"""Archive filesystem path resolution and raw sensor data packaging."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.models import Scene, Task

DATA_BASE_PATH = Path("/data")


def resolve_storage_path(path_str: str | None, storage_paths: dict) -> Path | None:
    """Resolve a stored path to an absolute filesystem path.

    Handles both absolute paths (written directly to storage_paths) and
    relative paths that may be anchored under /uploads (browser uploads) or
    the legacy DATA_BASE_PATH (/data).
    """
    if not path_str:
        return None

    direct = Path(path_str)
    if direct.is_absolute() and direct.exists():
        return direct

    uploads_candidate = Path("/") / path_str.lstrip("/")
    if uploads_candidate.exists():
        return uploads_candidate

    root_path = storage_paths.get("root")
    if root_path and not path_str.startswith("uploads"):
        candidate = Path(root_path) / path_str
        if candidate.exists():
            return candidate

    data_candidate = DATA_BASE_PATH / path_str
    if data_candidate.exists():
        return data_candidate

    return None


def add_scene_data_to_zip(
    zf: zipfile.ZipFile,
    scene: Scene,
    frames_data: list[dict[str, Any]],
    prefix: str = "data",
) -> None:
    """Add actual data files (lidar, camera images) for a scene to the ZIP archive."""
    storage_paths = scene.storage_paths or {}

    lidar_base = storage_paths.get("lidar_base")
    lidar_path = resolve_storage_path(lidar_base, storage_paths)
    if lidar_path and lidar_path.exists():
        for lidar_file in lidar_path.iterdir():
            if lidar_file.is_file():
                arcname = f"{prefix}/lidar/{lidar_file.name}"
                zf.write(str(lidar_file), arcname)

    cameras = storage_paths.get("cameras", {})
    for camera_name, camera_path_str in cameras.items():
        camera_path = resolve_storage_path(camera_path_str, storage_paths)
        if camera_path and camera_path.exists():
            for img_file in camera_path.iterdir():
                if img_file.is_file():
                    arcname = f"{prefix}/cameras/{camera_name}/{img_file.name}"
                    zf.write(str(img_file), arcname)

    ego_poses_path = storage_paths.get("ego_poses")
    ego_file = resolve_storage_path(ego_poses_path, storage_paths)
    if ego_file and ego_file.exists():
        zf.write(str(ego_file), f"{prefix}/ego_poses/ego_poses.json")
    else:
        frame_poses = [
            {
                "frame_index": f["frame_index"],
                "timestamp": f.get("timestamp"),
                "position": f["ego_pose"]["position"],
                "rotation": f["ego_pose"]["rotation"],
                **({"velocity": f["ego_pose"]["velocity"]} if f["ego_pose"].get("velocity") else {}),
            }
            for f in frames_data
            if f.get("ego_pose") and isinstance(f["ego_pose"], dict) and f["ego_pose"].get("position")
        ]
        if frame_poses:
            poses_json = json.dumps({"frames": frame_poses}, indent=2)
            zf.writestr(f"{prefix}/ego_poses/ego_poses.json", poses_json)

    if scene.calibration:
        zf.writestr(f"{prefix}/calibration.json", json.dumps(scene.calibration, indent=2))


def build_task_export_folder_name(task: Task) -> str:
    """Create a readable, stable folder name for per-task scene exports."""
    base_name = task.name or f"task_{str(task.id)[:8]}"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", base_name).strip("_")
    if not safe_name:
        safe_name = "task"
    return f"{safe_name}__{str(task.id)[:8]}"
