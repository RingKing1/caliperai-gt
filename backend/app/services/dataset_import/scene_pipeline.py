"""Per-scene orchestration shared by the ``/upload`` and ``/upload-zip`` routes.

The two HTTP entry points differ only in how they receive bytes (multipart
file list vs. ZIP archive); every per-scene step afterwards -- permanent
storage, ego poses, calibration, scene/frame rows, annotation import -- is
the same pipeline. Historical behavioural divergences are kept intact on
purpose (zero behaviour change) and made explicit on :class:`PipelineSpec`:

* ego pose synthesis from the parent ``metadata.json`` (upload only);
* dataset-level calibration inheritance (ZIP only);
* duplicate-name check skipped for user-renamed scenes (ZIP only);
* flat fallback layout: single synthetic camera (upload) vs.
  ``images`` / ``default`` / lidar bucketing (ZIP).
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.api.v1.endpoints.datasets import auto_create_tasks_for_scene
from app.core.file_security import DATA_EXTENSIONS, rename_data_files_to_uuid
from app.models.models import Dataset, Scene, User
from app.services.dataset_import.calibration import (
    detect_ego_to_lidar_rotation,
    parse_calibration_file,
)
from app.services.dataset_import.constants import GENERIC_FOLDER_NAMES
from app.services.dataset_import.frame_rows import build_import_frame_rows
from app.services.dataset_import.naming import generate_smart_scene_name
from app.services.dataset_import.pipeline_layout import (
    classify_scene_data_files,
    find_data_files,
)
from app.services.dataset_import.scene_importer import import_scene_annotations
from app.services.dataset_import.schemas import RenamedScene
from app.services.dataset_import.storage import schedule_scene_mirror
from app.services.dataset_import.tasks import get_or_create_scene_import_task

IMAGE_SUFFIXES = (".jpg", ".png", ".jpeg")
IMAGES_FOLDER_SUFFIXES = (
    ".jpg", ".png", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
)
FLAT_IMAGE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif",
)
LIDAR_SUFFIXES = (".pcd", ".bin", ".ply")


@dataclass(frozen=True)
class PipelineSpec:
    """Behaviour switches for a specific upload route."""

    name: str
    log_prefix: str
    synthesize_ego_from_parent_metadata: bool
    inherit_dataset_level_calibration: bool
    duplicate_name_check: str  # "always" | "unless_overridden"
    fallback_layout: str  # "single_camera" | "bucketed"


UPLOAD_PIPELINE = PipelineSpec(
    name="upload",
    log_prefix="[IMPORT]",
    synthesize_ego_from_parent_metadata=True,
    inherit_dataset_level_calibration=False,
    duplicate_name_check="always",
    fallback_layout="single_camera",
)

ZIP_PIPELINE = PipelineSpec(
    name="zip",
    log_prefix="[ZIP IMPORT]",
    synthesize_ego_from_parent_metadata=False,
    inherit_dataset_level_calibration=True,
    duplicate_name_check="unless_overridden",
    fallback_layout="bucketed",
)


@dataclass
class SceneImportRequest:
    """All request-scoped inputs for one per-scene import run."""

    dataset: Dataset
    user: User
    dataset_upload_dir: Path
    overwrite_annotations: bool = False
    preserve_folder_names: bool = True
    name_overrides: dict[str, str] = field(default_factory=dict)
    scene_descriptions: dict[str, str] = field(default_factory=dict)
    dataset_calibration: dict[str, Any] = field(default_factory=dict)


def resolve_scene_name(
    spec: PipelineSpec,
    request: SceneImportRequest,
    scene_index: int,
    raw_folder_name: str,
) -> tuple[str, str | None, str | None]:
    """Return ``(scene_name, user_override, user_description)``.

    User-provided overrides exist only on the ZIP route.
    """
    if (
        request.preserve_folder_names
        and raw_folder_name.lower() not in GENERIC_FOLDER_NAMES
    ):
        scene_name = raw_folder_name
    else:
        scene_name = generate_smart_scene_name(raw_folder_name, scene_index)

    user_override = None
    user_description = None
    if spec.name == "zip":
        original_scene_name = scene_name
        user_override = request.name_overrides.get(scene_name)
        if user_override:
            scene_name = user_override
        user_description = (
            request.scene_descriptions.get(original_scene_name) or None
        )
    return scene_name, user_override, user_description


def materialize_scene_files(
    source_scene_dir: Path,
    permanent_scene_dir: Path,
    scene_name: str,
    errors: list[str],
) -> dict[str, dict[str, str]]:
    """Copy the extracted scene into permanent storage and UUID-rename files.

    Also copies a sibling ``annotations/`` folder next to the scene (common
    for ``data/`` + ``annotations/`` layouts). Returns the rename map.
    """
    permanent_scene_dir.mkdir(parents=True, exist_ok=True)
    for item in source_scene_dir.iterdir():
        dst = permanent_scene_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)

    rename_map = rename_data_files_to_uuid(permanent_scene_dir, DATA_EXTENSIONS)

    parent_dir = source_scene_dir.parent
    if parent_dir != source_scene_dir:
        sibling_annotations = parent_dir / "annotations"
        if sibling_annotations.exists() and sibling_annotations.is_dir():
            annotations_dst = permanent_scene_dir / "annotations"
            if not annotations_dst.exists():
                try:
                    shutil.copytree(sibling_annotations, annotations_dst)
                except Exception as exc:
                    errors.append(
                        f"Scene {scene_name}: Failed to copy annotations "
                        f"folder: {exc}"
                    )
    return rename_map


def read_scene_ego_poses(
    spec: PipelineSpec,
    permanent_scene_dir: Path,
    source_scene_dir: Path,
    relative_path_base: str,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    """Load per-frame ego poses for a scene.

    Both routes read ``ego_poses/poses.json`` then ``ego_poses/ego_poses.json``
    in the ``{"frames": [...]}`` shape; the ZIP route additionally accepts a
    bare JSON list. The upload route synthesizes poses from a parent
    ``metadata.json`` when no scene-level poses file exists.
    """
    ego_poses_data: dict[int, dict[str, Any]] = {}
    ego_poses_file = permanent_scene_dir / "ego_poses" / "poses.json"
    if not ego_poses_file.exists():
        ego_poses_file = permanent_scene_dir / "ego_poses" / "ego_poses.json"

    ego_poses_rel_path: str | None = None
    if ego_poses_file.exists():
        ego_poses_rel_path = (
            f"{relative_path_base}/ego_poses/{ego_poses_file.name}"
        )
        with open(ego_poses_file) as f:
            poses_raw = json.load(f)
        if isinstance(poses_raw, dict) and "frames" in poses_raw:
            for pose_entry in poses_raw["frames"]:
                frame_idx = pose_entry.get("frame_index", -1)
                if frame_idx >= 0:
                    ego_poses_data[frame_idx] = {
                        "position": pose_entry.get("position", [0, 0, 0]),
                        "rotation": pose_entry.get("rotation", [1, 0, 0, 0]),
                        "velocity": pose_entry.get("velocity"),
                        "timestamp": pose_entry.get("timestamp"),
                    }
        elif spec.name == "zip" and isinstance(poses_raw, list):
            for idx, pose in enumerate(poses_raw):
                ego_poses_data[idx] = pose
    elif spec.synthesize_ego_from_parent_metadata:
        parent_metadata_file = source_scene_dir.parent / "metadata.json"
        if parent_metadata_file.exists():
            try:
                with open(parent_metadata_file) as f:
                    parent_meta = json.load(f)
                for frame_entry in parent_meta.get("frames", []):
                    pose = frame_entry.get("ego_pose")
                    if pose and isinstance(pose, dict) and pose.get("position"):
                        frame_idx = frame_entry.get("frame_index", -1)
                        if frame_idx >= 0:
                            ego_poses_data[frame_idx] = {
                                "position": pose.get("position", [0, 0, 0]),
                                "rotation": pose.get("rotation", [1, 0, 0, 0]),
                                "velocity": pose.get("velocity"),
                                "timestamp": pose.get("timestamp"),
                            }
                if ego_poses_data:
                    ego_poses_dir = permanent_scene_dir / "ego_poses"
                    ego_poses_dir.mkdir(exist_ok=True)
                    synth_poses_file = ego_poses_dir / "ego_poses.json"
                    poses_out = {
                        "frames": [
                            {"frame_index": idx, **data}
                            for idx, data in sorted(ego_poses_data.items())
                        ]
                    }
                    with open(synth_poses_file, "w") as f:
                        json.dump(poses_out, f, indent=2)
                    ego_poses_rel_path = (
                        f"{relative_path_base}/ego_poses/ego_poses.json"
                    )
            except Exception as exc:
                print(
                    f"[IMPORT] Failed to read ego_poses from metadata.json: "
                    f"{exc}"
                )

    return ego_poses_data, ego_poses_rel_path


def resolve_scene_calibration(
    spec: PipelineSpec,
    request: SceneImportRequest,
    permanent_scene_dir: Path,
    ego_poses_data: dict[int, dict[str, Any]],
) -> Any:
    """Scene-level calibration, falling back per the route convention.

    Upload resets to an empty ``lidar_to_cameras`` map when deriving
    ``ego_to_lidar`` from poses; the ZIP route inherits the dataset-level
    calibration parsed before the scene loop.
    """
    base = request.dataset_calibration if spec.inherit_dataset_level_calibration else None
    calib_file = permanent_scene_dir / "calibration.json"
    calib_dir = permanent_scene_dir / "calibration"
    if calib_file.exists():
        return parse_calibration_file(calib_file, ego_poses_data)
    if calib_dir.exists():
        return parse_calibration_file(calib_dir, ego_poses_data)
    if ego_poses_data:
        rotation = detect_ego_to_lidar_rotation(ego_poses_data)
        inherited = {}
        if spec.inherit_dataset_level_calibration and isinstance(base, dict):
            inherited = base.get("lidar_to_cameras", {})
        return {
            "lidar_to_cameras": inherited,
            "ego_to_lidar": {"rotation": rotation, "translation": [0, 0, 0]},
        }
    return base


async def ensure_unique_scene_name(
    db: AsyncSession,
    request: SceneImportRequest,
    scene_name: str,
    scene_id: uuid.UUID,
    renamed_scenes: list[RenamedScene],
    *,
    skip_check: bool,
) -> str:
    """Suffix ``_upload-YYYYMMDD_HHMM`` on duplicate names within a dataset."""
    if skip_check:
        return scene_name
    existing_result = await db.execute(
        select(Scene).where(
            Scene.dataset_id == request.dataset.id,
            Scene.name == scene_name,
            Scene.is_deleted == False,  # noqa: E712 - SQLAlchemy predicate
        )
    )
    if existing_result.scalar_one_or_none():
        original_name = scene_name
        scene_name = (
            f"{scene_name}_upload-{datetime.now().strftime('%Y%m%d_%H%M')}"
        )
        renamed_scenes.append(
            RenamedScene(
                original_name=original_name,
                new_name=scene_name,
                scene_id=str(scene_id),
            )
        )
    return scene_name


def build_scene_orm(
    spec: PipelineSpec,
    request: SceneImportRequest,
    scene_id: uuid.UUID,
    scene_name: str,
    user_description: str | None,
    scene_meta: dict[str, Any],
    frame_count: int,
    data_source: str,
    calibration: Any,
    storage_paths: dict[str, Any],
) -> Scene:
    """Construct the Scene row using the route's metadata conventions."""
    common = {
        "id": scene_id,
        "dataset_id": request.dataset.id,
        "name": scene_name,
        "frame_count": frame_count,
        "fps": scene_meta.get("fps", 10.0),
        "storage_paths": storage_paths,
    }
    if spec.name == "upload":
        return Scene(
            description=scene_meta.get(
                "description", f"Imported scene: {scene_name}"
            ),
            scene_metadata={
                "location": scene_meta.get("location"),
                "weather": scene_meta.get("weather"),
                "time_of_day": scene_meta.get("time_of_day"),
                "source": "browser_upload",
                "data_source": data_source,
            },
            calibration=calibration,
            **common,
        )
    return Scene(
        description=user_description or scene_meta.get("description"),
        scene_metadata={
            "location": scene_meta.get("location"),
            "weather": scene_meta.get("weather"),
            "time_of_day": scene_meta.get("time_of_day"),
            "recording_date": scene_meta.get("recording_date"),
        },
        calibration=calibration if calibration else {},
        **common,
    )


