"""Filesystem paths and static constants for dataset import flows."""
import os
from pathlib import Path

SEGMENTATION_ROOT = os.environ.get("SEGMENTATION_ROOT", "/uploads/segmentation")

UPLOAD_DIR = Path("/uploads")

GENERIC_FOLDER_NAMES = {
    'data', 'dataset', 'scenes', 'scene', 'default', 'default_scene',
    'test', 'sample', 'extracted',
}

FUSION_3D_TYPES = {"cuboid", "segmentation_3d", "cuboid_fusion"}

ONLY_2D_TYPES = {"box2d", "polygon", "polyline", "keypoints", "segmentation_2d", "semantic_segment"}

LIDAR_SENSOR_PATTERNS = {"lidar", "lidar_4d", "velodyne", "point_cloud", "pcd"}
AUTO_CLASS_COLORS = [
    "#FF6B6B",
    "#4ECDC4",
    "#45B7D1",
    "#96CEB4",
    "#FFEAA7",
    "#DDA0DD",
    "#98D8C8",
    "#F7DC6F",
    "#BB8FCE",
    "#85C1E9",
    "#F8B500",
    "#00CED1",
    "#FF69B4",
    "#90EE90",
    "#DEB887",
    "#87CEEB",
]


CLASS_COLOR_PALETTE = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
    '#F1948A', '#82E0AA', '#F8C471', '#D7BDE2', '#A9CCE3',
    '#FAD7A0', '#A3E4D7', '#D5A6BD', '#AED6F1', '#F5B7B1',
]


