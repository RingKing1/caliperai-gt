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
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.file_security import (
    DATA_EXTENSIONS,
    safe_zip_extract,
    validate_magic_bytes,
    validate_upload_path,
)
from app.models.models import (
    Dataset,
    Frame,
    ImportJob,
    Permission,
    Scene,
    User,
)
from app.services.dataset_import import (
    UPLOAD_DIR,
    UPLOAD_PIPELINE,
    ZIP_PIPELINE,
    BrowseFolderResponse,
    FolderItem,
    ImportRequest,
    ImportResponse,
    RenamedScene,
    SceneConflict,
    SceneNameCheckRequest,
    SceneNameCheckResponse,
    create_import_job,
    discover_frames,
    execute_directory_import,
    execute_video_import,
    generate_smart_scene_name,
    get_storage_paths,
    list_import_jobs,
    load_ego_poses,
    parse_calibration_file,
    schedule_import_job,
)
from app.services.dataset_import.schemas import ImportJobResponse
from app.services.dataset_service import auto_create_tasks_for_scene
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

        items: list[FolderItem] = []

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
    conflicts: list[SceneConflict] = []
    for i, folder_name in enumerate(request.folder_names):
        scene_name = folder_name if request.preserve_folder_names else generate_smart_scene_name(folder_name, i + 1)
        result = await db.execute(
            select(Scene).where(
                Scene.dataset_id == request.dataset_id,
                Scene.name == scene_name,
                Scene.is_deleted.is_(False),
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
    files: list[UploadFile] = File(...),
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

        return await execute_directory_import(
            db,
            root_path=Path(temp_dir),
            dataset=dataset,
            user=current_user,
            spec=UPLOAD_PIPELINE,
            dataset_upload_dir=dataset_upload_dir,
            overwrite_annotations=overwrite_annotations,
            preserve_folder_names=preserve_folder_names,
            derive_taxonomy=derive_taxonomy,
        )

    except HTTPException:
        raise
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
        log.info("[ZIP IMPORT] Receiving uploaded ZIP file...")
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
                    log.info("[ZIP IMPORT] Received %.1f MB...", file_size / (1024*1024))

        log.info("[ZIP IMPORT] Uploaded file size: %.1f MB", file_size / (1024*1024))
        log.info("[ZIP IMPORT] Extracting ZIP file...")
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

        try:
            name_overrides_dict: dict[str, str] = json.loads(name_overrides)
        except Exception:
            name_overrides_dict = {}

        try:
            scene_descriptions_dict: dict[str, str] = json.loads(scene_descriptions)
        except Exception:
            scene_descriptions_dict = {}

        return await execute_directory_import(
            db,
            root_path=extract_dir,
            dataset=dataset,
            user=current_user,
            spec=ZIP_PIPELINE,
            dataset_upload_dir=dataset_upload_dir,
            overwrite_annotations=overwrite_annotations,
            preserve_folder_names=preserve_folder_names,
            derive_taxonomy=derive_taxonomy,
            name_overrides=name_overrides_dict,
            scene_descriptions=scene_descriptions_dict,
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


@router.post("/jobs/upload", response_model=ImportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_folder_import_job(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    files: list[UploadFile] = File(...),
    derive_taxonomy: bool = Form(False),
    overwrite_annotations: bool = Form(False),
    preserve_folder_names: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> ImportJob:
    """Stage a browser folder upload and import it in a background job.

    Returns 202 with a job id immediately; poll ``GET /import/jobs/{id}``.
    Files are validated while staged so path/magic-byte problems still
    surface as 400 before the job is created.
    """
    await _get_import_dataset(db, dataset_id)

    staged_dir = Path(tempfile.mkdtemp(prefix="import_job_upload_"))
    try:
        for upload_file in files:
            raw_path = upload_file.filename or "unknown"
            relative_path = validate_upload_path(raw_path)
            content = await upload_file.read()
            leaf_ext = Path(relative_path).suffix.lower()
            if leaf_ext in DATA_EXTENSIONS:
                validate_magic_bytes(content, Path(relative_path).name)
            file_path = staged_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(content)
    except HTTPException:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise

    job = await create_import_job(
        db,
        dataset_id=dataset_id,
        user_id=current_user.id,
        job_type="upload",
        source_filename=None,
        staged_path=str(staged_dir),
        options={
            "derive_taxonomy": derive_taxonomy,
            "overwrite_annotations": overwrite_annotations,
            "preserve_folder_names": preserve_folder_names,
        },
    )
    schedule_import_job(job.id)
    return job


@router.post("/jobs/zip", response_model=ImportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_zip_import_job(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    file: UploadFile = File(..., description="ZIP file containing the dataset folder"),
    derive_taxonomy: bool = Form(False),
    overwrite_annotations: bool = Form(False),
    preserve_folder_names: bool = Form(True),
    name_overrides: str = Form(default="{}"),
    scene_descriptions: str = Form(default="{}"),
    db: AsyncSession = Depends(get_db),
) -> ImportJob:
    """Stage a ZIP upload and extract/import it in a background job (202)."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a ZIP archive (.zip)",
        )
    validate_upload_path(file.filename)
    await _get_import_dataset(db, dataset_id)

    staged_dir = Path(tempfile.mkdtemp(prefix="import_job_zip_"))
    zip_path = staged_dir / "upload.zip"
    try:
        with open(zip_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024 * 10)
                if not chunk:
                    break
                f.write(chunk)
        if zip_path.read_bytes()[:4] != b"PK\x03\x04":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is not a valid ZIP archive (magic bytes mismatch).",
            )
    except HTTPException:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise

    try:
        name_overrides_dict = json.loads(name_overrides)
    except Exception:
        name_overrides_dict = {}
    try:
        scene_descriptions_dict = json.loads(scene_descriptions)
    except Exception:
        scene_descriptions_dict = {}

    job = await create_import_job(
        db,
        dataset_id=dataset_id,
        user_id=current_user.id,
        job_type="zip",
        source_filename=file.filename,
        staged_path=str(staged_dir),
        options={
            "derive_taxonomy": derive_taxonomy,
            "overwrite_annotations": overwrite_annotations,
            "preserve_folder_names": preserve_folder_names,
            "name_overrides": name_overrides_dict,
            "scene_descriptions": scene_descriptions_dict,
        },
    )
    schedule_import_job(job.id)
    return job


@router.post("/jobs/video", response_model=ImportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_video_import_job(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    file: UploadFile = File(..., description="Video file (MP4, AVI, MOV, MKV, WebM)"),
    extraction_fps: float | None = Form(None, description="FPS to extract frames at (default: auto-detect)"),
    max_frames: int | None = Form(None, description="Maximum number of frames to extract"),
    image_format: str = Form("jpg", description="Output image format (jpg, png, webp)"),
    preserve_folder_names: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> ImportJob:
    """Stage a video upload and process frame extraction in a background job (202).

    Avoids holding open the HTTP connection while ffmpeg extracts frames.
    Poll ``GET /import/jobs/{id}`` for progress and results.
    """
    from app.core.file_security import VIDEO_EXTENSIONS as ALLOWED_VIDEO_EXT
    from app.services.video_service import is_ffmpeg_available

    if not is_ffmpeg_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video processing is not available. Please install ffmpeg on the server.",
        )
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid video format. Supported formats: {', '.join(ALLOWED_VIDEO_EXT)}",
        )
    validate_upload_path(file.filename)
    await _get_import_dataset(db, dataset_id)

    staged_dir = Path(tempfile.mkdtemp(prefix="import_job_video_"))
    video_path = staged_dir / f"video{file_ext}"
    try:
        with open(video_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024 * 10)
                if not chunk:
                    break
                f.write(chunk)
    except Exception:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise

    job = await create_import_job(
        db,
        dataset_id=dataset_id,
        user_id=current_user.id,
        job_type="video",
        source_filename=file.filename,
        staged_path=str(staged_dir),
        options={
            "extraction_fps": extraction_fps,
            "max_frames": max_frames,
            "image_format": image_format,
            "preserve_folder_names": preserve_folder_names,
        },
    )
    schedule_import_job(job.id)
    return job


@router.get("/jobs", response_model=list[ImportJobResponse])
async def list_dataset_import_jobs(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    dataset_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[ImportJob]:
    """Recent background import jobs for a dataset (newest first)."""
    return await list_import_jobs(db, dataset_id=dataset_id)


@router.get("/jobs/{job_id}", response_model=ImportJobResponse)
async def get_import_job_status(
    job_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    db: AsyncSession = Depends(get_db),
) -> ImportJob:
    """Poll a background import job's phase/progress/result."""
    job = await db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import job {job_id} not found",
        )
    return job


async def _get_import_dataset(db: AsyncSession, dataset_id: str) -> Dataset:
    query = select(Dataset).options(selectinload(Dataset.campaign)).where(
        Dataset.id == UUID(dataset_id)
    )
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {dataset_id}",
        )
    return dataset


@router.post("/upload-video", response_model=ImportResponse)
async def upload_video_and_import_dataset(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    dataset_id: str = Form(...),
    file: UploadFile = File(..., description="Video file (MP4, AVI, MOV, MKV, WebM)"),
    extraction_fps: float | None = Form(None, description="FPS to extract frames at (default: auto-detect)"),
    max_frames: int | None = Form(None, description="Maximum number of frames to extract"),
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
        is_ffmpeg_available,
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
    dataset = await _get_import_dataset(db, dataset_id)

    temp_dir = tempfile.mkdtemp(prefix="video_upload_")
    video_path = Path(temp_dir) / f"video{file_ext}"

    try:
        log.info(f"[VIDEO IMPORT] Receiving video file: {file.filename}")
        chunk_size = 1024 * 1024 * 10
        with open(video_path, "wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)

        return await execute_video_import(
            db,
            dataset=dataset,
            user=current_user,
            video_path=video_path,
            original_filename=file.filename,
            extraction_fps=extraction_fps,
            max_frames=max_frames,
            image_format=image_format,
            preserve_folder_names=preserve_folder_names,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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
        Dataset.is_deleted.is_(False),
    )
    result = await db.execute(dataset_query)
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {request.dataset_id} not found"
        )

    errors = []
    renamed_scenes: list[RenamedScene] = []
    scenes_imported = 0
    frames_imported = 0

    metadata_file = root_path / "metadata.json"
    sensor_config = {}
    if metadata_file.exists():
        with open(metadata_file) as f:
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
                with open(scene_metadata_file) as f:
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
                Scene.is_deleted.is_(False),
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


@router.post("/validate", response_model=dict[str, Any])
async def validate_dataset_structure(
    root_path: str,
) -> dict[str, Any]:
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
        with open(metadata_file) as f:
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
