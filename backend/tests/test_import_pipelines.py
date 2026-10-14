"""
Characterization tests for the three dataset upload pipelines.

These tests pin the CURRENT behaviour of:
* POST /import/upload        -> upload_and_import_dataset
* POST /import/upload-zip    -> upload_zip_and_import_dataset
* POST /import/upload-video  -> upload_video_and_import_dataset

They are a safety net for the planned orchestrator extraction that will
de-duplicate the upload/zip per-scene loops. Strategy: call the route
functions directly (same style as test_browse_security.py), exercise the
real filesystem layout / UUID-rename / scene-detection code, and mock only
the DB session and the heavy side-effect boundaries (MinIO mirror,
annotation import, auto task creation, ffmpeg).

Notable behaviour intentionally pinned (a fork to reconcile later):
* /upload wraps EVERYTHING in ``except Exception`` and re-raises 500, so
  client errors raised inside (path traversal / magic-byte rejection)
  surface as 500, whereas /upload-zip and /upload-video re-raise the
  original 4xx via ``except HTTPException: raise``.
"""
import io
import time
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import import_data
from app.models.models import Frame, Scene
from app.services.dataset_import import generate_smart_scene_name
from app.services.dataset_import import storage as import_storage

VIDEO_SERVICE = "app.services.video_service"

JPG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 32
PCD_BYTES = (
    b"VERSION 0.7\nFIELDS x\nSIZE 4\nTYPE F\nCOUNT 1\n"
    b"WIDTH 1\nPOINTS 1\nDATA ascii\n0.5\n"
)


