"""
Dataset Import endpoints with RBAC protection.
Handles importing multi-sensor datasets from folder structures, uploads, ZIPs and video.

Business logic (parsing, frame discovery, taxonomy derivation, storage mirroring,
per-scene annotation import) lives in ``app.services.dataset_import``.
"""
import json
import logging
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from app.api.v1.endpoints.datasets import auto_create_tasks_for_scene
from app.core.config import settings
from app.core.database import get_db
from app.core.file_security import (
    DATA_EXTENSIONS,
    rename_data_files_to_uuid,
    safe_zip_extract,
    validate_magic_bytes,
    validate_upload_path,
)
from app.models.models import (
    Dataset,
    Frame,
    Permission,
    Scene,
    User,
)
from app.services.dataset_import import (
    GENERIC_FOLDER_NAMES,
    UPLOAD_DIR,
    BrowseFolderResponse,
    FolderItem,
    ImportRequest,
    ImportResponse,
    RenamedScene,
    SceneConflict,
    SceneNameCheckRequest,
    SceneNameCheckResponse,
    build_import_frame_rows,
    classify_scene_data_files,
    derive_and_merge_taxonomy,
    detect_ego_to_lidar_rotation,
    detect_scene_dirs,
    discover_frames,
    find_data_files,
    generate_smart_scene_name,
    get_or_create_scene_import_task,
    get_storage_paths,
    import_scene_annotations,
    load_ego_poses,
    parse_calibration_file,
    scan_annotations_for_classes,
    schedule_scene_mirror,
)
from app.services.rbac_service import RequirePermissions, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()

@router.get("/browse", response_model=BrowseFolderResponse)
async def browse_folders(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    path: str = "/",
) -> BrowseFolderResponse:
    """
    Browse server filesystem directories.
    Requires DATASETS_IMPORT permission.

    Only paths under ALLOWED_BROWSE_ROOTS (/uploads, /data by default) are
    accessible. Any path outside those roots, and any symlink that would
    escape them, is rejected with 403.
    """
    allowed_roots: list[Path] = [
        Path(r).resolve() for r in settings.ALLOWED_BROWSE_ROOTS
    ]

    def _is_within_allowed(p: Path) -> bool:
        """Return True iff *p* is equal to or a descendant of an allowed root."""
        return any(p == root or root in p.parents for root in allowed_roots)

    try:
        folder_path = Path(path).resolve()

        if not _is_within_allowed(folder_path):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: path is outside allowed directories",
            )

        if not folder_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Path does not exist: {path}",
            )

        if not folder_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Path is not a directory: {path}",
            )

        items: List[FolderItem] = []

        try:
            for entry in sorted(folder_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if entry.name.startswith('.'):
                    continue

                if entry.is_symlink():
                    try:
                        resolved_entry = entry.resolve()
                    except OSError:
                        continue
                    if not _is_within_allowed(resolved_entry):
                        continue

                try:
                    is_dir = entry.is_dir()
                    size = None if is_dir else entry.stat().st_size
                    items.append(FolderItem(
                        name=entry.name,
                        path=str(entry),
                        is_directory=is_dir,
                        size=size,
                    ))
                except PermissionError:
                    continue

        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied accessing: {path}",
            )

        raw_parent = folder_path.parent
        if folder_path == folder_path.parent or not _is_within_allowed(raw_parent):
            parent_path = None
        else:
            parent_path = str(raw_parent)

        return BrowseFolderResponse(
            current_path=str(folder_path),
            parent_path=parent_path,
            items=items,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error browsing folder: {str(e)}",
        )



