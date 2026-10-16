"""Shared import core for the synchronous and background-job entry points.

``execute_directory_import`` contains everything that happens after the
uploaded bytes have been staged on disk: optional top-level wrapper descent,
dataset-level calibration, scene discovery, optional taxonomy derivation,
per-scene orchestration and the final commit. Both the legacy synchronous
endpoints and the background import jobs call it, so their behaviour stays
identical apart from *when* the HTTP response is returned.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Dataset, User
from app.services.dataset_import.calibration import parse_calibration_file
from app.services.dataset_import.pipeline_layout import detect_scene_dirs
from app.services.dataset_import.scene_pipeline import (
    PipelineSpec,
    SceneImportRequest,
    import_one_scene,
)
from app.services.dataset_import.schemas import ImportResponse
from app.services.dataset_import.taxonomy import (
    derive_and_merge_taxonomy,
    scan_annotations_for_classes,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, str], Awaitable[None]]


def descend_to_bundle_root(root_path: Path, spec: PipelineSpec) -> Path:
    """Skip a single wrapping folder (browser/ZIP export convention)."""
    subdirs = [
        d
        for d in root_path.iterdir()
        if d.is_dir()
        and (
            not spec.ignore_hidden_top_level
            or (not d.name.startswith(".") and d.name != "__MACOSX")
        )
    ]
    if len(subdirs) == 1 and not (root_path / "metadata.json").exists():
        return subdirs[0]
    return root_path


async def execute_directory_import(
    db: AsyncSession,
    *,
    root_path: Path,
    dataset: Dataset,
    user: User,
    spec: PipelineSpec,
    dataset_upload_dir: Path,
    overwrite_annotations: bool,
    preserve_folder_names: bool,
    derive_taxonomy: bool,
    name_overrides: dict[str, str] | None = None,
    scene_descriptions: dict[str, str] | None = None,
    progress: ProgressCallback | None = None,
) -> ImportResponse:
    """Run scene discovery/import on an already-staged directory."""

    async def report(phase: str, percent: int, message: str = "") -> None:
        if progress is not None:
            await progress(phase, percent, message)

    root_path = descend_to_bundle_root(root_path, spec)

    scenes_imported = 0
    frames_imported = 0
    errors: list[str] = []
    renamed_scenes = []

    await report("discovering", 5, f"Scanning {root_path.name}")
    calibration_data = {}
    calibration_path = root_path / "calibration"
    if calibration_path.exists():
        calibration_data = parse_calibration_file(calibration_path)

    scene_dirs, scene_parent_names = detect_scene_dirs(
        root_path, debug=spec.detect_debug
    )
    logger.info(
        "%s Scene directories to import: %s",
        spec.log_prefix,
        [d.name for d in scene_dirs],
    )

    await report(
        "discovering",
        10,
        f"Found {len(scene_dirs)} scene(s)",
    )

    if derive_taxonomy and scene_dirs:
        await report("taxonomy", 12, "Deriving taxonomy from annotations")
        logger.info(
            "%s derive_taxonomy=True, scanning annotations for classes...",
            spec.log_prefix,
        )
        discovered_classes = scan_annotations_for_classes(scene_dirs)
        if discovered_classes:
            taxonomy = await derive_and_merge_taxonomy(
                db=db,
                dataset=dataset,
                discovered_classes=discovered_classes,
                user_id=user.id,
            )
            if taxonomy:
                errors.append(
                    f"Taxonomy: Created/updated '{taxonomy.name}' with "
                    f"{len(taxonomy.classes)} classes"
                )
        else:
            errors.append("Taxonomy: No annotation classes found to derive")

    total = len(scene_dirs)
    for scene_index, scene_dir in enumerate(scene_dirs, start=1):
        await report(
            "importing",
            12 + int(78 * (scene_index - 1) / total) if total else 90,
            f"Importing scene {scene_index}/{total}: {scene_dir.name}",
        )
        frame_count = await import_one_scene(
            db=db,
            spec=spec,
            request=SceneImportRequest(
                dataset=dataset,
                user=user,
                dataset_upload_dir=dataset_upload_dir,
                overwrite_annotations=overwrite_annotations,
                preserve_folder_names=preserve_folder_names,
                name_overrides=name_overrides or {},
                scene_descriptions=scene_descriptions or {},
                dataset_calibration=calibration_data,
            ),
            scene_index=scene_index,
            scene_dir=scene_dir,
            parent_folder_name=scene_parent_names.get(
                scene_dir, scene_dir.name
            ),
            errors=errors,
            renamed_scenes=renamed_scenes,
        )
        if frame_count is not None:
            scenes_imported += 1
            frames_imported += frame_count
        await report(
            "importing",
            12 + int(78 * scene_index / total) if total else 90,
            f"Imported {scenes_imported}/{total} scene(s)",
        )

    await report("committing", 95, "Saving to database")
    await db.commit()
    await report("completed", 100, "Done")

    suffix = " from ZIP" if spec.name == "zip" else ""
    return ImportResponse(
        success=scenes_imported > 0,
        message=(
            f"Imported {scenes_imported} scenes with "
            f"{frames_imported} frames{suffix}"
        ),
        scenes_imported=scenes_imported,
        frames_imported=frames_imported,
        errors=errors,
        renamed_scenes=renamed_scenes,
    )
