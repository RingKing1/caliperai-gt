"""Mirroring imported scene files into per-org MinIO storage."""
import asyncio
import logging
import uuid
from pathlib import Path

from app.services.storage_service import get_storage_service

log = logging.getLogger(__name__)
def _mirror_scene_to_minio(
    org_id,
    dataset_id,
    scene_id: uuid.UUID,
    scene_dir: Path,
) -> None:
    """Upload every file in *scene_dir* to the org MinIO bucket (encrypted).

    Object key pattern: ``datasets/{dataset_id}/{scene_id}/{relative_path}``.
    Errors are logged but never raised — local storage remains the source of
    truth; MinIO is the encrypted mirror used for pre-signed URL serving.
    """
    try:
        svc = get_storage_service()
        svc.ensure_bucket(org_id)
        for file_path in scene_dir.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(scene_dir)
            object_key = f"datasets/{dataset_id}/{scene_id}/{rel.as_posix()}"
            try:
                svc.upload_file(org_id, object_key, file_path)
            except Exception as exc:  # noqa: BLE001
                log.warning("MinIO upload failed for %s: %s", object_key, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not mirror scene %s to MinIO: %s", scene_id, exc)


def schedule_scene_mirror(
    org_id,
    dataset_id,
    scene_id: uuid.UUID,
    scene_dir: Path,
) -> None:
    """Fire-and-forget the MinIO mirror on the default executor.

    Shared by the browser upload, ZIP upload and video upload routes so the
    scheduling policy (and its patch point for tests) lives in one place.
    The future is deliberately not awaited: local storage is the source of
    truth and the mirror itself swallows all errors.
    """
    asyncio.get_event_loop().run_in_executor(
        None, _mirror_scene_to_minio, org_id, dataset_id, scene_id, scene_dir
    )




