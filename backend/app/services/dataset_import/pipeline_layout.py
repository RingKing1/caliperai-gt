"""Filesystem layout detection shared by the upload and ZIP upload routes.

Both routes walk an extracted on-disk tree with identical heuristics:
recognise scene folders, apply generic-name parent substitution and
classify the per-scene data source. Kept dependency-light (no DB / ORM) so
the behaviour is trivially unit-testable.
"""
import logging
from pathlib import Path

from app.services.dataset_import.constants import GENERIC_FOLDER_NAMES

logger = logging.getLogger(__name__)

SUPPORTED_DATA_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".pcd", ".bin", ".ply",
    ".gif", ".bmp", ".tiff", ".tif",
}

_SCENE_SENSOR_FOLDERS = {"cameras", "lidar", "images", "pointcloud", "velodyne"}
_SKIP_FOLDERS = {"calibration", "metadata", "__MACOSX"}
_FLAT_PARENT_FOLDERS = {"cameras", "data"}


def find_data_files(directory: Path) -> list[Path]:
    """Find supported image / point-cloud files directly in *directory*."""
    return sorted(
        (f for f in directory.iterdir()
         if f.is_file() and f.suffix.lower() in SUPPORTED_DATA_SUFFIXES),
        key=lambda x: x.name,
    )


def is_scene_folder(directory: Path) -> bool:
    """A directory is a scene when it contains a sensor folder or calibration.json."""
    for item in directory.iterdir():
        if item.is_dir() and item.name.lower() in _SCENE_SENSOR_FOLDERS:
            return True
    if (directory / "calibration.json").exists():
        return True
    return False


def detect_scene_dirs(
    root_path: Path, *, debug: bool = False
) -> tuple[list[Path], dict[Path, str]]:
    """Resolve which sub-directories of *root_path* should be imported.

    Returns ``(scene_dirs, scene_parent_names)`` where ``scene_parent_names``
    maps a scene dir to the parent folder name to use for naming when the
    scene folder itself has a generic name (``data``/``scenes``/...).
    """
    scene_dirs: list[Path] = []
    scene_parent_names: dict[Path, str] = {}

    if is_scene_folder(root_path):
        return [root_path], scene_parent_names

    for item in root_path.iterdir():
        if item.is_dir() and item.name not in _SKIP_FOLDERS and is_scene_folder(item):
            scene_dirs.append(item)
            if (item.name.lower() in GENERIC_FOLDER_NAMES
                    and root_path.name.lower() not in GENERIC_FOLDER_NAMES):
                scene_parent_names[item] = root_path.name

    if scene_dirs:
        return scene_dirs, scene_parent_names

    if debug:
        logger.debug("No scene folders found, checking for flat image structure...")
    root_data_files = find_data_files(root_path)
    if debug:
        logger.debug("Found %d data files in root", len(root_data_files))

    if root_data_files:
        return [root_path], scene_parent_names

    if root_path.name.lower() in _FLAT_PARENT_FOLDERS:
        for subdir in root_path.iterdir():
            if subdir.is_dir():
                subdir_files = find_data_files(subdir)
                if subdir_files:
                    if debug:
                        logger.debug(
                            "Found %d files in %s, treating as scene",
                            len(subdir_files),
                            subdir.name,
                        )
                    scene_dirs.append(subdir)

    return scene_dirs, scene_parent_names


def classify_scene_data_files(scene_dir: Path) -> tuple[list[Path], str]:
    """Pick the primary data files for a scene and label the data source.

    Mirrors the upload-route if/elif precedence exactly, including the
    quirk that an existing (but empty) ``cameras`` folder wins over
    ``images`` / loose files and yields ``([], "unknown")``.
    """
    lidar_path = scene_dir / "lidar"
    cameras_path = scene_dir / "cameras"
    images_path = scene_dir / "images"

    data_files: list[Path] = []
    data_source = "unknown"

    if lidar_path.exists():
        data_files = [
            f for f in lidar_path.iterdir()
            if f.suffix.lower() in (".pcd", ".bin", ".ply")
        ]
        data_source = "lidar"
    elif cameras_path.exists():
        for cam_dir in cameras_path.iterdir():
            if cam_dir.is_dir():
                data_files = [
                    f for f in cam_dir.iterdir()
                    if f.suffix.lower() in (".jpg", ".png", ".jpeg")
                ]
                data_source = f"camera:{cam_dir.name}"
                break
    elif images_path.exists():
        data_files = [
            f for f in images_path.iterdir()
            if f.suffix.lower() in (".jpg", ".png", ".jpeg", ".gif",
                                    ".bmp", ".tiff", ".tif")
        ]
        data_source = "images"
    else:
        data_files = find_data_files(scene_dir)
        data_source = "direct"

    return sorted(data_files, key=lambda x: x.name), data_source
