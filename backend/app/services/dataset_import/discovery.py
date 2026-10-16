"""On-disk frame discovery and storage-path derivation."""
import json
from pathlib import Path
from typing import Any

from app.services.dataset_import.calibration import load_ego_poses


def discover_frames(scene_path: Path, sensor_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover frames in a scene folder."""
    frames = []

    lidar_path = scene_path / "lidar"
    if lidar_path.exists():
        lidar_files = sorted(lidar_path.glob("*.pcd")) + sorted(lidar_path.glob("*.bin"))

        timestamps_file = scene_path / "timestamps.json"
        timestamps = {}
        if timestamps_file.exists():
            with open(timestamps_file, 'r') as f:
                ts_data = json.load(f)
                for frame_ts in ts_data.get("frames", []):
                    timestamps[frame_ts["frame_index"]] = frame_ts["timestamp"]

        ego_poses = load_ego_poses(scene_path)

        for idx, lidar_file in enumerate(lidar_files):
            file_paths = {
                "lidar": lidar_file.name,
                "cameras": {}
            }

            cameras_path = scene_path / "cameras"
            if cameras_path.exists():
                for camera_dir in cameras_path.iterdir():
                    if camera_dir.is_dir():
                        camera_id = camera_dir.name
                        for ext in [".jpg", ".png", ".webp"]:
                            camera_file = camera_dir / f"{lidar_file.stem}{ext}"
                            if camera_file.exists():
                                file_paths["cameras"][camera_id] = camera_file.name
                                break

            frame = {
                "frame_index": idx,
                "timestamp": timestamps.get(idx, idx * 0.1),
                "ego_pose": ego_poses.get(idx),
                "file_paths": file_paths
            }
            frames.append(frame)

    return frames


def get_storage_paths(scene_path: Path, root_path: Path) -> dict[str, Any]:
    """Build storage paths for a scene."""
    relative_scene = scene_path.relative_to(root_path)

    storage_paths = {
        "lidar_base": str(relative_scene / "lidar"),
        "cameras": {},
        "ego_poses": None
    }

    cameras_path = scene_path / "cameras"
    if cameras_path.exists():
        for camera_dir in cameras_path.iterdir():
            if camera_dir.is_dir():
                storage_paths["cameras"][camera_dir.name] = str(relative_scene / "cameras" / camera_dir.name)

    ego_poses_file = scene_path / "ego_poses" / "poses.json"
    if not ego_poses_file.exists():
        ego_poses_file = scene_path / "ego_poses" / "ego_poses.json"

    if ego_poses_file.exists():
        storage_paths["ego_poses"] = str(relative_scene / "ego_poses" / ego_poses_file.name)

    return storage_paths



