"""Unit tests for the shared upload/ZIP per-scene orchestration.

These pin the historical per-route divergences that ``PipelineSpec`` keeps
explicit instead of silently unifying.
"""
import json

from app.services.dataset_import import scene_pipeline as sp


class _FakeDataset:
    id = "dataset-id"


def _request(tmp_path, **kwargs):
    defaults = {
        "dataset": _FakeDataset(),
        "user": None,
        "dataset_upload_dir": tmp_path,
        "dataset_calibration": {
            "lidar_to_cameras": {"front": {"inherited": True}},
        },
    }
    defaults.update(kwargs)
    return sp.SceneImportRequest(**defaults)


def test_zip_uses_name_and_description_overrides():
    req = sp.SceneImportRequest(
        dataset=_FakeDataset(),
        user=None,
        dataset_upload_dir="/tmp",
        name_overrides={"scene_a": "renamed"},
        scene_descriptions={"scene_a": "desc"},
    )
    name, override, description = sp.resolve_scene_name(
        sp.ZIP_PIPELINE, req, 1, "scene_a"
    )
    assert name == "renamed"
    assert override == "renamed"
    assert description == "desc"


def test_upload_ignores_overrides_and_preserves_name():
    req = sp.SceneImportRequest(
        dataset=_FakeDataset(),
        user=None,
        dataset_upload_dir="/tmp",
        name_overrides={"scene_a": "renamed"},
    )
    name, override, description = sp.resolve_scene_name(
        sp.UPLOAD_PIPELINE, req, 1, "scene_a"
    )
    assert name == "scene_a"
    assert override is None
    assert description is None


def test_calibration_zip_inherits_dataset_level(tmp_path):
    scene_dir = tmp_path / "scene"
    scene_dir.mkdir()
    result = sp.resolve_scene_calibration(
        sp.ZIP_PIPELINE, _request(tmp_path), scene_dir, {}
    )
    assert result["lidar_to_cameras"] == {"front": {"inherited": True}}


def test_calibration_upload_resets_without_inheritance(tmp_path):
    scene_dir = tmp_path / "scene"
    scene_dir.mkdir()
    result = sp.resolve_scene_calibration(
        sp.UPLOAD_PIPELINE, _request(tmp_path), scene_dir, {}
    )
    assert result is None


def test_ego_poses_accept_json_list_only_for_zip(tmp_path):
    scene_dir = tmp_path / "scene"
    (scene_dir / "ego_poses").mkdir(parents=True)
    (scene_dir / "ego_poses" / "poses.json").write_text(
        json.dumps([{"position": [1, 0, 0]}])
    )
    zip_poses, zip_rel = sp.read_scene_ego_poses(
        sp.ZIP_PIPELINE, scene_dir, scene_dir, "uploads/d/s"
    )
    assert zip_rel == "uploads/d/s/ego_poses/poses.json"
    assert zip_poses[0] == {"position": [1, 0, 0]}

    # same file shape on the upload route: not a {"frames": ...} document,
    # so it is ignored and parent-metadata synthesis kicks in instead
    (scene_dir / "ego_poses" / "poses.json").unlink()
    up_poses, up_rel = sp.read_scene_ego_poses(
        sp.UPLOAD_PIPELINE, scene_dir, scene_dir, "uploads/d/s"
    )
    assert up_poses == {}
    assert up_rel is None


def test_upload_synthesizes_ego_poses_from_parent_metadata(tmp_path):
    source_scene = tmp_path / "bundle" / "data"
    permanent = tmp_path / "permanent"
    (source_scene).mkdir(parents=True)
    permanent.mkdir()
    (tmp_path / "bundle" / "metadata.json").write_text(json.dumps({
        "frames": [
            {"frame_index": 0, "ego_pose": {
                "position": [1, 2, 3], "rotation": [1, 0, 0, 0],
                "timestamp": 0.1}}
        ]
    }))
    poses, rel = sp.read_scene_ego_poses(
        sp.UPLOAD_PIPELINE, permanent, source_scene, "uploads/d/s"
    )
    assert poses[0]["position"] == [1, 2, 3]
    assert rel == "uploads/d/s/ego_poses/ego_poses.json"
    assert (permanent / "ego_poses" / "ego_poses.json").exists()
