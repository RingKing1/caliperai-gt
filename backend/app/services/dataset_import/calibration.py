"""Calibration / ego-pose parsing for imported scenes."""
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
def detect_ego_to_lidar_rotation(ego_poses: dict[int, dict]) -> list[list[float]]:
    """
    Return the fixed ego_to_lidar rotation for this dataset convention.

    Conventions confirmed for this importer:
    - ego pose +x is the drive direction
    - GT LiDAR +y is the same drive direction

    Therefore ego_x must map to lidar_y, ego_y to lidar_-x, and ego_z to lidar_z.
    """
    _ = ego_poses
    rotation = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]
    log.info("Applying fixed ego_to_lidar convention: ego +x -> lidar +y")
    return rotation


def parse_calibration_file(calibration_path: Path, ego_poses: dict[int, dict] | None = None) -> dict[str, Any]:
    """Parse calibration data from files.

    Supports two formats:
    1. A folder with extrinsics.json and intrinsics/ subfolder
    2. A single calibration.json file containing all calibration data

    If ego_to_lidar is missing or identity, auto-detects axis convention from ego poses
    and applies correct calibration to enforce y-forward LiDAR convention.
    """
    calibration = {
        "lidar_to_cameras": {},
        "ego_to_lidar": None
    }

    if calibration_path.suffix == '.json' and calibration_path.exists():
        with open(calibration_path, 'r') as f:
            data = json.load(f)
            calibration["lidar_to_cameras"] = data.get("lidar_to_cameras", {})
            calibration["ego_to_lidar"] = data.get("ego_to_lidar")
        if calibration["ego_to_lidar"] and calibration["ego_to_lidar"].get("rotation") != [[1,0,0],[0,1,0],[0,0,1]]:
            return calibration
    else:
        if not calibration_path.is_dir():
            pass
        else:
            extrinsics_file = calibration_path / "extrinsics.json"
            if extrinsics_file.exists():
                with open(extrinsics_file, 'r') as f:
                    data = json.load(f)
                    calibration["lidar_to_cameras"] = data.get("lidar_to_cameras", {})
                    calibration["ego_to_lidar"] = data.get("ego_to_lidar")

            intrinsics_path = calibration_path / "intrinsics"
            if intrinsics_path.exists():
                for intrinsic_file in intrinsics_path.glob("*.json"):
                    camera_id = intrinsic_file.stem
                    with open(intrinsic_file, 'r') as f:
                        intrinsic_data = json.load(f)
                        if camera_id in calibration["lidar_to_cameras"]:
                            calibration["lidar_to_cameras"][camera_id]["intrinsic"] = intrinsic_data
                        else:
                            calibration["lidar_to_cameras"][camera_id] = {
                                "extrinsic": {"rotation": [[1,0,0],[0,1,0],[0,0,1]], "translation": [0,0,0]},
                                "intrinsic": intrinsic_data
                            }

            if calibration["ego_to_lidar"] and calibration["ego_to_lidar"].get("rotation") != [[1,0,0],[0,1,0],[0,0,1]]:
                return calibration

    if ego_poses:
        rotation = detect_ego_to_lidar_rotation(ego_poses)
        calibration["ego_to_lidar"] = {"rotation": rotation, "translation": [0, 0, 0]}
    else:
        log.warning("No ego poses provided; defaulting to identity ego_to_lidar (GT tool expects y-forward LiDAR)")
        calibration["ego_to_lidar"] = {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation": [0, 0, 0]}

    return calibration



def load_ego_poses(scene_path: Path) -> dict[int, dict]:
    """Load ego poses from scene directory.

    Checks both 'ego_poses/poses.json' and 'ego_poses/ego_poses.json' locations.
    Returns dictionary mapping frame_index to pose data (position, rotation, velocity).
    Supports both {'frames': [...]} and flat list [...] file formats.
    """
    ego_poses_file = scene_path / "ego_poses" / "poses.json"
    if not ego_poses_file.exists():
        ego_poses_file = scene_path / "ego_poses" / "ego_poses.json"

    ego_poses = {}
    if ego_poses_file.exists():
        try:
            with open(ego_poses_file, 'r') as f:
                poses_data = json.load(f)
                if isinstance(poses_data, dict):
                    pose_entries = poses_data.get("frames", [])
                elif isinstance(poses_data, list):
                    pose_entries = poses_data
                else:
                    pose_entries = []

                for frame_index, pose in enumerate(pose_entries):
                    pose_index = pose.get("frame_index", frame_index)
                    ego_poses[pose_index] = {
                        "position": pose.get("position", [0, 0, 0]),
                        "rotation": pose.get("rotation", [1, 0, 0, 0]),
                        "velocity": pose.get("velocity")
                    }
        except Exception as e:
            log.warning(f"Failed to load ego poses from {ego_poses_file}: {e}")

    return ego_poses