class FakeUploadFile:
    """Minimal UploadFile: serves its content once, then empty chunks."""

    def __init__(self, filename, content=b"", content_type="application/octet-stream"):
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._sent = False

    async def read(self, size=-1):
        if self._sent:
            return b""
        self._sent = True
        return self._content


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    """Execute #1 returns the dataset; all later queries return *existing*."""

    def __init__(self, dataset=None, existing_scene=None):
        self._dataset = dataset
        self._existing = existing_scene
        self.executes = 0
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, *_args, **_kwargs):
        self.executes += 1
        if self.executes == 1:
            return _FakeResult(self._dataset)
        return _FakeResult(self._existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _mock_dataset():
    dataset = MagicMock()
    dataset.id = uuid.uuid4()
    dataset.campaign.organization_id = uuid.uuid4()
    return dataset


def _mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


def _mock_task():
    task = MagicMock()
    task.id = uuid.uuid4()
    task.name = "Auto Task"
    return task


def _mock_taxonomy():
    taxonomy = MagicMock()
    taxonomy.name = "AutoTaxonomy"
    taxonomy.classes = ["car"]
    return taxonomy


def _wait_called(mock, timeout=2.0):
    """Wait for the fire-and-forget run_in_executor mirror to actually run."""
    deadline = time.time() + timeout
    while time.time() < deadline and not mock.called:
        time.sleep(0.01)
    assert mock.called, "expected _mirror_scene_to_minio to be scheduled"


def _patch_pipeline_deps(monkeypatch, tmp_path):
    """Patch every heavy side effect used by the import_data endpoints."""
    mirror_mock = MagicMock()
    monkeypatch.setattr(import_storage, "_mirror_scene_to_minio", mirror_mock)
    mocks = {
        "UPLOAD_DIR": tmp_path / "uploads",
        "_mirror_scene_to_minio": mirror_mock,
        "auto_create_tasks_for_scene": AsyncMock(return_value=None),
        "get_or_create_scene_import_task": AsyncMock(return_value=_mock_task()),
        "import_scene_annotations": AsyncMock(return_value=(0, 0)),
        "scan_annotations_for_classes": MagicMock(return_value=[]),
        "derive_and_merge_taxonomy": AsyncMock(return_value=_mock_taxonomy()),
    }
    for name, value in mocks.items():
        if name == "_mirror_scene_to_minio":
            continue  # patched on the storage module above
        monkeypatch.setattr(import_data, name, value, raising=True)
    return mocks


def _patch_video_service(monkeypatch, *, ffmpeg=True, magic_ok=True,
                         metadata=None, extraction=None):
    monkeypatch.setattr(f"{VIDEO_SERVICE}.is_ffmpeg_available",
                        MagicMock(return_value=ffmpeg))
    monkeypatch.setattr(f"{VIDEO_SERVICE}.validate_video_magic_bytes",
                        MagicMock(return_value=magic_ok))
    monkeypatch.setattr(f"{VIDEO_SERVICE}.get_video_metadata",
                        MagicMock(return_value=metadata or {
                            "duration": 10.0, "fps": 30.0,
                            "width": 640, "height": 480, "codec": "h264",
                        }))

    async def _default_extract(video_path, output_dir, fps, max_frames,
                               image_format):
        paths = []
        for idx in range(3):
            p = Path(output_dir) / f"frame_{idx:06d}.{image_format}"
            p.write_bytes(JPG_BYTES)
            paths.append(p)
        return paths, {
            "duration": 10.0, "fps": 30.0, "width": 640, "height": 480,
            "codec": "h264", "extraction_fps": 30.0,
            "timestamps": [0.0, 0.033, 0.066],
        }

    monkeypatch.setattr(f"{VIDEO_SERVICE}.extract_frames_async",
                        extraction or _default_extract)


def _scenes(db):
    return [o for o in db.added if isinstance(o, Scene)]


def _frames(db):
    return [o for o in db.added if isinstance(o, Frame)]


def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def _call_upload(db, files, *, dataset_id=None, user=None,
                       derive_taxonomy=False, overwrite_annotations=False,
                       preserve_folder_names=True):
    return await import_data.upload_and_import_dataset(
        current_user=user or _mock_user(),
        dataset_id=str(dataset_id or uuid.uuid4()),
        files=files,
        derive_taxonomy=derive_taxonomy,
        overwrite_annotations=overwrite_annotations,
        preserve_folder_names=preserve_folder_names,
        db=db,
    )


async def _call_zip(db, archive, *, filename="data.zip", dataset_id=None,
                    user=None, derive_taxonomy=False,
                    overwrite_annotations=False, preserve_folder_names=True,
                    name_overrides="{}", scene_descriptions="{}"):
    return await import_data.upload_zip_and_import_dataset(
        current_user=user or _mock_user(),
        dataset_id=str(dataset_id or uuid.uuid4()),
        file=FakeUploadFile(filename, archive),
        derive_taxonomy=derive_taxonomy,
        overwrite_annotations=overwrite_annotations,
        preserve_folder_names=preserve_folder_names,
        name_overrides=name_overrides,
        scene_descriptions=scene_descriptions,
        db=db,
    )


async def _call_video(db, *, filename="clip.mp4", content=b"x", dataset_id=None,
                      user=None, extraction_fps=None, max_frames=None,
                      image_format="jpg", preserve_folder_names=True):
    return await import_data.upload_video_and_import_dataset(
        current_user=user or _mock_user(),
        dataset_id=str(dataset_id or uuid.uuid4()),
        file=FakeUploadFile(filename, content),
        extraction_fps=extraction_fps,
        max_frames=max_frames,
        image_format=image_format,
        preserve_folder_names=preserve_folder_names,
        db=db,
    )


# ===========================================================================
# /import/upload
# ===========================================================================

@pytest.mark.asyncio
async def test_upload_missing_dataset_returns_404(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=None)

    with pytest.raises(HTTPException) as exc:
        await _call_upload(db, [FakeUploadFile("a/lidar/0001.pcd", PCD_BYTES)])
    assert exc.value.status_code == 404
    assert not db.committed


@pytest.mark.asyncio
async def test_upload_traversal_currently_surfaces_as_500(tmp_path, monkeypatch):
    # Characterization pin: /upload's broad `except Exception` turns the
    # validator's 400 into a 500 (zip/video keep the 400).
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await _call_upload(db, [FakeUploadFile("../escape.pcd", b"x")])
    assert exc.value.status_code == 500
    assert db.rolled_back


@pytest.mark.asyncio
async def test_upload_bad_jpeg_magic_currently_surfaces_as_500(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await _call_upload(db, [FakeUploadFile("s/images/0001.jpg", b"not-jpeg")])
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_upload_lidar_scene_happy_path(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    dataset = _mock_dataset()
    db = FakeSession(dataset=dataset)

    resp = await _call_upload(
        db,
        [
            FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES),
            FakeUploadFile("scene_a/lidar/0002.pcd", PCD_BYTES),
        ],
        dataset_id=dataset.id,
    )

    assert resp.success is True
    assert resp.scenes_imported == 1
    assert resp.frames_imported == 2
    assert resp.errors == []
    assert db.committed

    scenes, frames = _scenes(db), _frames(db)
    assert len(scenes) == 1
    assert scenes[0].name == "scene_a"
    assert scenes[0].frame_count == 2
    assert scenes[0].scene_metadata["source"] == "browser_upload"
    assert scenes[0].scene_metadata["data_source"] == "lidar"
    assert [f.frame_index for f in frames] == [0, 1]
    assert all(f.scene_id == scenes[0].id for f in frames)

    scene_dirs = list((tmp_path / "uploads" / str(dataset.id)).iterdir())
    assert len(scene_dirs) == 1
    lidar_files = list((scene_dirs[0] / "lidar").iterdir())
    assert len(lidar_files) == 2
    assert all(f.suffix == ".pcd" for f in lidar_files)

    deps["import_scene_annotations"].assert_awaited_once()
    kwargs = deps["import_scene_annotations"].await_args.kwargs
    assert kwargs["overwrite"] is False
    assert kwargs["scene"].name == "scene_a"
    deps["get_or_create_scene_import_task"].assert_awaited_once()
    _wait_called(deps["_mirror_scene_to_minio"])
    mirror_args = deps["_mirror_scene_to_minio"].call_args.args
    assert mirror_args[:3] == (
        dataset.campaign.organization_id, dataset.id, scenes[0].id
    )


@pytest.mark.asyncio
async def test_upload_overwrite_flag_passed_to_importer(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    dataset = _mock_dataset()
    db = FakeSession(dataset=dataset)

    await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES)],
        dataset_id=dataset.id, overwrite_annotations=True,
    )

    kwargs = deps["import_scene_annotations"].await_args.kwargs
    assert kwargs["overwrite"] is True