@router.post("/check-scene-names", response_model=SceneNameCheckResponse)
async def check_scene_names(
    request: SceneNameCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SceneNameCheckResponse:
    """Check which scene folder names already exist in the dataset before uploading."""
    conflicts: List[SceneConflict] = []
    for i, folder_name in enumerate(request.folder_names):
        scene_name = folder_name if request.preserve_folder_names else generate_smart_scene_name(folder_name, i + 1)
        result = await db.execute(
            select(Scene).where(
                Scene.dataset_id == request.dataset_id,
                Scene.name == scene_name,
                Scene.is_deleted == False,
            )
        )
        if result.scalar_one_or_none():
            suggested = f"{scene_name}_upload-{datetime.now().strftime('%Y%m%d_%H%M')}"
            conflicts.append(SceneConflict(original_name=scene_name, suggested_name=suggested))
    return SceneNameCheckResponse(conflicts=conflicts)


@router.post("/upload", response_model=ImportResponse)
async def upload_and_import_dataset(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    files: List[UploadFile] = File(...),
    derive_taxonomy: bool = Form(False),
    overwrite_annotations: bool = Form(False),
    preserve_folder_names: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Upload files from user's browser and import them as a dataset.
    Requires DATASETS_IMPORT permission.
    
    Files should be uploaded with their relative paths preserved.
    Files are stored permanently in /uploads/{dataset_id}/{scene_name}/
    
    Args:
        dataset_id: ID of the dataset to import into
        files: List of files to upload
        derive_taxonomy: If True, scan annotations and create/merge taxonomy from discovered classes
        overwrite_annotations: If True, delete existing annotations before importing new ones
        preserve_folder_names: If True, keep original folder names; if False, apply smart naming
    """
    query = select(Dataset).options(selectinload(Dataset.campaign)).where(Dataset.id == UUID(dataset_id))
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {dataset_id}"
        )
    
    dataset_upload_dir = UPLOAD_DIR / dataset_id
    dataset_upload_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp(prefix="dataset_upload_")
    
    try:
        for file in files:
            raw_path = file.filename or "unknown"

            relative_path = validate_upload_path(raw_path)

            content = await file.read()

            leaf_name = Path(relative_path).name
            leaf_ext = Path(leaf_name).suffix.lower()
            if leaf_ext in DATA_EXTENSIONS:
                validate_magic_bytes(content, leaf_name)

            file_path = Path(temp_dir) / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "wb") as f:
                f.write(content)

        root_path = Path(temp_dir)
        
        print(f"[IMPORT DEBUG] Initial root_path: {root_path}")
        print(f"[IMPORT DEBUG] Contents: {list(root_path.iterdir())}")
        
        subdirs = [d for d in root_path.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and not (root_path / "metadata.json").exists():
            root_path = subdirs[0]
        
        scenes_imported = 0
        frames_imported = 0
        errors: List[str] = []
        renamed_scenes: List[RenamedScene] = []

        calibration_data = {}
        calibration_path = root_path / "calibration"
        if calibration_path.exists():
            calibration_data = parse_calibration_file(calibration_path)
        
        scene_dirs, scene_parent_names = detect_scene_dirs(root_path, debug=True)
        
        print(f"[IMPORT DEBUG] Scene directories to import: {[d.name for d in scene_dirs]}")
        print(f"[IMPORT DEBUG] Number of scene_dirs: {len(scene_dirs)}")
        
        if derive_taxonomy and scene_dirs:
            print("[IMPORT] derive_taxonomy=True, scanning annotations for classes...")
            discovered_classes = scan_annotations_for_classes(scene_dirs)
            if discovered_classes:
                taxonomy = await derive_and_merge_taxonomy(
                    db=db,
                    dataset=dataset,
                    discovered_classes=discovered_classes,
                    user_id=current_user.id,
                )
                if taxonomy:
                    errors.append(f"Taxonomy: Created/updated '{taxonomy.name}' with {len(taxonomy.classes)} classes")
            else:
                errors.append("Taxonomy: No annotation classes found to derive")
        
        for scene_index, scene_dir in enumerate(scene_dirs, start=1):
            try:
                raw_folder_name = scene_parent_names.get(scene_dir, scene_dir.name)
                
                if preserve_folder_names and raw_folder_name.lower() not in GENERIC_FOLDER_NAMES:
                    scene_name = raw_folder_name
                else:
                    scene_name = generate_smart_scene_name(raw_folder_name, scene_index)
                
                scene_meta_path = scene_dir / "scene_metadata.json"
                scene_meta = {}
                if scene_meta_path.exists():
                    with open(scene_meta_path) as f:
                        scene_meta = json.load(f)
                
                data_files, data_source = classify_scene_data_files(scene_dir)
                frame_count = len(data_files)
                
                if frame_count == 0:
                    errors.append(f"Scene {scene_name}: No frames detected")
                    continue
                
                scene_id = uuid.uuid4()
                permanent_scene_dir = dataset_upload_dir / str(scene_id)
                permanent_scene_dir.mkdir(parents=True, exist_ok=True)
                
                for item in scene_dir.iterdir():
                    src = item
                    dst = permanent_scene_dir / item.name
                    if item.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                
                uuid_rename_map = rename_data_files_to_uuid(permanent_scene_dir, DATA_EXTENSIONS)

                org_id_val = dataset.campaign.organization_id
                schedule_scene_mirror(
                    org_id_val, dataset.id, scene_id, permanent_scene_dir,
                )

                parent_dir = scene_dir.parent
                if parent_dir != scene_dir:
                    sibling_annotations = parent_dir / "annotations"
                    if sibling_annotations.exists() and sibling_annotations.is_dir():
                        annotations_dst = permanent_scene_dir / "annotations"
                        if not annotations_dst.exists():
                            try:
                                shutil.copytree(sibling_annotations, annotations_dst)
                            except Exception as e:
                                errors.append(f"Scene {scene_name}: Failed to copy annotations folder: {str(e)}")

                permanent_lidar_path = permanent_scene_dir / "lidar"
                permanent_images_path = permanent_scene_dir / "images"
                permanent_cameras_path = permanent_scene_dir / "cameras"
                
                relative_path_base = f"uploads/{dataset.id}/{scene_id}"
                
                cameras_storage_paths: Dict[str, str] = {}
                if permanent_cameras_path.exists():
                    for cam_dir in permanent_cameras_path.iterdir():
                        if cam_dir.is_dir():
                            cameras_storage_paths[cam_dir.name] = f"{relative_path_base}/cameras/{cam_dir.name}"

                permanent_ego_poses_file = permanent_scene_dir / "ego_poses" / "poses.json"
                if not permanent_ego_poses_file.exists():
                    permanent_ego_poses_file = permanent_scene_dir / "ego_poses" / "ego_poses.json"

                ego_poses_path = None
                ego_poses_data: Dict[int, Dict[str, Any]] = {}
                if permanent_ego_poses_file.exists():
                    ego_poses_path = f"{relative_path_base}/ego_poses/{permanent_ego_poses_file.name}"
                    with open(permanent_ego_poses_file, "r") as f:
                        poses_json = json.load(f)
                        if "frames" in poses_json:
                            for pose_entry in poses_json["frames"]:
                                frame_idx = pose_entry.get("frame_index", -1)
                                if frame_idx >= 0:
                                    ego_poses_data[frame_idx] = {
                                        "position": pose_entry.get("position", [0, 0, 0]),
                                        "rotation": pose_entry.get("rotation", [1, 0, 0, 0]),
                                        "velocity": pose_entry.get("velocity"),
                                        "timestamp": pose_entry.get("timestamp"),
                                    }
                else:
                    parent_metadata_file = scene_dir.parent / "metadata.json"
                    if parent_metadata_file.exists():
                        try:
                            with open(parent_metadata_file, "r") as f:
                                parent_meta = json.load(f)
                            for frame_entry in parent_meta.get("frames", []):
                                ep = frame_entry.get("ego_pose")
                                if ep and isinstance(ep, dict) and ep.get("position"):
                                    frame_idx = frame_entry.get("frame_index", -1)
                                    if frame_idx >= 0:
                                        ego_poses_data[frame_idx] = {
                                            "position": ep.get("position", [0, 0, 0]),
                                            "rotation": ep.get("rotation", [1, 0, 0, 0]),
                                            "velocity": ep.get("velocity"),
                                            "timestamp": ep.get("timestamp"),
                                        }
                            if ego_poses_data:
                                ego_poses_dir = permanent_scene_dir / "ego_poses"
                                ego_poses_dir.mkdir(exist_ok=True)
                                synth_poses_file = ego_poses_dir / "ego_poses.json"
                                poses_out = {"frames": [
                                    {"frame_index": idx, **data}
                                    for idx, data in sorted(ego_poses_data.items())
                                ]}
                                with open(synth_poses_file, "w") as f:
                                    json.dump(poses_out, f, indent=2)
                                ego_poses_path = f"{relative_path_base}/ego_poses/ego_poses.json"
                        except Exception as e:
                            print(f"[IMPORT] Failed to read ego_poses from metadata.json: {e}")

                permanent_calib_file = permanent_scene_dir / "calibration.json"
                permanent_calib_dir = permanent_scene_dir / "calibration"
                calibration_data = None
                if permanent_calib_file.exists():
                    calibration_data = parse_calibration_file(permanent_calib_file, ego_poses_data)
                elif permanent_calib_dir.exists():
                    calibration_data = parse_calibration_file(permanent_calib_dir, ego_poses_data)
                elif ego_poses_data:
                    rotation = detect_ego_to_lidar_rotation(ego_poses_data)
                    calibration_data = {
                        "lidar_to_cameras": {},
                        "ego_to_lidar": {"rotation": rotation, "translation": [0, 0, 0]},
                    }

                existing_scene_query = select(Scene).where(
                    Scene.dataset_id == dataset.id,
                    Scene.name == scene_name,
                    Scene.is_deleted == False,
                )
                existing_result = await db.execute(existing_scene_query)
                if existing_result.scalar_one_or_none():
                    original_name = scene_name
                    scene_name = f"{scene_name}_upload-{datetime.now().strftime('%Y%m%d_%H%M')}"
                    renamed_scenes.append(RenamedScene(original_name=original_name, new_name=scene_name, scene_id=str(scene_id)))

                scene = Scene(
                    id=scene_id,
                    dataset_id=dataset.id,
                    name=scene_name,
                    description=scene_meta.get("description", f"Imported scene: {scene_name}"),
                    frame_count=frame_count,
                    fps=scene_meta.get("fps", 10.0),
                    scene_metadata={
                        "location": scene_meta.get("location"),
                        "weather": scene_meta.get("weather"),
                        "time_of_day": scene_meta.get("time_of_day"),
                        "source": "browser_upload",
                        "data_source": data_source,
                    },
                    calibration=calibration_data,
                    storage_paths={
                        "root": str(permanent_scene_dir),
                        "lidar_base": f"{relative_path_base}/lidar" if permanent_lidar_path.exists() else None,
                        "images_base": f"{relative_path_base}/images" if permanent_images_path.exists() else None,
                        "cameras": cameras_storage_paths if cameras_storage_paths else None,
                        "ego_poses": ego_poses_path,
                    },
                )
                db.add(scene)
                await db.flush()
                await auto_create_tasks_for_scene(db, scene)
                await db.flush()

                permanent_data_files: List[Path] = []
                lidar_files: List[Path] = []
                camera_files: Dict[str, List[Path]] = {}
                
                if permanent_lidar_path.exists():
                    lidar_files = sorted([f for f in permanent_lidar_path.iterdir() if f.is_file()], key=lambda x: x.name)
                    permanent_data_files = lidar_files
                
                if permanent_cameras_path.exists():
                    for cam_dir in permanent_cameras_path.iterdir():
                        if cam_dir.is_dir():
                            cam_files = sorted([f for f in cam_dir.iterdir() if f.is_file()], key=lambda x: x.name)
                            if cam_files:
                                camera_files[cam_dir.name] = cam_files
                    if not permanent_data_files and camera_files:
                        first_cam = next(iter(camera_files.values()))
                        permanent_data_files = first_cam
                
                if not permanent_data_files:
                    if permanent_images_path.exists():
                        permanent_data_files = sorted([f for f in permanent_images_path.iterdir() if f.is_file()], key=lambda x: x.name)
                    else:
                        permanent_data_files = sorted(find_data_files(permanent_scene_dir), key=lambda x: x.name)
                
                if permanent_data_files and not camera_files and not lidar_files:
                    camera_name = scene_dir.name if scene_dir.name != "default_scene" else scene_name
                    camera_files = {camera_name: permanent_data_files}
                    cameras_storage_paths = {camera_name: f"{relative_path_base}"}
                    scene.storage_paths = {
                        **scene.storage_paths,
                        "cameras": cameras_storage_paths
                    }
                    attributes.flag_modified(scene, "storage_paths")
                    print(f"[IMPORT] Treating flat image structure as single camera: {camera_name}, path: {relative_path_base}")
                
                for frame in build_import_frame_rows(
                    scene=scene,
                    permanent_scene_dir=permanent_scene_dir,
                    permanent_data_files=permanent_data_files,
                    lidar_files=lidar_files,
                    camera_files=camera_files,
                    uuid_rename_map=uuid_rename_map,
                    ego_poses_data=ego_poses_data,
                ):
                    db.add(frame)
                
                await db.flush()

                task = await get_or_create_scene_import_task(
                    db=db,
                    scene=scene,
                    assignee_id=current_user.id,
                    frame_count=frame_count,
                    description=f"Auto-created for {scene_name} ({frame_count} frames)",
                )
                print(f"[IMPORT] Using task {task.id} for imported annotations")
                
                try:
                    annotations_3d, annotations_2d = await import_scene_annotations(
                        db=db,
                        scene=scene,
                        scene_dir=permanent_scene_dir,
                        task=task,
                        overwrite=overwrite_annotations,
                    )
                    if annotations_3d > 0 or annotations_2d > 0:
                        errors.append(f"Scene {scene_name}: Imported {annotations_3d} 3D and {annotations_2d} 2D annotations")
                except Exception as e:
                    errors.append(f"Scene {scene_name}: Failed to import annotations: {str(e)}")
                
                scenes_imported += 1
                frames_imported += frame_count
                print(f"[IMPORT] Successfully imported scene {scene_name} with {frame_count} frames. Total: {scenes_imported} scenes, {frames_imported} frames")
                
            except Exception as e:
                import traceback
                print(f"[IMPORT ERROR] Scene {scene_dir.name}: {str(e)}")
                print(f"[IMPORT ERROR] Traceback: {traceback.format_exc()}")
                errors.append(f"Scene {scene_dir.name}: {str(e)}")
        
        await db.commit()
        
        return ImportResponse(
            success=scenes_imported > 0,
            message=f"Imported {scenes_imported} scenes with {frames_imported} frames",
            scenes_imported=scenes_imported,
            frames_imported=frames_imported,
            errors=errors,
            renamed_scenes=renamed_scenes,
        )

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


@router.post("/upload-zip", response_model=ImportResponse)
async def upload_zip_and_import_dataset(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    file: UploadFile = File(..., description="ZIP file containing the dataset folder"),
    derive_taxonomy: bool = Form(False),
    overwrite_annotations: bool = Form(False),
    preserve_folder_names: bool = Form(True),
    name_overrides: str = Form(default='{}'),
    scene_descriptions: str = Form(default='{}'),
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Upload a ZIP file containing a dataset and import it.
    Requires DATASETS_IMPORT permission.
    
    Use this endpoint when you have more than 1000 files (browser limitation).
    The ZIP file should contain the dataset folder structure.
    
    Args:
        dataset_id: ID of the dataset to import into
        file: ZIP file containing the dataset
        derive_taxonomy: If True, scan annotations and create/merge taxonomy from discovered classes
        overwrite_annotations: If True, delete existing annotations before importing new ones
        preserve_folder_names: If True, keep original folder names; if False, apply smart naming
    """
    log.info(f"[ZIP IMPORT] Received upload request: dataset_id={dataset_id}, filename={file.filename}, content_type={file.content_type}")
    
    if not file.filename or not file.filename.lower().endswith('.zip'):
        log.error(f"[ZIP IMPORT] Invalid file extension: {file.filename}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a ZIP archive (.zip)"
        )
    validate_upload_path(file.filename)
    
    query = select(Dataset).options(selectinload(Dataset.campaign)).where(Dataset.id == UUID(dataset_id))
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {dataset_id}"
        )
    
    dataset_upload_dir = UPLOAD_DIR / dataset_id
    dataset_upload_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp(prefix="dataset_zip_upload_")
    zip_path = Path(temp_dir) / "upload.zip"
    
    try:
        print("[ZIP IMPORT] Receiving uploaded ZIP file...")
        file_size = 0
        chunk_size = 1024 * 1024 * 10
        
        with open(zip_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                file_size += len(chunk)
                if file_size % (chunk_size * 10) == 0:
                    print(f"[ZIP IMPORT] Received {file_size / (1024*1024):.1f} MB...")
        
        print(f"[ZIP IMPORT] Uploaded file size: {file_size / (1024*1024):.1f} MB")
        print("[ZIP IMPORT] Extracting ZIP file...")
        extract_dir = Path(temp_dir) / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        zip_magic = zip_path.read_bytes()[:4]
        if zip_magic != b"PK\x03\x04":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is not a valid ZIP archive (magic bytes mismatch).",
            )

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                safe_zip_extract(zip_ref, extract_dir)
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or corrupted ZIP file"
            )
        
        root_path = extract_dir
        subdirs = [d for d in root_path.iterdir() if d.is_dir() and not d.name.startswith('.') and d.name != "__MACOSX"]

        if len(subdirs) == 1 and not (root_path / "metadata.json").exists():
            root_path = subdirs[0]

        try:
            name_overrides_dict: Dict[str, str] = json.loads(name_overrides)
        except Exception:
            name_overrides_dict = {}

        try:
            scene_descriptions_dict: Dict[str, str] = json.loads(scene_descriptions)
        except Exception:
            scene_descriptions_dict = {}

        scenes_imported = 0
        frames_imported = 0
        errors: List[str] = []
        renamed_scenes: List[RenamedScene] = []

        calibration_data = {}
        calibration_path = root_path / "calibration"
        if calibration_path.exists():
            calibration_data = parse_calibration_file(calibration_path)
        
        scene_dirs, scene_parent_names = detect_scene_dirs(root_path)
        
        print(f"[ZIP IMPORT] Scene directories to import: {[d.name for d in scene_dirs]}")
        
        if derive_taxonomy and scene_dirs:
            print("[ZIP IMPORT] derive_taxonomy=True, scanning annotations for classes...")
            discovered_classes = scan_annotations_for_classes(scene_dirs)
            if discovered_classes:
                taxonomy = await derive_and_merge_taxonomy(
                    db=db,
                    dataset=dataset,
                    discovered_classes=discovered_classes,
                    user_id=current_user.id,
                )
                if taxonomy:
                    errors.append(f"Taxonomy: Created/updated '{taxonomy.name}' with {len(taxonomy.classes)} classes")
            else:
                errors.append("Taxonomy: No annotation classes found to derive")
        
        for scene_index, scene_dir in enumerate(scene_dirs, start=1):
            try:
                raw_folder_name = scene_parent_names.get(scene_dir, scene_dir.name)

                if preserve_folder_names and raw_folder_name.lower() not in GENERIC_FOLDER_NAMES:
                    scene_name = raw_folder_name
                else:
                    scene_name = generate_smart_scene_name(raw_folder_name, scene_index)

                original_scene_name = scene_name
                user_override = name_overrides_dict.get(scene_name)
                if user_override:
                    scene_name = user_override
                user_description = scene_descriptions_dict.get(original_scene_name) or None

                scene_meta_path = scene_dir / "scene_metadata.json"
                scene_meta = {}
                if scene_meta_path.exists():
                    with open(scene_meta_path) as f:
                        scene_meta = json.load(f)
                
                data_files, data_source = classify_scene_data_files(scene_dir)
                frame_count = len(data_files)
                
                if frame_count == 0:
                    errors.append(f"Scene {scene_name}: No frames detected")
                    continue
                
                scene_id = uuid.uuid4()
                permanent_scene_dir = dataset_upload_dir / str(scene_id)
                permanent_scene_dir.mkdir(parents=True, exist_ok=True)
                
                for item in scene_dir.iterdir():
                    src = item
                    dst = permanent_scene_dir / item.name
                    if item.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)

                zip_uuid_rename_map = rename_data_files_to_uuid(
                    permanent_scene_dir, DATA_EXTENSIONS
                )

                org_id_val = dataset.campaign.organization_id
                schedule_scene_mirror(
                    org_id_val, dataset.id, scene_id, permanent_scene_dir,
                )

                parent_dir = scene_dir.parent
                if parent_dir != scene_dir:
                    sibling_annotations = parent_dir / "annotations"
                    if sibling_annotations.exists() and sibling_annotations.is_dir():
                        annotations_dst = permanent_scene_dir / "annotations"
                        if not annotations_dst.exists():
                            try:
                                shutil.copytree(sibling_annotations, annotations_dst)
                            except Exception as e:
                                errors.append(f"Scene {scene_name}: Failed to copy annotations folder: {str(e)}")
                
                permanent_lidar_path = permanent_scene_dir / "lidar"
                permanent_images_path = permanent_scene_dir / "images"
                permanent_cameras_path = permanent_scene_dir / "cameras"
                
                relative_path_base = f"uploads/{dataset.id}/{scene_id}"
                
                cameras_storage_paths: Dict[str, str] = {}
                if permanent_cameras_path.exists():
                    for cam_dir in permanent_cameras_path.iterdir():
                        if cam_dir.is_dir():
                            cameras_storage_paths[cam_dir.name] = f"{relative_path_base}/cameras/{cam_dir.name}"
                elif permanent_images_path.exists():
                    cameras_storage_paths["images"] = f"{relative_path_base}/images"
                
                ego_poses_data: Dict[int, Any] = {}
                ego_poses_path = permanent_scene_dir / "ego_poses" / "poses.json"
                if not ego_poses_path.exists():
                    ego_poses_path = permanent_scene_dir / "ego_poses" / "ego_poses.json"
                if ego_poses_path.exists():
                    with open(ego_poses_path) as f:
                        poses_raw = json.load(f)
                        if isinstance(poses_raw, dict) and "frames" in poses_raw:
                            for pose_entry in poses_raw["frames"]:
                                idx = pose_entry.get("frame_index", -1)
                                if idx >= 0:
                                    ego_poses_data[idx] = {
                                        "position": pose_entry.get("position", [0, 0, 0]),
                                        "rotation": pose_entry.get("rotation", [1, 0, 0, 0]),
                                        "velocity": pose_entry.get("velocity"),
                                        "timestamp": pose_entry.get("timestamp"),
                                    }
                        elif isinstance(poses_raw, list):
                            for idx, pose in enumerate(poses_raw):
                                ego_poses_data[idx] = pose

                scene_calibration = calibration_data
                scene_calibration_path = permanent_scene_dir / "calibration.json"
                scene_calib_dir = permanent_scene_dir / "calibration"
                if scene_calibration_path.exists():
                    scene_calibration = parse_calibration_file(scene_calibration_path, ego_poses_data)
                elif scene_calib_dir.exists():
                    scene_calibration = parse_calibration_file(scene_calib_dir, ego_poses_data)
                elif ego_poses_data:
                    rotation = detect_ego_to_lidar_rotation(ego_poses_data)
                    scene_calibration = {
                        "lidar_to_cameras": scene_calibration.get("lidar_to_cameras", {}) if isinstance(scene_calibration, dict) else {},
                        "ego_to_lidar": {"rotation": rotation, "translation": [0, 0, 0]},
                    }
                
                if not user_override:
                    existing_scene_query = select(Scene).where(
                        Scene.dataset_id == dataset.id,
                        Scene.name == scene_name,
                        Scene.is_deleted == False,
                    )
                    existing_result = await db.execute(existing_scene_query)
                    if existing_result.scalar_one_or_none():
                        original_name = scene_name
                        scene_name = f"{scene_name}_upload-{datetime.now().strftime('%Y%m%d_%H%M')}"
                        renamed_scenes.append(RenamedScene(original_name=original_name, new_name=scene_name, scene_id=str(scene_id)))

                scene = Scene(
                    dataset_id=dataset.id,
                    name=scene_name,
                    description=user_description or scene_meta.get("description"),
                    scene_metadata={
                        "location": scene_meta.get("location"),
                        "weather": scene_meta.get("weather"),
                        "time_of_day": scene_meta.get("time_of_day"),
                        "recording_date": scene_meta.get("recording_date"),
                    },
                    frame_count=frame_count,
                    fps=scene_meta.get("fps", 10.0),
                    calibration=scene_calibration if scene_calibration else {},
                    storage_paths={
                        "lidar_base": f"{relative_path_base}/lidar" if permanent_lidar_path.exists() else None,
                        "cameras": cameras_storage_paths,
                    },
                )
                db.add(scene)
                await db.flush()
                await auto_create_tasks_for_scene(db, scene)
                await db.flush()

                permanent_data_files = []
                lidar_files = []
                camera_files: Dict[str, List[Path]] = {}
                
                if permanent_lidar_path.exists():
                    lidar_files = sorted([f for f in permanent_lidar_path.iterdir() if f.suffix.lower() in [".pcd", ".bin", ".ply"]], key=lambda x: x.name)
                    permanent_data_files = lidar_files
                
                if permanent_cameras_path.exists():
                    for cam_dir in permanent_cameras_path.iterdir():
                        if cam_dir.is_dir():
                            cam_images = sorted([f for f in cam_dir.iterdir() if f.suffix.lower() in [".jpg", ".png", ".jpeg"]], key=lambda x: x.name)
                            camera_files[cam_dir.name] = cam_images
                            if not permanent_data_files:
                                permanent_data_files = cam_images
                elif permanent_images_path.exists():
                    images = sorted([f for f in permanent_images_path.iterdir() if f.suffix.lower() in [".jpg", ".png", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"]], key=lambda x: x.name)
                    camera_files["images"] = images
                    if not permanent_data_files:
                        permanent_data_files = images
                
                if not permanent_data_files:
                    all_root_files = sorted(find_data_files(permanent_scene_dir), key=lambda x: x.name)
                    pcd_root_files = [f for f in all_root_files if f.suffix.lower() in {".pcd", ".bin", ".ply"}]
                    img_root_files = [f for f in all_root_files if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}]

                    if pcd_root_files:
                        lidar_files = pcd_root_files
                        permanent_data_files = pcd_root_files
                        scene.storage_paths = {
                            **scene.storage_paths,
                            "lidar_base": relative_path_base,
                        }
                        attributes.flag_modified(scene, "storage_paths")

                    if img_root_files:
                        camera_files["default"] = img_root_files
                        if not permanent_data_files:
                            permanent_data_files = img_root_files
                        scene.storage_paths = {
                            **scene.storage_paths,
                            "cameras": {
                                **(scene.storage_paths.get("cameras") or {}),
                                "default": relative_path_base,
                            },
                        }
                        attributes.flag_modified(scene, "storage_paths")
                
                for frame in build_import_frame_rows(
                    scene=scene,
                    permanent_scene_dir=permanent_scene_dir,
                    permanent_data_files=permanent_data_files,
                    lidar_files=lidar_files,
                    camera_files=camera_files,
                    uuid_rename_map=zip_uuid_rename_map,
                    ego_poses_data=ego_poses_data,
                ):
                    db.add(frame)
                
                await db.flush()

                task = await get_or_create_scene_import_task(
                    db=db,
                    scene=scene,
                    assignee_id=current_user.id,
                    frame_count=frame_count,
                    description=f"Auto-created for {scene_name} ({frame_count} frames)",
                )
                print(f"[ZIP IMPORT] Using task {task.id} for imported annotations")
                
                try:
                    annotations_3d, annotations_2d = await import_scene_annotations(
                        db=db,
                        scene=scene,
                        scene_dir=permanent_scene_dir,
                        task=task,
                        overwrite=overwrite_annotations,
                    )
                    if annotations_3d > 0 or annotations_2d > 0:
                        errors.append(f"Scene {scene_name}: Imported {annotations_3d} 3D and {annotations_2d} 2D annotations")
                except Exception as e:
                    errors.append(f"Scene {scene_name}: Failed to import annotations: {str(e)}")
                
                scenes_imported += 1
                frames_imported += frame_count
                print(f"[ZIP IMPORT] Successfully imported scene {scene_name} with {frame_count} frames")
                
            except Exception as e:
                import traceback
                print(f"[ZIP IMPORT ERROR] Scene {scene_dir.name}: {str(e)}")
                print(f"[ZIP IMPORT ERROR] Traceback: {traceback.format_exc()}")
                errors.append(f"Scene {scene_dir.name}: {str(e)}")
        
        await db.commit()
        
        return ImportResponse(
            success=scenes_imported > 0,
            message=f"Imported {scenes_imported} scenes with {frames_imported} frames from ZIP",
            scenes_imported=scenes_imported,
            frames_imported=frames_imported,
            errors=errors,
            renamed_scenes=renamed_scenes,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ZIP upload failed: {str(e)}"
        )
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


@router.post("/upload-video", response_model=ImportResponse)
async def upload_video_and_import_dataset(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    file: UploadFile = File(..., description="Video file (MP4, AVI, MOV, MKV, WebM)"),
    extraction_fps: Optional[float] = Form(None, description="FPS to extract frames at (default: auto-detect)"),
    max_frames: Optional[int] = Form(None, description="Maximum number of frames to extract"),
    image_format: str = Form("jpg", description="Output image format (jpg, png, webp)"),
    preserve_folder_names: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Upload a video file and extract frames to create a scene with a task.
    Requires DATASETS_IMPORT permission.
    
    The video will be processed to extract frames at the specified FPS.
    Each video becomes a scene with extracted frames as camera images.
    A task is automatically created for annotation.
    
    Args:
        dataset_id: ID of the dataset to import into
        file: Video file to upload (MP4, AVI, MOV, MKV, WebM)
        extraction_fps: FPS to extract frames at (default: video's native FPS)
        max_frames: Maximum number of frames to extract (default: no limit)
        image_format: Output image format - jpg, png, or webp (default: jpg)
        preserve_folder_names: If True, use video filename as scene name
    """
    from app.core.file_security import VIDEO_EXTENSIONS as ALLOWED_VIDEO_EXT
    from app.services.video_service import (
        extract_frames_async,
        get_video_metadata,
        is_ffmpeg_available,
        validate_video_magic_bytes,
    )
    
    if not is_ffmpeg_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video processing is not available. Please install ffmpeg on the server."
        )
    
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required"
        )
    
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid video format. Supported formats: {', '.join(ALLOWED_VIDEO_EXT)}"
        )
    
    validate_upload_path(file.filename)
    
    query = select(Dataset).options(selectinload(Dataset.campaign)).where(Dataset.id == UUID(dataset_id))
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {dataset_id}"
        )
    
    dataset_upload_dir = UPLOAD_DIR / dataset_id
    dataset_upload_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = tempfile.mkdtemp(prefix="video_upload_")
    video_path = Path(temp_dir) / f"video{file_ext}"
    permanent_scene_dir = None

    try:
        log.info(f"[VIDEO IMPORT] Receiving video file: {file.filename}")
        file_size = 0
        chunk_size = 1024 * 1024 * 10
        
        with open(video_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                file_size += len(chunk)
        
        log.info(f"[VIDEO IMPORT] Video file size: {file_size / (1024*1024):.1f} MB")
        
        with open(video_path, "rb") as f:
            header = f.read(16)
        
        if not validate_video_magic_bytes(header, file_ext):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match expected {file_ext.upper()[1:]} format"
            )
        
        metadata = get_video_metadata(video_path)
        if not metadata or metadata.get("duration", 0) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not read video metadata. The file may be corrupted."
            )
        
        log.info(f"[VIDEO IMPORT] Video metadata: {metadata}")
        
        video_name = Path(file.filename).stem
        if preserve_folder_names and video_name.lower() not in GENERIC_FOLDER_NAMES:
            scene_name = video_name
        else:
            scene_name = generate_smart_scene_name(video_name, 1)
        
        existing_scene_query = select(Scene).where(
            Scene.dataset_id == dataset.id,
            Scene.name == scene_name,
            Scene.is_deleted == False,
        )
        existing_result = await db.execute(existing_scene_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A scene with the name '{scene_name}' already exists in this dataset",
            )
        
        scene_id = uuid.uuid4()
        permanent_scene_dir = dataset_upload_dir / str(scene_id)
        frames_dir = permanent_scene_dir / "cameras" / "video"
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        log.info(f"[VIDEO IMPORT] Extracting frames at {extraction_fps or 'native'} FPS...")
        frame_paths, extraction_metadata = await extract_frames_async(
            video_path=video_path,
            output_dir=frames_dir,
            fps=extraction_fps,
            max_frames=max_frames,
            image_format=image_format,
        )
        
        frame_count = len(frame_paths)
        log.info(f"[VIDEO IMPORT] Extracted {frame_count} frames")
        
        if frame_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No frames could be extracted from the video"
            )
        
        uuid_rename_map = rename_data_files_to_uuid(permanent_scene_dir, DATA_EXTENSIONS)
        
        org_id_val = dataset.campaign.organization_id
        schedule_scene_mirror(
            org_id_val, dataset.id, scene_id, permanent_scene_dir,
        )
        
        relative_path_base = f"uploads/{dataset.id}/{scene_id}"
        cameras_storage_paths = {"video": f"{relative_path_base}/cameras/video"}
        
        video_scene_metadata = {
            "source": "video_upload",
            "original_filename": file.filename,
            "video_duration": extraction_metadata.get("duration"),
            "video_fps": extraction_metadata.get("fps"),
            "video_resolution": [extraction_metadata.get("width"), extraction_metadata.get("height")],
            "video_codec": extraction_metadata.get("codec"),
            "extraction_fps": extraction_metadata.get("extraction_fps"),
            "frames_extracted": frame_count,
        }
        
        scene = Scene(
            id=scene_id,
            dataset_id=dataset.id,
            name=scene_name,
            description=f"Extracted from video: {file.filename}",
            frame_count=frame_count,
            fps=extraction_metadata.get("extraction_fps") or extraction_metadata.get("fps") or 30.0,
            scene_metadata=video_scene_metadata,
            calibration={},
            storage_paths={
                "root": str(permanent_scene_dir),
                "cameras": cameras_storage_paths,
            },
        )
        db.add(scene)
        await db.flush()
        await auto_create_tasks_for_scene(db, scene)
        await db.flush()

        permanent_frame_files = sorted(frames_dir.glob(f"*.{image_format}"), key=lambda x: x.name)
        timestamps = extraction_metadata.get("timestamps", [])
        
        for frame_idx, frame_file in enumerate(permanent_frame_files):
            frame_file_paths = {
                "cameras": {"video": frame_file.name},
                "_meta": {
                    "absolute_path": str(frame_file),
                    "relative_path": str(frame_file.relative_to(permanent_scene_dir)),
                    "original_filename": uuid_rename_map.get(
                        str(frame_file.relative_to(permanent_scene_dir)), {}
                    ).get("original_name") or frame_file.name,
                },
            }
            
            frame_timestamp = timestamps[frame_idx] if frame_idx < len(timestamps) else frame_idx / scene.fps
            
            frame = Frame(
                scene_id=scene.id,
                frame_index=frame_idx,
                timestamp=frame_timestamp,
                file_paths=frame_file_paths,
                ego_pose=None,
            )
            db.add(frame)
        
        await db.flush()

        task = await get_or_create_scene_import_task(
            db=db,
            scene=scene,
            assignee_id=current_user.id,
            frame_count=frame_count,
            description=f"Auto-created for video {file.filename} ({frame_count} frames)",
        )
        log.info(f"[VIDEO IMPORT] Using task: {task.name}")
        
        await db.commit()
        
        return ImportResponse(
            success=True,
            message=f"Imported video as scene '{scene_name}' with {frame_count} frames",
            scenes_imported=1,
            frames_imported=frame_count,
            errors=[
                f"Video: {extraction_metadata.get('width')}x{extraction_metadata.get('height')} @ {extraction_metadata.get('fps'):.1f} fps",
                f"Extracted {frame_count} frames at {extraction_metadata.get('extraction_fps'):.1f} fps",
            ],
        )
        
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        if permanent_scene_dir is not None:
            try:
                shutil.rmtree(permanent_scene_dir)
            except Exception:
                pass
        log.warning(
            f"[VIDEO IMPORT] Scene name '{scene_name}' already exists in dataset "
            f"{dataset_id} (duplicate or concurrent upload)"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A scene named '{scene_name}' already exists in this dataset. "
                "It may have just been created by this same upload — refresh the "
                "dataset to check. To re-import, delete the existing scene or rename the file."
            ),
        )
    except Exception as e:
        await db.rollback()
        import traceback
        log.error(f"[VIDEO IMPORT ERROR] {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video upload failed: {str(e)}"
        )
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


@router.post("/import", response_model=ImportResponse)
async def import_dataset(
    request: ImportRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Import scenes and frames from a local dataset folder structure.
    Requires DATASETS_IMPORT permission.
    
    Expected folder structure:
    ```
    root_path/
    ├── metadata.json
    ├── calibration/
    │   ├── extrinsics.json
    │   └── intrinsics/
    │       └── {camera_id}.json
    └── scenes/
        └── {scene_id}/
            ├── scene_metadata.json
            ├── lidar/
            │   └── {frame}.pcd
            ├── cameras/
            │   └── {camera_id}/
            │       └── {frame}.jpg
            ├── ego_poses/
            │   └── poses.json
            └── timestamps.json
    ```
    """
    root_path = Path(request.root_path)
    
    if not root_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path does not exist: {root_path}"
        )
    
    dataset_query = select(Dataset).where(
        Dataset.id == request.dataset_id,
        Dataset.is_deleted == False,
    )
    result = await db.execute(dataset_query)
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {request.dataset_id} not found"
        )
    
    errors = []
    renamed_scenes: List[RenamedScene] = []
    scenes_imported = 0
    frames_imported = 0
    
    metadata_file = root_path / "metadata.json"
    sensor_config = {}
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
            sensor_config = metadata.get("sensors", {})
    
    calibration_path = root_path / "calibration"
    default_calibration = {}
    if calibration_path.exists():
        default_calibration = parse_calibration_file(calibration_path)
    
    scenes_path = root_path / "scenes"
    if not scenes_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No 'scenes' folder found in {root_path}"
        )
    
    for scene_dir in sorted(scenes_path.iterdir()):
        if not scene_dir.is_dir():
            continue
        
        try:
            scene_metadata_file = scene_dir / "scene_metadata.json"
            if scene_metadata_file.exists():
                with open(scene_metadata_file, 'r') as f:
                    scene_meta = json.load(f)
            else:
                lidar_path = scene_dir / "lidar"
                frame_count = len(list(lidar_path.glob("*.pcd"))) + len(list(lidar_path.glob("*.bin"))) if lidar_path.exists() else 0
                scene_meta = {
                    "scene_id": scene_dir.name,
                    "name": scene_dir.name,
                    "frame_count": frame_count,
                    "fps": 10.0
                }
            
            scene_calibration = default_calibration.copy()
            scene_ego_poses = load_ego_poses(scene_dir)
            scene_calib_file = scene_dir / "calibration.json"
            scene_calib_path = scene_dir / "calibration"
            if scene_calib_file.exists():
                scene_calibration = parse_calibration_file(scene_calib_file, scene_ego_poses)
            elif scene_calib_path.exists():
                scene_calibration = parse_calibration_file(scene_calib_path, scene_ego_poses)
            
            storage_paths = get_storage_paths(scene_dir, root_path)
            
            scene_id = uuid.uuid4()
            scene_name = scene_meta.get("name") or scene_dir.name
            existing_scene_query = select(Scene).where(
                Scene.dataset_id == request.dataset_id,
                Scene.name == scene_name,
                Scene.is_deleted == False,
            )
            existing_result = await db.execute(existing_scene_query)
            if existing_result.scalar_one_or_none():
                original_name = scene_name
                scene_name = f"{scene_name}_upload-{datetime.now().strftime('%Y%m%d_%H%M')}"
                renamed_scenes.append(RenamedScene(original_name=original_name, new_name=scene_name, scene_id=str(scene_id)))

            scene = Scene(
                id=scene_id,
                dataset_id=request.dataset_id,
                name=scene_name,
                description=f"Imported from {scene_dir.name}",
                scene_metadata={
                    "location": scene_meta.get("location"),
                    "weather": scene_meta.get("weather"),
                    "time_of_day": scene_meta.get("time_of_day"),
                    "recording_date": scene_meta.get("recording_date"),
                    "duration_seconds": scene_meta.get("duration_seconds"),
                    "ego_vehicle": scene_meta.get("ego_vehicle"),
                },
                frame_count=scene_meta.get("frame_count", 0),
                fps=scene_meta.get("fps", 10.0),
                calibration=scene_calibration,
                storage_paths=storage_paths,
            )
            db.add(scene)
            await db.flush()
            await auto_create_tasks_for_scene(db, scene)
            await db.flush()

            frames_data = discover_frames(scene_dir, sensor_config)
            for frame_data in frames_data:
                frame = Frame(
                    scene_id=scene.id,
                    frame_index=frame_data["frame_index"],
                    timestamp=frame_data["timestamp"],
                    ego_pose=frame_data.get("ego_pose"),
                    file_paths=frame_data["file_paths"],
                )
                db.add(frame)
                frames_imported += 1
            
            scenes_imported += 1
            
        except Exception as e:
            errors.append(f"Error importing scene {scene_dir.name}: {str(e)}")
    
    await db.commit()
    
    return ImportResponse(
        success=len(errors) == 0,
        message=f"Imported {scenes_imported} scenes with {frames_imported} frames",
        scenes_imported=scenes_imported,
        frames_imported=frames_imported,
        errors=errors,
        renamed_scenes=renamed_scenes,
    )


@router.post("/validate", response_model=Dict[str, Any])
async def validate_dataset_structure(
    root_path: str,
) -> Dict[str, Any]:
    """
    Validate a dataset folder structure without importing.
    Returns information about what would be imported.
    """
    path = Path(root_path)
    
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path does not exist: {root_path}"
        )
    
    result = {
        "valid": True,
        "metadata_found": False,
        "calibration_found": False,
        "scenes": [],
        "total_frames": 0,
        "sensors_detected": [],
        "warnings": [],
        "errors": []
    }
    
    metadata_file = path / "metadata.json"
    if metadata_file.exists():
        result["metadata_found"] = True
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
            sensors = metadata.get("sensors", {})
            if "lidar" in sensors:
                result["sensors_detected"].append(f"LiDAR: {sensors['lidar'].get('sensor_id', 'unknown')}")
            for cam in sensors.get("cameras", []):
                result["sensors_detected"].append(f"Camera: {cam.get('sensor_id', 'unknown')}")
    else:
        result["warnings"].append("No metadata.json found - sensor config will be inferred")
    
    calibration_path = path / "calibration"
    if calibration_path.exists():
        result["calibration_found"] = True
        extrinsics = calibration_path / "extrinsics.json"
        if not extrinsics.exists():
            result["warnings"].append("No extrinsics.json found in calibration folder")
    else:
        result["warnings"].append("No calibration folder found - 3D-to-2D projection may not work")
    
    scenes_path = path / "scenes"
    if not scenes_path.exists():
        result["valid"] = False
        result["errors"].append("No 'scenes' folder found")
        return result
    
    for scene_dir in sorted(scenes_path.iterdir()):
        if not scene_dir.is_dir():
            continue
        
        scene_info = {
            "name": scene_dir.name,
            "has_metadata": (scene_dir / "scene_metadata.json").exists(),
            "has_lidar": (scene_dir / "lidar").exists(),
            "has_cameras": (scene_dir / "cameras").exists(),
            "has_ego_poses": ((scene_dir / "ego_poses" / "poses.json").exists() or (scene_dir / "ego_poses" / "ego_poses.json").exists()),
            "has_timestamps": (scene_dir / "timestamps.json").exists(),
            "frame_count": 0,
            "cameras": []
        }
        
        lidar_path = scene_dir / "lidar"
        if lidar_path.exists():
            scene_info["frame_count"] = len(list(lidar_path.glob("*.pcd"))) + len(list(lidar_path.glob("*.bin")))
        
        cameras_path = scene_dir / "cameras"
        if cameras_path.exists():
            scene_info["cameras"] = [d.name for d in cameras_path.iterdir() if d.is_dir()]
        
        result["scenes"].append(scene_info)
        result["total_frames"] += scene_info["frame_count"]
    
    if len(result["scenes"]) == 0:
        result["valid"] = False
        result["errors"].append("No scene folders found in 'scenes' directory")
    
    return result