def collect_scene_files(
    spec: PipelineSpec,
    scene: Scene,
    permanent_scene_dir: Path,
    source_scene_dir: Path,
    scene_name: str,
    relative_path_base: str,
) -> tuple[list[Path], list[Path], dict[str, list[Path]]]:
    """Discover permanent lidar/camera files and keep storage_paths in sync.

    Canonical layouts (``lidar/`` + ``cameras/<cam>/``) are handled the same
    way on both routes; the fallback layouts follow the historical per-route
    bucketing via ``PipelineSpec.fallback_layout``.
    """
    permanent_lidar_path = permanent_scene_dir / "lidar"
    permanent_images_path = permanent_scene_dir / "images"
    permanent_cameras_path = permanent_scene_dir / "cameras"

    permanent_data_files: list[Path] = []
    lidar_files: list[Path] = []
    camera_files: dict[str, list[Path]] = {}

    if permanent_lidar_path.exists():
        if spec.name == "upload":
            lidar_files = sorted(
                [f for f in permanent_lidar_path.iterdir() if f.is_file()],
                key=lambda x: x.name,
            )
        else:
            lidar_files = sorted(
                [
                    f
                    for f in permanent_lidar_path.iterdir()
                    if f.suffix.lower() in LIDAR_SUFFIXES
                ],
                key=lambda x: x.name,
            )
        permanent_data_files = lidar_files

    if permanent_cameras_path.exists():
        for cam_dir in permanent_cameras_path.iterdir():
            if not cam_dir.is_dir():
                continue
            if spec.name == "upload":
                cam_files = sorted(
                    [f for f in cam_dir.iterdir() if f.is_file()],
                    key=lambda x: x.name,
                )
                if cam_files:
                    camera_files[cam_dir.name] = cam_files
            else:
                cam_images = sorted(
                    [
                        f
                        for f in cam_dir.iterdir()
                        if f.suffix.lower() in IMAGE_SUFFIXES
                    ],
                    key=lambda x: x.name,
                )
                camera_files[cam_dir.name] = cam_images
                if not permanent_data_files:
                    permanent_data_files = cam_images
        if spec.name == "upload" and not permanent_data_files and camera_files:
            permanent_data_files = next(iter(camera_files.values()))
    elif spec.fallback_layout == "bucketed" and permanent_images_path.exists():
        images = sorted(
            [
                f
                for f in permanent_images_path.iterdir()
                if f.suffix.lower() in IMAGES_FOLDER_SUFFIXES
            ],
            key=lambda x: x.name,
        )
        camera_files["images"] = images
        if not permanent_data_files:
            permanent_data_files = images

    if not permanent_data_files:
        if spec.fallback_layout == "single_camera":
            if permanent_images_path.exists():
                permanent_data_files = sorted(
                    [
                        f
                        for f in permanent_images_path.iterdir()
                        if f.is_file()
                    ],
                    key=lambda x: x.name,
                )
            else:
                permanent_data_files = sorted(
                    find_data_files(permanent_scene_dir), key=lambda x: x.name
                )
        else:
            all_root_files = sorted(
                find_data_files(permanent_scene_dir), key=lambda x: x.name
            )
            pcd_root_files = [
                f for f in all_root_files
                if f.suffix.lower() in LIDAR_SUFFIXES
            ]
            img_root_files = [
                f for f in all_root_files
                if f.suffix.lower() in FLAT_IMAGE_SUFFIXES
            ]
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

    if (
        spec.fallback_layout == "single_camera"
        and permanent_data_files
        and not camera_files
        and not lidar_files
    ):
        camera_name = (
            source_scene_dir.name
            if source_scene_dir.name != "default_scene"
            else scene_name
        )
        camera_files = {camera_name: permanent_data_files}
        # Files may live under an images/ subfolder; the camera base must
        # point at the directory actually containing the frame files so the
        # frontend can resolve {storage_paths.cameras[key]}/{filename}.
        via_images_dir = permanent_images_path.exists() and all(
            f.parent == permanent_images_path for f in permanent_data_files
        )
        camera_base = (
            f"{relative_path_base}/images"
            if via_images_dir
            else relative_path_base
        )
        scene.storage_paths = {
            **scene.storage_paths,
            "cameras": {camera_name: camera_base},
        }
        attributes.flag_modified(scene, "storage_paths")
        print(
            f"[IMPORT] Treating flat image structure as single camera: "
            f"{camera_name}, path: {relative_path_base}"
        )

    return permanent_data_files, lidar_files, camera_files


