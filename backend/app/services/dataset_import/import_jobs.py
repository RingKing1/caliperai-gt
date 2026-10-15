"""Background import job lifecycle.

The receiving worker stages upload bytes into a temp directory, inserts a
``pending`` job and schedules the actual import as an ``asyncio`` task.
Status updates are written through a *separate* short-lived DB session so
polling sees progress while the import keeps its original single-commit
transaction semantics (partial scenes are never visible before commit).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Dataset, ImportJob, User
from app.services.dataset_import.constants import UPLOAD_DIR
from app.services.dataset_import.import_runner import execute_directory_import
from app.services.dataset_import.scene_pipeline import UPLOAD_PIPELINE, ZIP_PIPELINE

log = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def create_import_job(
    db: AsyncSession,
    *,
    dataset_id: str,
    user_id: UUID | None,
    job_type: str,
    source_filename: str | None,
    staged_path: str,
    options: dict[str, Any],
) -> ImportJob:
    job = ImportJob(
        dataset_id=UUID(str(dataset_id)),
        created_by=user_id,
        job_type=job_type,
        source_filename=source_filename,
        status="pending",
        phase="queued",
        progress=0,
        staged_path=staged_path,
        options=options,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def list_import_jobs(
    db: AsyncSession, *, dataset_id: str, limit: int = 50
) -> list[ImportJob]:
    result = await db.execute(
        select(ImportJob)
        .where(ImportJob.dataset_id == UUID(str(dataset_id)))
        .order_by(ImportJob.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def schedule_import_job(job_id: UUID) -> None:
    """Fire-and-forget the job on the current worker's event loop."""
    task = asyncio.create_task(_run_import_job(job_id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _set_job_fields(job_id: UUID, **fields: Any) -> None:
    """Commit a status update in its own transaction."""
    from app.core.database import async_session_factory

    async with async_session_factory() as status_db:
        job = await status_db.get(ImportJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        await status_db.commit()


async def _entity_exists(model, entity_id: UUID) -> bool:
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(select(model.id).where(model.id == entity_id))
        return result.scalar_one_or_none() is not None


async def _run_import_job(job_id: UUID) -> None:
    from app.core.database import async_session_factory
    from app.core.file_security import safe_zip_extract

    log.info("[IMPORT JOB] %s starting", job_id)
    staged_path: Path | None = None
    try:
        async with async_session_factory() as db:
            job = await db.get(ImportJob, job_id)
            if job is None:
                log.error("[IMPORT JOB] %s disappeared", job_id)
                return
            staged_path = Path(job.staged_path) if job.staged_path else None
            options = dict(job.options or {})
            dataset_id = job.dataset_id
            user_id = job.created_by
            job_type = job.job_type

        if not await _entity_exists(Dataset, dataset_id):
            await _set_job_fields(
                job_id, status="failed", phase="failed",
                error="Dataset no longer exists",
                finished_at=datetime.now(timezone.utc),
            )
            return
        if user_id is None or not await _entity_exists(User, user_id):
            await _set_job_fields(
                job_id, status="failed", phase="failed",
                error="Initiating user no longer exists",
                finished_at=datetime.now(timezone.utc),
            )
            return

        await _set_job_fields(
            job_id,
            status="running",
            phase="preparing",
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
        )

        if job_type == "zip":
            zip_path = staged_path / "upload.zip"
            extract_dir = staged_path / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            await _set_job_fields(job_id, phase="extracting", message="Extracting ZIP")
            try:
                with zipfile.ZipFile(zip_path, "r") as archive:
                    safe_zip_extract(archive, extract_dir)
            except zipfile.BadZipFile as exc:
                await _set_job_fields(
                    job_id, status="failed", phase="failed",
                    error=f"Invalid or corrupted ZIP file: {exc}",
                    finished_at=datetime.now(timezone.utc),
                )
                return
            bundle_root = extract_dir
            spec = ZIP_PIPELINE
        else:
            bundle_root = staged_path
            spec = UPLOAD_PIPELINE

        dataset_upload_dir = UPLOAD_DIR / str(dataset_id)
        dataset_upload_dir.mkdir(parents=True, exist_ok=True)

        async def progress(phase: str, percent: int, message: str) -> None:
            await _set_job_fields(
                job_id,
                phase=phase,
                progress=max(0, min(100, percent)),
                message=message[:2000] if message else None,
                heartbeat_at=datetime.now(timezone.utc),
            )

        async with async_session_factory() as import_db:
            dataset = (
                await import_db.execute(
                    select(Dataset)
                    .options(selectinload(Dataset.campaign))
                    .where(Dataset.id == dataset_id)
                )
            ).scalar_one()
            user = (
                await import_db.execute(select(User).where(User.id == user_id))
            ).scalar_one()

            response = await execute_directory_import(
                import_db,
                root_path=bundle_root,
                dataset=dataset,
                user=user,
                spec=spec,
                dataset_upload_dir=dataset_upload_dir,
                overwrite_annotations=bool(
                    options.get("overwrite_annotations", False)
                ),
                preserve_folder_names=bool(
                    options.get("preserve_folder_names", True)
                ),
                derive_taxonomy=bool(options.get("derive_taxonomy", False)),
                name_overrides=options.get("name_overrides") or {},
                scene_descriptions=options.get("scene_descriptions") or {},
                progress=progress,
            )

        await _set_job_fields(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            message=response.message,
            scenes_imported=response.scenes_imported,
            frames_imported=response.frames_imported,
            total_scenes=response.scenes_imported,
            processed_scenes=response.scenes_imported,
            result=response.model_dump(mode="json"),
            finished_at=datetime.now(timezone.utc),
        )
        log.info("[IMPORT JOB] %s completed: %s", job_id, response.message)
    except Exception as exc:  # noqa: BLE001 - job must record any failure
        log.exception("[IMPORT JOB] %s failed", job_id)
        await _set_job_fields(
            job_id,
            status="failed",
            phase="failed",
            error=str(exc)[:4000],
            finished_at=datetime.now(timezone.utc),
        )
    finally:
        if staged_path is not None:
            shutil.rmtree(staged_path, ignore_errors=True)
