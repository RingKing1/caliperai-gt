"""Build Frame ORM rows for imported data files (upload + ZIP pipelines)."""
from pathlib import Path
from typing import Any

from app.models.models import Frame


def build_import_frame_rows(
    *,
    scene,
    permanent_scene_dir: Path,
    permanent_data_files: list[Path],
    lidar_files: list[Path],
    camera_files: dict[str, list[Path]],
    uuid_rename_map: dict[str, dict[str, str]],
    ego_poses_data: dict[int, dict[str, Any]],
) -> list[Frame]:
    """Assemble the per-frame rows using the upload/ZIP route conventions.

    * ``lidar`` / ``cameras`` entries point at co-indexed files by basename;
    * ``_meta`` keeps absolute/relative paths and the pre-rename filename;
    * timestamps come from ego poses when available, else frame_index / fps.
    """
    frames: list[Frame] = []

    for frame_idx, data_file in enumerate(permanent_data_files):
        frame_file_paths: dict[str, Any] = {}

        if lidar_files and frame_idx < len(lidar_files):
            frame_file_paths["lidar"] = lidar_files[frame_idx].name

        if camera_files:
            cameras_dict: dict[str, str] = {}
            for cam_name, cam_file_list in camera_files.items():
                if frame_idx < len(cam_file_list):
                    cameras_dict[cam_name] = cam_file_list[frame_idx].name
            if cameras_dict:
                frame_file_paths["cameras"] = cameras_dict

        rel_key = str(data_file.relative_to(permanent_scene_dir))
        original_name = (
            uuid_rename_map.get(rel_key, {}).get("original_name")
            or data_file.name
        )
        frame_file_paths["_meta"] = {
            "absolute_path": str(data_file),
            "relative_path": rel_key,
            "original_filename": original_name,
        }

        frame_ego_pose: dict[str, Any] | None = ego_poses_data.get(frame_idx)
        if (frame_ego_pose and isinstance(frame_ego_pose, dict)
                and "timestamp" in frame_ego_pose):
            frame_timestamp = frame_ego_pose.get("timestamp")
        else:
            frame_timestamp = frame_idx * (1.0 / scene.fps)

        frames.append(Frame(
            scene_id=scene.id,
            frame_index=frame_idx,
            timestamp=frame_timestamp,
            file_paths=frame_file_paths,
            ego_pose=frame_ego_pose if isinstance(frame_ego_pose, dict) else None,
        ))

    return frames
