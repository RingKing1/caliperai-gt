"""Video import pipeline.

Extracts frames from video files (MP4, AVI, MOV, MKV, WebM), generates a scene,
persists frame records, auto-creates tasks, and mirrors files to MinIO.
Supports both synchronous route execution and asynchronous background job execution.
"""
from __future__ import annotations

import logging
import shutil
import traceback
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_security import DATA_EXTENSIONS, rename_data_files_to_uuid
from app.models.models import Dataset, Frame, Scene, User
from app.services import video_service
from app.services.dataset_import.constants import (
    GENERIC_FOLDER_NAMES,
    UPLOAD_DIR,
)
from app.services.dataset_import.naming import generate_smart_scene_name
from app.services.dataset_import.schemas import ImportResponse
from app.services.dataset_import.storage import (
    schedule_scene_mirror,
)
from app.services.dataset_import.tasks import get_or_create_scene_import_task
from app.services.dataset_service import auto_create_tasks_for_scene

log = logging.getLogger(__name__)


async def execute_video_import(
    db: AsyncSession,
    *,
    dataset: Dataset,
    user: User,
    video_path: Path,
    original_filename: str,
    dataset_upload_dir: Path | None = None,
    extraction_fps: float | None = None,
    max_frames: int | None = None,
    image_format: str = "jpg",
    preserve_folder_names: bool = True,
    progress: Callable[[str, int, str], Awaitable[None]] | None = None,
) -> ImportResponse:
    """Import a video into a dataset as a scene with extracted frames and tasks."""
    async def report(phase: str, percent: int, msg: str) -> None:
        if progress is not None:
            await progress(phase, percent, msg)

    file_ext = Path(original_filename).suffix.lower()

    await report("validating", 10, "Validating video header and metadata")
    with open(video_path, "rb") as f:
        header = f.read(16)

    if not video_service.validate_video_magic_bytes(header, file_ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File content does not match expected {file_ext.upper()[1:]} format",
        )

    metadata = video_service.get_video_metadata(video_path)
    if not metadata or metadata.get("duration", 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read video metadata. The file may be corrupted.",
        )

    log.info("[VIDEO IMPORT] Video metadata: %s", metadata)

    video_name = Path(original_filename).stem
    if preserve_folder_names and video_name.lower() not in GENERIC_FOLDER_NAMES:
        scene_name = video_name
    else:
        scene_name = generate_smart_scene_name(video_name, 1)

    existing_scene_query = select(Scene).where(
        Scene.dataset_id == dataset.id,
        Scene.name == scene_name,
        Scene.is_deleted.is_(False),
    )
    existing_result = await db.execute(existing_scene_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A scene with the name '{scene_name}' already exists in this dataset",
        )

    upload_root = dataset_upload_dir or (UPLOAD_DIR / str(dataset.id))
    upload_root.mkdir(parents=True, exist_ok=True)

    scene_id = uuid.uuid4()
    permanent_scene_dir = upload_root / str(scene_id)
    frames_dir = permanent_scene_dir / "cameras" / "video"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        await report(
            "extracting", 25, f"Extracting frames at {extraction_fps or 'native'} FPS..."
        )
        log.info("[VIDEO IMPORT] Extracting frames at %s FPS...", extraction_fps or "native")
        frame_paths, extraction_metadata = await video_service.extract_frames_async(
            video_path=video_path,
            output_dir=frames_dir,
            fps=extraction_fps,
            max_frames=max_frames,
            image_format=image_format,
        )

        frame_count = len(frame_paths)
        log.info("[VIDEO IMPORT] Extracted %d frames", frame_count)

        if frame_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No frames could be extracted from the video",
            )

        await report("indexing", 70, f"Indexing {frame_count} frames and creating scene...")
        uuid_rename_map = rename_data_files_to_uuid(permanent_scene_dir, DATA_EXTENSIONS)

        org_id_val = (
            dataset.campaign.organization_id
            if getattr(dataset, "campaign", None) is not None
            else None
        )
        if org_id_val:
            schedule_scene_mirror(
                org_id_val, dataset.id, scene_id, permanent_scene_dir,
            )

        relative_path_base = f"uploads/{dataset.id}/{scene_id}"
        cameras_storage_paths = {"video": f"{relative_path_base}/cameras/video"}

        video_scene_metadata = {
            "source": "video_upload",
            "original_filename": original_filename,
            "video_duration": extraction_metadata.get("duration"),
            "video_fps": extraction_metadata.get("fps"),
            "video_resolution": [
                extraction_metadata.get("width"),
                extraction_metadata.get("height"),
            ],
            "video_codec": extraction_metadata.get("codec"),
            "extraction_fps": extraction_metadata.get("extraction_fps"),
            "frames_extracted": frame_count,
        }

        scene = Scene(
            id=scene_id,
            dataset_id=dataset.id,
            name=scene_name,
            description=f"Extracted from video: {original_filename}",
            frame_count=frame_count,
            fps=(
                extraction_metadata.get("extraction_fps")
                or extraction_metadata.get("fps")
                or 30.0
            ),
            scene_metadata=video_scene_metadata,
            calibration={},
            storage_paths={
                "root": str(permanent_scene_dir),
                "cameras": cameras_storage_paths,
            },
        )
        db.add(scene)
        await db.flush()
        await auto_create_tasks_for_scene(db, scene)
        await db.flush()

        permanent_frame_files = sorted(
            frames_dir.glob(f"*.{image_format}"), key=lambda x: x.name
        )
        timestamps = extraction_metadata.get("timestamps", [])

        for frame_idx, frame_file in enumerate(permanent_frame_files):
            frame_file_paths = {
                "cameras": {"video": frame_file.name},
                "_meta": {
                    "absolute_path": str(frame_file),
                    "relative_path": str(frame_file.relative_to(permanent_scene_dir)),
                    "original_filename": uuid_rename_map.get(
                        str(frame_file.relative_to(permanent_scene_dir)), {}
                    ).get("original_name") or frame_file.name,
                },
            }

            frame_timestamp = (
                timestamps[frame_idx]
                if frame_idx < len(timestamps)
                else frame_idx / scene.fps
            )

            frame = Frame(
                scene_id=scene.id,
                frame_index=frame_idx,
                timestamp=frame_timestamp,
                file_paths=frame_file_paths,
                ego_pose=None,
            )
            db.add(frame)

        await db.flush()

        task = await get_or_create_scene_import_task(
            db=db,
            scene=scene,
            assignee_id=user.id,
            frame_count=frame_count,
            description=f"Auto-created for video {original_filename} ({frame_count} frames)",
        )
        log.info("[VIDEO IMPORT] Using task: %s", task.name)

        await report("committing", 95, "Saving to database")
        await db.commit()
        await report("completed", 100, "Done")

        return ImportResponse(
            success=True,
            message=f"Imported video as scene '{scene_name}' with {frame_count} frames",
            scenes_imported=1,
            frames_imported=frame_count,
            errors=[
                (
                    f"Video: {extraction_metadata.get('width')}x"
                    f"{extraction_metadata.get('height')} @ "
                    f"{extraction_metadata.get('fps'):.1f} fps"
                ),
                (
                    f"Extracted {frame_count} frames at "
                    f"{extraction_metadata.get('extraction_fps'):.1f} fps"
                ),
            ],
        )

    except HTTPException:
        if permanent_scene_dir.exists():
            shutil.rmtree(permanent_scene_dir, ignore_errors=True)
        raise
    except IntegrityError:
        await db.rollback()
        if permanent_scene_dir.exists():
            shutil.rmtree(permanent_scene_dir, ignore_errors=True)
        log.warning(
            "[VIDEO IMPORT] Scene name '%s' already exists in dataset %s (duplicate or concurrent upload)",
            scene_name,
            dataset.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A scene named '{scene_name}' already exists in this dataset. "
                "It may have just been created by this same upload — refresh the "
                "dataset to check. To re-import, delete the existing scene or rename the file."
            ),
        )
    except Exception as e:
        await db.rollback()
        if permanent_scene_dir.exists():
            shutil.rmtree(permanent_scene_dir, ignore_errors=True)
        log.error("[VIDEO IMPORT ERROR] %s\n%s", str(e), traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video upload failed: {str(e)}",
        )
