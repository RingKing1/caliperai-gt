"""Tests for calibration schemas (resolution/camera_model contract)."""
import pytest
from pydantic import ValidationError

from app.schemas.scene import IntrinsicCalibration, SceneCalibration, SceneUpdate


def _intrinsic_kwargs(**overrides):
    base = dict(fx=1000.0, fy=1000.0, cx=960.0, cy=540.0)
    base.update(overrides)
    return base


def test_intrinsic_calibration_keeps_resolution_and_camera_model():
    intrinsic = IntrinsicCalibration(
        **_intrinsic_kwargs(
            resolution=[1920, 1080],
            camera_model="kannala_brandt",
        )
    )
    assert intrinsic.resolution == (1920, 1080)
    assert intrinsic.camera_model == "kannala_brandt"
    dumped = intrinsic.model_dump(mode="json")
    assert dumped["resolution"] == [1920, 1080]
    assert dumped["camera_model"] == "kannala_brandt"


def test_intrinsic_calibration_defaults_new_fields_to_none():
    intrinsic = IntrinsicCalibration(**_intrinsic_kwargs())
    assert intrinsic.resolution is None
    assert intrinsic.camera_model is None


@pytest.mark.parametrize("resolution", [[1920], [1920, 1080, 3], []])
def test_intrinsic_calibration_rejects_non_pair_resolution(resolution):
    with pytest.raises(ValidationError):
        IntrinsicCalibration(**_intrinsic_kwargs(resolution=resolution))


def test_intrinsic_calibration_rejects_unknown_camera_model():
    with pytest.raises(ValidationError):
        IntrinsicCalibration(**_intrinsic_kwargs(camera_model="fisheye_ocam"))


def test_scene_update_preserves_intrinsic_extensions():
    update = SceneUpdate(
        calibration=SceneCalibration(
            lidar_to_cameras={
                "cam_front": {
                    "extrinsic": {
                        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "translation": [0.0, 0.0, 0.0],
                    },
                    "intrinsic": {
                        **_intrinsic_kwargs(
                            resolution=[1920, 1080],
                            camera_model="pinhole",
                        ),
                    },
                }
            }
        )
    )
    intrinsic = update.calibration.lidar_to_cameras["cam_front"].intrinsic
    assert intrinsic.resolution == (1920, 1080)
    assert intrinsic.camera_model == "pinhole"
