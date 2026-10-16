"""Tests for background import jobs: staging endpoints + runner state machine."""
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import import_data
from app.models.models import ImportJob
from app.services.dataset_import import import_jobs
from app.services.dataset_import.schemas import ImportResponse
from tests.test_import_pipelines import (
    JPG_BYTES,
    FakeSession,
    FakeUploadFile,
    _mock_dataset,
    _mock_user,
    _patch_pipeline_deps,
    _zip_bytes,
)


class _JobStore:
    """Session factory backing one ImportJob row for the background runner."""

    def __init__(self, job, exists=True):
        self.job = job
        self.exists = exists

    def __call__(self):
        store = self

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, model, pk):
                if model is ImportJob and pk == store.job.id:
                    return store.job
                return None

            def add(self, obj):
                store.job = obj

            async def commit(self):
                pass

            async def refresh(self, _obj, **_kw):
                pass

            async def execute(self, _stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return object() if store.exists else None

                    def scalar_one(self):
                        return MagicMock()

                return _R()

        return _Session()


def _patch_schedule(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        import_data, "schedule_import_job", lambda job_id: scheduled.append(job_id)
    )
    return scheduled


def _stage_under_tmp(monkeypatch, tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    counter = {"n": 0}

    def _mkdtemp(prefix=""):
        counter["n"] += 1
        path = staging / f"{prefix.strip('_') or 'tmp'}{counter['n']}"
        path.mkdir()
        return str(path)

    monkeypatch.setattr(import_data.tempfile, "mkdtemp", _mkdtemp)
    return staging


@pytest.mark.asyncio
async def test_zip_job_endpoint_returns_202_and_persists_pending(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    scheduled = _patch_schedule(monkeypatch)
    _stage_under_tmp(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())
    monkeypatch.setattr(db, "refresh", AsyncMock(), raising=False)

    archive = _zip_bytes({"scene_a/lidar/0000.pcd": b"x"})
    job = await import_data.start_zip_import_job(
        current_user=_mock_user(),
        dataset_id=str(db._dataset.id),
        file=FakeUploadFile("data.zip", archive),
        db=db,
    )

    assert job.status == "pending"
    assert job.job_type == "zip"
    assert job.source_filename == "data.zip"
    assert scheduled == [job.id]
    assert (Path(job.staged_path) / "upload.zip").exists()


@pytest.mark.asyncio
async def test_zip_job_rejects_non_zip_extension(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    _patch_schedule(monkeypatch)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await import_data.start_zip_import_job(
            current_user=_mock_user(),
            dataset_id=str(db._dataset.id),
            file=FakeUploadFile("data.tar", b"x"),
            db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_zip_job_rejects_bad_magic_and_cleans_staging(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    staging = _stage_under_tmp(monkeypatch, tmp_path)
    _patch_schedule(monkeypatch)
    db = FakeSession(dataset=_mock_dataset())

    with pytest.raises(HTTPException) as exc:
        await import_data.start_zip_import_job(
            current_user=_mock_user(),
            dataset_id=str(db._dataset.id),
            file=FakeUploadFile("data.zip", b"not a zip"),
            db=db,
        )
    assert exc.value.status_code == 400
    assert not any(staging.iterdir())


@pytest.mark.asyncio
async def test_folder_job_endpoint_stages_files(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    scheduled = _patch_schedule(monkeypatch)
    _stage_under_tmp(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())
    monkeypatch.setattr(db, "refresh", AsyncMock(), raising=False)

    job = await import_data.start_folder_import_job(
        current_user=_mock_user(),
        dataset_id=str(db._dataset.id),
        files=[
            FakeUploadFile("batch/a.jpg", JPG_BYTES),
            FakeUploadFile("batch/b.jpg", JPG_BYTES),
        ],
        db=db,
    )

    assert job.status == "pending"
    assert job.job_type == "upload"
    assert scheduled == [job.id]
    staged = Path(job.staged_path)
    assert (staged / "batch" / "a.jpg").exists()
    assert (staged / "batch" / "b.jpg").exists()


@pytest.mark.asyncio
async def test_runner_marks_completed_and_cleans_staging(tmp_path, monkeypatch):
    job = ImportJob(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        job_type="zip",
        status="pending",
        staged_path=str(tmp_path / "staged"),
        options={},
    )
    (tmp_path / "staged").mkdir()
    with zipfile.ZipFile(tmp_path / "staged" / "upload.zip", "w") as archive:
        archive.writestr("scene_a/lidar/0000.pcd", b"x")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", _JobStore(job), raising=False
    )
    monkeypatch.setattr(
        import_jobs, "_entity_exists", AsyncMock(return_value=True)
    )

    async def _fake_execute(*_args, **_kwargs):
        return ImportResponse(
            success=True,
            message="Imported 1 scenes with 2 frames from ZIP",
            scenes_imported=1,
            frames_imported=2,
        )

    monkeypatch.setattr(import_jobs, "execute_directory_import", _fake_execute)

    await import_jobs._run_import_job(job.id)

    assert job.status == "completed"
    assert job.phase == "completed"
    assert job.progress == 100
    assert job.scenes_imported == 1
    assert job.frames_imported == 2
    assert job.result["success"] is True
    assert job.finished_at is not None
    assert not (tmp_path / "staged").exists()


@pytest.mark.asyncio
async def test_runner_marks_failed_on_exception(tmp_path, monkeypatch):
    job = ImportJob(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        job_type="upload",
        status="pending",
        staged_path=str(tmp_path / "staged2"),
        options={},
    )
    (tmp_path / "staged2").mkdir()
    monkeypatch.setattr(
        "app.core.database.async_session_factory", _JobStore(job), raising=False
    )
    monkeypatch.setattr(
        import_jobs, "_entity_exists", AsyncMock(return_value=True)
    )

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(import_jobs, "execute_directory_import", _boom)

    await import_jobs._run_import_job(job.id)

    assert job.status == "failed"
    assert "disk on fire" in job.error
    assert job.finished_at is not None
    assert not (tmp_path / "staged2").exists()


@pytest.mark.asyncio
async def test_video_job_endpoint_returns_202_and_persists_pending(tmp_path, monkeypatch):
    _patch_pipeline_deps(monkeypatch, tmp_path)
    scheduled = _patch_schedule(monkeypatch)
    _stage_under_tmp(monkeypatch, tmp_path)
    db = FakeSession(dataset=_mock_dataset())
    monkeypatch.setattr(db, "refresh", AsyncMock(), raising=False)
    from tests.test_import_pipelines import _patch_video_service
    _patch_video_service(monkeypatch)

    res = await import_data.start_video_import_job(
        current_user=_mock_user(),
        dataset_id=str(uuid.uuid4()),
        file=FakeUploadFile("test.mp4", b"dummy video bytes"),
        extraction_fps=10.0,
        max_frames=100,
        image_format="jpg",
        preserve_folder_names=True,
        db=db,
    )

    assert isinstance(res, ImportJob)
    assert res.job_type == "video"
    assert res.status == "pending"
    assert res.source_filename == "test.mp4"
    assert res.options["extraction_fps"] == 10.0
    assert res.options["max_frames"] == 100
    assert scheduled == [res.id]


@pytest.mark.asyncio
async def test_runner_runs_video_import_job(tmp_path, monkeypatch):
    staged = tmp_path / "staged_video"
    staged.mkdir()
    (staged / "clip.mp4").write_bytes(b"dummy video")

    job = ImportJob(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        job_type="video",
        status="pending",
        source_filename="clip.mp4",
        staged_path=str(staged),
        options={"extraction_fps": 15.0},
    )
    monkeypatch.setattr(
        "app.core.database.async_session_factory", _JobStore(job), raising=False
    )
    monkeypatch.setattr(
        import_jobs, "_entity_exists", AsyncMock(return_value=True)
    )

    fake_resp = ImportResponse(
        success=True,
        message="Imported video as scene 'clip' with 5 frames",
        scenes_imported=1,
        frames_imported=5,
    )
    mock_execute = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(import_jobs, "execute_video_import", mock_execute)

    await import_jobs._run_import_job(job.id)

    assert job.status == "completed"
    assert job.phase == "completed"
    assert job.progress == 100
    assert job.scenes_imported == 1
    assert job.frames_imported == 5
    assert job.result["success"] is True
    assert mock_execute.awaited
    assert not staged.exists()