@pytest.mark.asyncio
async def test_upload_preserve_false_uses_smart_name(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES)],
        preserve_folder_names=False,
    )

    assert _scenes(db)[0].name == generate_smart_scene_name("scene_a", 1)
    assert resp.scenes_imported == 1


@pytest.mark.asyncio
async def test_upload_generic_folder_inherits_parent_name(tmp_path, monkeypatch):
    # my_trip/data/images/*.jpg -> scene name "my_trip" (generic "data" skipped)
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db, [FakeUploadFile("my_trip/data/images/0001.jpg", JPG_BYTES)],
    )

    assert resp.scenes_imported == 1
    assert _scenes(db)[0].name == "my_trip"


@pytest.mark.asyncio
async def test_upload_flat_images_treated_as_single_camera(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db,
        [
            FakeUploadFile("batch/img1.jpg", JPG_BYTES),
            FakeUploadFile("batch/img2.jpg", JPG_BYTES),
        ],
    )

    scene = _scenes(db)[0]
    assert resp.frames_imported == 2
    assert scene.name == "batch"
    assert scene.scene_metadata["data_source"] == "direct"
    assert "batch" in (scene.storage_paths.get("cameras") or {})
    assert len(_frames(db)) == 2


@pytest.mark.asyncio
async def test_upload_scene_without_frames_recorded_as_error(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/readme.txt", b"no frames here")],
    )

    assert resp.success is False
    assert resp.scenes_imported == 0
    assert resp.frames_imported == 0
    assert resp.errors == ["Scene scene_a: No frames detected"]
    assert _scenes(db) == []
    assert db.committed