async def import_one_scene(
    *,
    db: AsyncSession,
    spec: PipelineSpec,
    request: SceneImportRequest,
    scene_index: int,
    scene_dir: Path,
    parent_folder_name: str,
    errors: list[str],
    renamed_scenes: list[RenamedScene],
) -> int | None:
    """Run the full import for one scene directory.

    Returns the imported frame count, or ``None`` when the scene was skipped
    or failed (an explanatory string is appended to ``errors``).
    """
    prefix = spec.log_prefix
    try:
        scene_name, user_override, user_description = resolve_scene_name(
            spec, request, scene_index, parent_folder_name
        )

        scene_meta: dict[str, Any] = {}
        scene_meta_path = scene_dir / "scene_metadata.json"
        if scene_meta_path.exists():
            with open(scene_meta_path) as f:
                scene_meta = json.load(f)

        data_files, data_source = classify_scene_data_files(scene_dir)
        frame_count = len(data_files)
        if frame_count == 0:
            errors.append(f"Scene {scene_name}: No frames detected")
            return None

        scene_id = uuid.uuid4()
        permanent_scene_dir = request.dataset_upload_dir / str(scene_id)
        rename_map = materialize_scene_files(
            scene_dir, permanent_scene_dir, scene_name, errors
        )

        schedule_scene_mirror(
            request.dataset.campaign.organization_id,
            request.dataset.id,
            scene_id,
            permanent_scene_dir,
        )

        relative_path_base = f"uploads/{request.dataset.id}/{scene_id}"

        permanent_lidar_path = permanent_scene_dir / "lidar"
        permanent_images_path = permanent_scene_dir / "images"
        permanent_cameras_path = permanent_scene_dir / "cameras"

        cameras_storage_paths: dict[str, str] = {}
        if permanent_cameras_path.exists():
            for cam_dir in permanent_cameras_path.iterdir():
                if cam_dir.is_dir():
                    cameras_storage_paths[cam_dir.name] = (
                        f"{relative_path_base}/cameras/{cam_dir.name}"
                    )
        elif (
            spec.fallback_layout == "bucketed"
            and permanent_images_path.exists()
        ):
            cameras_storage_paths["images"] = (
                f"{relative_path_base}/images"
            )

        ego_poses_data, ego_poses_rel_path = read_scene_ego_poses(
            spec, permanent_scene_dir, scene_dir, relative_path_base
        )

        calibration = resolve_scene_calibration(
            spec, request, permanent_scene_dir, ego_poses_data
        )

        scene_name = await ensure_unique_scene_name(
            db,
            request,
            scene_name,
            scene_id,
            renamed_scenes,
            skip_check=(
                spec.duplicate_name_check == "unless_overridden"
                and bool(user_override)
            ),
        )

        storage_paths = {
            "root": str(permanent_scene_dir),
            "lidar_base": (
                f"{relative_path_base}/lidar"
                if permanent_lidar_path.exists()
                else None
            ),
            "images_base": (
                f"{relative_path_base}/images"
                if permanent_images_path.exists()
                else None
            ),
            "cameras": (
                cameras_storage_paths
                if spec.name == "zip" or cameras_storage_paths
                else None
            ),
            "ego_poses": ego_poses_rel_path,
        }
        scene = build_scene_orm(
            spec,
            request,
            scene_id,
            scene_name,
            user_description,
            scene_meta,
            frame_count,
            data_source,
            calibration,
            storage_paths,
        )
        db.add(scene)
        await db.flush()
        await auto_create_tasks_for_scene(db, scene)
        await db.flush()

        (
            permanent_data_files,
            lidar_files,
            camera_files,
        ) = collect_scene_files(
            spec,
            scene,
            permanent_scene_dir,
            scene_dir,
            scene_name,
            relative_path_base,
        )

        for frame in build_import_frame_rows(
            scene=scene,
            permanent_scene_dir=permanent_scene_dir,
            permanent_data_files=permanent_data_files,
            lidar_files=lidar_files,
            camera_files=camera_files,
            uuid_rename_map=rename_map,
            ego_poses_data=ego_poses_data,
        ):
            db.add(frame)
        await db.flush()

        task = await get_or_create_scene_import_task(
            db,
            scene=scene,
            assignee_id=request.user.id,
            frame_count=frame_count,
            description=(
                f"Auto-created for {scene_name} ({frame_count} frames)"
            ),
        )
        print(f"{prefix} Using task {task.id} for imported annotations")

        try:
            annotations_3d, annotations_2d = await import_scene_annotations(
                db,
                scene=scene,
                scene_dir=permanent_scene_dir,
                task=task,
                overwrite=request.overwrite_annotations,
            )
            if annotations_3d > 0 or annotations_2d > 0:
                errors.append(
                    f"Scene {scene_name}: Imported {annotations_3d} 3D "
                    f"and {annotations_2d} 2D annotations"
                )
        except Exception as exc:
            errors.append(
                f"Scene {scene_name}: Failed to import annotations: {exc}"
            )

        print(
            f"{prefix} Successfully imported scene {scene_name} with "
            f"{frame_count} frames"
        )
        return frame_count
    except Exception as exc:
        import traceback

        print(f"{prefix} ERROR Scene {scene_dir.name}: {exc}")
        print(f"{prefix} ERROR Traceback: {traceback.format_exc()}")
        errors.append(f"Scene {scene_dir.name}: {exc}")
        return None
