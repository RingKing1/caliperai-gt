"""Regression tests for frame image path resolution across import layouts.

The image endpoint historically assumed every frame lived under
``<scene>/cameras/<camera>/`` with a lidar file as the frame primary, so
``images/`` fallback bundles and flat bundles always returned 404. Image
only frames also failed ``GET /frames`` because ``FrameFilePaths.lidar`` was
required. These tests pin all three on-disk layouts.
"""
from pathlib import Path

import pytest

from app.schemas.schemas import FrameFilePaths
from app.services.scene_service import (
    resolve_frame_image_path as _resolve_frame_image_path,
)


def _frame_paths(tmp_path: Path, primary_rel: str, cameras: dict) -> dict:
    primary = tmp_path / primary_rel
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_bytes(b"")
    for rel in cameras.values():
        image = tmp_path / rel
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"")
    return {
        "cameras": {key: Path(rel).name for key, rel in cameras.items()},
        "_meta": {
            "absolute_path": str(primary),
            "relative_path": primary_rel,
        },
    }


def test_canonical_lidar_primary(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "lidar/0.pcd",
        {"front": "cameras/front/0.jpg"},
    )
    assert _resolve_frame_image_path(file_paths, "front") == tmp_path / "cameras/front/0.jpg"


def test_canonical_raw_camera_key_normalized(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "lidar/0.pcd",
        {"camera_0_front100": "cameras/camera_0_front100/0.jpg"},
    )
    resolved = _resolve_frame_image_path(file_paths, "front")
    assert resolved == tmp_path / "cameras/camera_0_front100/0.jpg"


def test_canonical_cameras_only_primary(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "cameras/front/0.jpg",
        {"front": "cameras/front/0.jpg"},
    )
    assert _resolve_frame_image_path(file_paths, "front") == tmp_path / "cameras/front/0.jpg"


def test_images_fallback_layout(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "images/0.jpg",
        {"images": "images/0.jpg"},
    )
    assert _resolve_frame_image_path(file_paths, "images") == tmp_path / "images/0.jpg"
    assert _resolve_frame_image_path(file_paths, "front") == tmp_path / "images/0.jpg"


def test_flat_fallback_layout(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "0.jpg",
        {"default": "0.jpg"},
    )
    assert _resolve_frame_image_path(file_paths, "default") == tmp_path / "0.jpg"


def test_unknown_camera_in_multi_camera_bundle(tmp_path):
    file_paths = _frame_paths(
        tmp_path,
        "lidar/0.pcd",
        {
            "front": "cameras/front/0.jpg",
            "back": "cameras/back/0.jpg",
        },
    )
    assert _resolve_frame_image_path(file_paths, "left") is None


def test_missing_file_returns_none(tmp_path):
    file_paths = _frame_paths(tmp_path, "lidar/0.pcd", {})
    file_paths["cameras"] = {"front": "missing.jpg"}
    assert _resolve_frame_image_path(file_paths, "front") is None


def test_legacy_rows_without_relative_path(tmp_path):
    image = tmp_path / "legacy_scene/cameras/front/0.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    lidar = tmp_path / "legacy_scene/lidar/0.pcd"
    lidar.parent.mkdir(parents=True)
    lidar.write_bytes(b"")
    file_paths = {
        "cameras": {"front": "0.jpg"},
        "_meta": {"absolute_path": str(lidar)},
    }
    assert _resolve_frame_image_path(file_paths, "front") == image


def test_frame_file_paths_lidar_optional():
    assert FrameFilePaths(cameras={}).lidar is None
    assert FrameFilePaths(lidar="0.pcd", cameras={}).lidar == "0.pcd"


@pytest.mark.parametrize("meta", [{}, {"_meta": {}}, {"_meta": {"absolute_path": "rel/0.pcd"}}])
def test_malformed_meta_returns_none(meta):
    file_paths = {**meta, "cameras": {"front": "0.jpg"}}
    assert _resolve_frame_image_path(file_paths, "front") is None