@pytest.mark.asyncio
async def test_upload_duplicate_scene_name_is_suffixed(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset(), existing_scene=MagicMock())

    resp = await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES)],
    )

    assert resp.scenes_imported == 1
    assert len(resp.renamed_scenes) == 1
    renamed = resp.renamed_scenes[0]
    assert renamed.original_name == "scene_a"
    assert renamed.new_name.startswith("scene_a_upload-")
    assert _scenes(db)[0].name == renamed.new_name


@pytest.mark.asyncio
async def test_upload_derive_taxonomy_with_classes(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    deps["scan_annotations_for_classes"].return_value = {"car"}
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES)],
        derive_taxonomy=True,
    )

    deps["derive_and_merge_taxonomy"].assert_awaited_once()
    assert resp.errors == [
        "Taxonomy: Created/updated 'AutoTaxonomy' with 1 classes"
    ]


@pytest.mark.asyncio
async def test_upload_derive_taxonomy_without_classes(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    deps["scan_annotations_for_classes"].return_value = set()
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_upload(
        db, [FakeUploadFile("scene_a/lidar/0001.pcd", PCD_BYTES)],
        derive_taxonomy=True,
    )

    deps["derive_and_merge_taxonomy"].assert_not_called()
    assert resp.errors == ["Taxonomy: No annotation classes found to derive"]


# ===========================================================================
# /import/upload-zip
# ===========================================================================

@pytest.mark.asyncio
async def test_zip_rejects_non_zip_extension_with_400(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        await _call_zip(FakeSession(), b"x", filename="data.tar")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_zip_rejects_bad_magic_with_400(tmp_path, monkeypatch):
    # zip re-raises HTTPException (no rollback on the way out), unlike /upload.
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await _call_zip(db, b"NOT A ZIP")
    assert exc.value.status_code == 400
    assert db.rolled_back is False


@pytest.mark.asyncio
async def test_zip_missing_dataset_returns_404(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    archive = _zip_bytes({"x/lidar/a.pcd": PCD_BYTES})

    with pytest.raises(HTTPException) as exc:
        await _call_zip(FakeSession(dataset=None), archive)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_zip_single_scene_happy_path(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    dataset = _mock_dataset()
    db = FakeSession(dataset=dataset)

    archive = _zip_bytes({
        "scene_a/lidar/0001.pcd": PCD_BYTES,
        "scene_a/lidar/0002.pcd": PCD_BYTES,
    })
    resp = await _call_zip(db, archive, dataset_id=dataset.id)

    assert resp.success is True
    assert resp.scenes_imported == 1
    assert resp.frames_imported == 2
    assert "from ZIP" in resp.message
    assert _scenes(db)[0].name == "scene_a"
    assert len(_frames(db)) == 2
    deps["import_scene_annotations"].assert_awaited_once()
    assert deps["import_scene_annotations"].await_args.kwargs["overwrite"] is False
    _wait_called(deps["_mirror_scene_to_minio"])


@pytest.mark.asyncio
async def test_zip_macosx_meta_does_not_block_root_descent(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    archive = _zip_bytes({
        "__MACOSX/._scene_a": b"\x00",
        "scene_a/lidar/0001.pcd": PCD_BYTES,
    })
    resp = await _call_zip(db, archive)

    assert resp.scenes_imported == 1
    assert _scenes(db)[0].name == "scene_a"


@pytest.mark.asyncio
async def test_zip_name_and_description_overrides_applied(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    archive = _zip_bytes({"scene_a/lidar/0001.pcd": PCD_BYTES})
    resp = await _call_zip(
        db, archive,
        name_overrides='{"scene_a": "Renamed Scene"}',
        scene_descriptions='{"scene_a": "Custom desc"}',
    )

    scene = _scenes(db)[0]
    assert resp.scenes_imported == 1
    assert scene.name == "Renamed Scene"
    assert scene.description == "Custom desc"


@pytest.mark.asyncio
async def test_zip_malformed_overrides_json_ignored(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())

    archive = _zip_bytes({"scene_a/lidar/0001.pcd": PCD_BYTES})
    resp = await _call_zip(
        db, archive, name_overrides="{bad", scene_descriptions="also bad",
    )

    assert resp.scenes_imported == 1
    assert _scenes(db)[0].name == "scene_a"


# ===========================================================================
# /import/upload-video
# ===========================================================================

@pytest.mark.asyncio
async def test_video_ffmpeg_unavailable_returns_503(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch, ffmpeg=False)

    with pytest.raises(HTTPException) as exc:
        await _call_video(FakeSession())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_video_rejects_bad_extension_with_400(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await _call_video(FakeSession(), filename="clip.txt")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_video_missing_dataset_returns_404(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await _call_video(FakeSession(dataset=None))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_video_bad_magic_returns_400(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch, magic_ok=False)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await _call_video(db)
    assert exc.value.status_code == 400
    assert db.rolled_back is False


@pytest.mark.asyncio
async def test_video_duplicate_scene_returns_409(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch)
    db = FakeSession(dataset=_mock_dataset(), existing_scene=MagicMock())

    with pytest.raises(HTTPException) as exc:
        await _call_video(db, filename="my_clip.mp4")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_video_zero_extracted_frames_returns_400(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)

    async def _empty_extract(**_kwargs):
        return [], {
            "duration": 1.0, "fps": 30.0, "width": 1, "height": 1,
            "codec": "h264", "extraction_fps": 30.0, "timestamps": [],
        }

    _patch_video_service(monkeypatch, extraction=_empty_extract)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await _call_video(db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_video_happy_path_creates_scene_and_frames(tmp_path, monkeypatch):
    deps = _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch)
    dataset = _mock_dataset()
    db = FakeSession(dataset=dataset)

    resp = await _call_video(db, filename="my_clip.mp4", dataset_id=dataset.id)

    assert resp.success is True
    assert resp.scenes_imported == 1
    assert resp.frames_imported == 3
    assert len(resp.errors) == 2

    scene, frames = _scenes(db)[0], _frames(db)
    assert scene.name == "my_clip"
    assert scene.frame_count == 3
    assert scene.fps == 30.0
    assert scene.scene_metadata["source"] == "video_upload"
    assert scene.scene_metadata["original_filename"] == "my_clip.mp4"
    assert scene.storage_paths["cameras"] == {
        "video": f"uploads/{dataset.id}/{scene.id}/cameras/video"
    }
    assert [f.frame_index for f in frames] == [0, 1, 2]
    for frame in frames:
        assert frame.file_paths["cameras"] == {"video": frame.file_paths["cameras"]["video"]}
        assert frame.file_paths["cameras"]["video"].endswith(".jpg")

    deps["get_or_create_scene_import_task"].assert_awaited_once()
    deps["import_scene_annotations"].assert_not_called()
    assert db.committed
    _wait_called(deps["_mirror_scene_to_minio"])


@pytest.mark.asyncio
async def test_video_generic_filename_uses_smart_name(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_video_service(monkeypatch)
    db = FakeSession(dataset=_mock_dataset())

    resp = await _call_video(db, filename="data.mp4")

    assert _scenes(db)[0].name == generate_smart_scene_name("data", 1)
    assert resp.scenes_imported == 1


# ===========================================================================
# Shared pipeline-layout helpers (pure)
# ===========================================================================

from app.services.dataset_import import (  # noqa: E402
    build_import_frame_rows,
    classify_scene_data_files,
    detect_scene_dirs,
)


@pytest.mark.asyncio
async def test_classify_prefers_lidar_then_cameras_then_images(tmp_path):
    scene = tmp_path / "s"
    (scene / "lidar").mkdir(parents=True)
    (scene / "cameras" / "front").mkdir(parents=True)
    (scene / "images").mkdir(parents=True)
    (scene / "lidar" / "b.pcd").write_bytes(b"VERSION 0.7\n")
    (scene / "lidar" / "a.pcd").write_bytes(b"VERSION 0.7\n")
    (scene / "cameras" / "front" / "x.jpg").write_bytes(JPG_BYTES)
    (scene / "images" / "y.jpg").write_bytes(JPG_BYTES)

    files, source = classify_scene_data_files(scene)
    assert source == "lidar"
    assert [f.name for f in files] == ["a.pcd", "b.pcd"]

    import shutil
    shutil.rmtree(scene / "lidar")
    files, source = classify_scene_data_files(scene)
    assert source == "camera:front"
    assert [f.name for f in files] == ["x.jpg"]

    shutil.rmtree(scene / "cameras")
    files, source = classify_scene_data_files(scene)
    assert source == "images"
    assert [f.name for f in files] == ["y.jpg"]


@pytest.mark.asyncio
async def test_classify_empty_cameras_does_not_fall_back(tmp_path):
    # Pinned quirk: an existing-but-empty cameras folder wins and yields
    # ("unknown", []) instead of falling through to images/direct.
    scene = tmp_path / "s"
    (scene / "cameras").mkdir(parents=True)
    (scene / "images").mkdir()
    (scene / "images" / "y.jpg").write_bytes(JPG_BYTES)

    files, source = classify_scene_data_files(scene)
    assert files == []
    assert source == "unknown"


@pytest.mark.asyncio
async def test_classify_loose_files_are_direct(tmp_path):
    scene = tmp_path / "s"
    scene.mkdir()
    (scene / "02.jpg").write_bytes(JPG_BYTES)
    (scene / "01.jpg").write_bytes(JPG_BYTES)
    (scene / "notes.txt").write_text("x")

    files, source = classify_scene_data_files(scene)
    assert source == "direct"
    assert [f.name for f in files] == ["01.jpg", "02.jpg"]


@pytest.mark.asyncio
async def test_detect_scene_dirs_root_and_children_and_generic_parent(tmp_path):
    # Root itself is a scene
    root1 = tmp_path / "scene_root"
    (root1 / "lidar").mkdir(parents=True)
    dirs, parent_names = detect_scene_dirs(root1)
    assert dirs == [root1]
    assert parent_names == {}

    # Multiple child scenes
    root2 = tmp_path / "multi"
    (root2 / "a" / "lidar").mkdir(parents=True)
    (root2 / "b" / "images").mkdir(parents=True)
    (root2 / "calibration").mkdir()
    dirs, parent_names = detect_scene_dirs(root2)
    assert {d.name for d in dirs} == {"a", "b"}
    assert parent_names == {}

    # Generic child folder inherits the parent folder name
    root3 = tmp_path / "my_trip"
    (root3 / "data" / "images").mkdir(parents=True)
    (root3 / "data" / "images" / "f.jpg").write_bytes(JPG_BYTES)
    dirs, parent_names = detect_scene_dirs(root3)
    assert [d.name for d in dirs] == ["data"]
    assert parent_names[dirs[0]] == "my_trip"


@pytest.mark.asyncio
async def test_detect_scene_dirs_flat_files_and_cameras_subdirs(tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "1.jpg").write_bytes(JPG_BYTES)
    dirs, _ = detect_scene_dirs(flat)
    assert dirs == [flat]

    cams = tmp_path / "cameras"
    (cams / "front").mkdir(parents=True)
    (cams / "front" / "1.jpg").write_bytes(JPG_BYTES)
    dirs, _ = detect_scene_dirs(cams)
    assert [d.name for d in dirs] == ["front"]

    empty = tmp_path / "empty"
    empty.mkdir()
    dirs, _ = detect_scene_dirs(empty)
    assert dirs == []


@pytest.mark.asyncio
async def test_build_import_frame_rows_alignment_and_meta(tmp_path):
    class _Scene:
        id = uuid.uuid4()
        fps = 10.0

    scene_dir = tmp_path / "scene"
    (scene_dir / "lidar").mkdir(parents=True)
    lidar_files = [scene_dir / "lidar" / f"{i}.pcd" for i in range(2)]
    camera_files = {"front": [scene_dir / f"f{i}.jpg" for i in range(3)]}
    for f in lidar_files + sum(camera_files.values(), []):
        f.write_bytes(b"x")

    rename_map = {
        "lidar/0.pcd": {"original_name": "0001.pcd"},
    }
    ego = {1: {"position": [0, 0, 0], "timestamp": 12.5}}

    frames = build_import_frame_rows(
        scene=_Scene(),
        permanent_scene_dir=scene_dir,
        permanent_data_files=lidar_files,
        lidar_files=lidar_files,
        camera_files=camera_files,
        uuid_rename_map=rename_map,
        ego_poses_data=ego,
    )

    assert len(frames) == 2
    assert frames[0].file_paths["lidar"] == "0.pcd"
    assert frames[0].file_paths["cameras"] == {"front": "f0.jpg"}
    assert frames[0].file_paths["_meta"]["original_filename"] == "0001.pcd"
    assert frames[0].timestamp == 0.0  # 0 / fps
    assert frames[1].file_paths["_meta"]["original_filename"] == "1.pcd"
    assert frames[1].timestamp == 12.5  # ego pose wins
    assert frames[1].ego_pose == ego[1]


# ===========================================================================
# /import  (local server-folder import; regression guard for the scene_name
#           F821 NameError that previously made every scene fail)
# ===========================================================================

from app.services.dataset_import.schemas import ImportRequest  # noqa: E402


def _build_local_dataset(root: Path, *, with_meta_name=True):
    (root / "scenes" / "scene_alpha" / "lidar").mkdir(parents=True)
    (root / "scenes" / "scene_alpha" / "lidar" / "0001.pcd").write_bytes(PCD_BYTES)
    (root / "scenes" / "scene_alpha" / "lidar" / "0002.pcd").write_bytes(PCD_BYTES)
    if with_meta_name:
        (root / "scenes" / "scene_alpha" / "scene_metadata.json").write_text(
            '{"name": "Alpha Scene", "fps": 5.0, "frame_count": 2}'
        )


@pytest.mark.asyncio
async def test_local_import_uses_scene_meta_name(tmp_path, monkeypatch):
    monkeypatch.setattr(import_data, "auto_create_tasks_for_scene", AsyncMock())
    dataset = _mock_dataset()
    db = FakeSession(dataset=dataset)
    root = tmp_path / "ds"
    _build_local_dataset(root)

    req = ImportRequest(dataset_id=dataset.id, root_path=str(root))
    resp = await import_data.import_dataset(request=req, current_user=_mock_user(), db=db)

    assert resp.success is True
    assert resp.errors == []
    assert resp.scenes_imported == 1
    assert resp.frames_imported == 2
    assert resp.renamed_scenes == []
    scene = _scenes(db)[0]
    assert scene.name == "Alpha Scene"
    assert scene.fps == 5.0
    assert [f.frame_index for f in _frames(db)] == [0, 1]
    assert db.committed


@pytest.mark.asyncio
async def test_local_import_falls_back_to_folder_name(tmp_path, monkeypatch):
    monkeypatch.setattr(import_data, "auto_create_tasks_for_scene", AsyncMock())
    db = FakeSession(dataset=_mock_dataset())
    root = tmp_path / "ds"
    _build_local_dataset(root, with_meta_name=False)

    req = ImportRequest(dataset_id=_mock_dataset().id, root_path=str(root))
    resp = await import_data.import_dataset(request=req, current_user=_mock_user(), db=db)

    assert resp.success is True
    assert _scenes(db)[0].name == "scene_alpha"


@pytest.mark.asyncio
async def test_local_import_duplicate_name_is_suffixed(tmp_path, monkeypatch):
    monkeypatch.setattr(import_data, "auto_create_tasks_for_scene", AsyncMock())
    db = FakeSession(dataset=_mock_dataset(), existing_scene=MagicMock())
    root = tmp_path / "ds"
    _build_local_dataset(root)

    req = ImportRequest(dataset_id=_mock_dataset().id, root_path=str(root))
    resp = await import_data.import_dataset(request=req, current_user=_mock_user(), db=db)

    assert resp.success is True
    assert len(resp.renamed_scenes) == 1
    renamed = resp.renamed_scenes[0]
    assert renamed.original_name == "Alpha Scene"
    assert renamed.new_name.startswith("Alpha Scene_upload-")
    assert _scenes(db)[0].name == renamed.new_name
