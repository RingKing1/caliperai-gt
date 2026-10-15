"""Scene domain service: CRUD, label-filter parsing and frame image lookup.

Extracted from ``app/api/v1/endpoints/scenes.py`` so endpoints stay thin
(auth + HTTP mapping). Search ranking/aggregation itself remains in the
dedicated ``scene_*_search_service`` modules; this service only parses
HTTP query params into their filters and shapes responses.

Functions raise plain domain exceptions instead of ``HTTPException``; the
endpoints translate them.
"""
import re
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Dataset, Frame, Scene
from app.schemas.schemas import SceneCreate, SceneSearchResponse, SceneUpdate
from app.services.dataset_service import auto_create_tasks_for_scene
from app.services.scene_hybrid_search_service import search_scenes_hybrid
from app.services.scene_search_service import (
    CLASS_GROUPS,
    SceneSearchFilters,
    normalize_class_name,
    resolve_term,
    search_scenes,
)
from app.services.scene_semantic_search_service import (
    embedding_coverage,
    search_scenes_semantic,
)

# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class SceneServiceError(Exception):
    """Base class for scene-domain errors."""


class SceneNotFoundError(SceneServiceError):
    def __init__(self, scene_id: Any):
        self.scene_id = scene_id
        super().__init__(f"Scene {scene_id} not found")


class SceneConflictError(SceneServiceError):
    pass


class SceneValidationError(SceneServiceError):
    """Carries the structured ``detail`` payload expected by the API."""

    def __init__(self, detail: Any):
        self.detail = detail
        super().__init__(str(detail))


class FrameNotFoundError(SceneServiceError):
    def __init__(self, frame_index: int, scene_id: Any):
        self.frame_index = frame_index
        self.scene_id = scene_id
        super().__init__(f"Frame {frame_index} not found in scene {scene_id}")


class FrameImageNotFoundError(SceneServiceError):
    def __init__(self, camera: str, frame_index: int):
        self.camera = camera
        self.frame_index = frame_index
        super().__init__(f"No {camera} image for frame {frame_index}")


# ---------------------------------------------------------------------------
# Pure rules: query parsing
# ---------------------------------------------------------------------------


def split_filter_values(values: list[str] | None) -> list[str]:
    result = []
    for value in values or []:
        for item in value.split(","):
            item = item.strip()
            if item:
                result.append(item)
    return result


def parse_label_filters(
    q: Optional[str],
    classes: list[str],
    groups: list[str],
) -> tuple[list[str], list[str]]:
    """Resolve free-text/group/class params into (classes, canonical groups)."""
    requested_classes: list[str] = []
    normalized_groups: list[str] = []
    invalid_groups: list[str] = []

    for value in split_filter_values(classes):
        class_name = normalize_class_name(value)
        if class_name and class_name not in requested_classes:
            requested_classes.append(class_name)

    for value in split_filter_values(groups):
        kind, name = resolve_term(value)
        if kind == "group":
            if name not in normalized_groups:
                normalized_groups.append(name)
        else:
            invalid_groups.append(value)

    if invalid_groups:
        raise SceneValidationError(
            {
                "error": "unknown_class_group",
                "invalid_groups": invalid_groups,
                "valid_groups": sorted(CLASS_GROUPS),
            }
        )

    if q:
        for raw_value in split_filter_values([q]):
            kind, name = resolve_term(raw_value)
            if kind == "group":
                if name not in normalized_groups:
                    normalized_groups.append(name)
            elif name not in requested_classes:
                requested_classes.append(name)
    return requested_classes, normalized_groups


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------


async def search_by_labels(
    db: AsyncSession,
    *,
    q: Optional[str],
    classes: list[str],
    groups: list[str],
    dataset_id: Optional[UUID],
    name_contains: Optional[str],
    min_objects: int,
    min_class_ratio: float,
    min_group_ratio: float,
    min_group_frame_ratio: float,
    page: int,
    page_size: int,
) -> SceneSearchResponse:
    """Search scenes by imported label statistics (class presence/count/ratio)."""
    requested_classes, normalized_groups = parse_label_filters(q, classes, groups)
    limit = page_size
    offset = (page - 1) * page_size
    filters = SceneSearchFilters(
        dataset_id=dataset_id,
        classes=requested_classes,
        groups=normalized_groups,
        name_contains=name_contains,
        min_objects=min_objects,
        min_class_ratio=min_class_ratio,
        min_group_ratio=min_group_ratio,
        min_group_frame_ratio=min_group_frame_ratio,
        limit=limit,
        offset=0,
    )

    # The dataset is small enough to aggregate first; return total count and
    # apply pagination in Python so ratio sorting remains deterministic.
    all_results = await search_scenes(db, filters)
    page_results = all_results[offset : offset + limit]
    return SceneSearchResponse(
        query=q,
        classes=requested_classes,
        groups=normalized_groups,
        total=len(all_results),
        limit=limit,
        offset=offset,
        class_groups=CLASS_GROUPS,
        results=page_results,
    )


async def search_hybrid(
    db: AsyncSession,
    *,
    semantic_q: Optional[str],
    cameras: list[str],
    min_similarity: float,
    top_k_frames: int,
    candidate_pool: Optional[int],
    preview_frames: int,
    q: Optional[str],
    classes: list[str],
    groups: list[str],
    dataset_id: Optional[UUID],
    name_contains: Optional[str],
    min_objects: int,
    min_class_ratio: float,
    min_group_ratio: float,
    min_group_frame_ratio: float,
    page: int,
    page_size: int,
) -> dict:
    """Exact label filters first, then CLIP semantic ranking."""
    requested_classes, normalized_groups = parse_label_filters(q, classes, groups)
    filters = SceneSearchFilters(
        dataset_id=dataset_id,
        classes=requested_classes,
        groups=normalized_groups,
        name_contains=name_contains,
        min_objects=min_objects,
        min_class_ratio=min_class_ratio,
        min_group_ratio=min_group_ratio,
        min_group_frame_ratio=min_group_frame_ratio,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    semantic_query = semantic_q.strip() if semantic_q and semantic_q.strip() else None
    camera_list = split_filter_values(cameras) or None
    response = await search_scenes_hybrid(
        db,
        filters,
        semantic_query=semantic_query,
        cameras=camera_list,
        min_similarity=min_similarity,
        top_k_frames=top_k_frames,
        candidate_pool=candidate_pool,
        preview_frames=preview_frames,
    )
    response["classes"] = requested_classes
    response["groups"] = normalized_groups
    response["class_groups"] = CLASS_GROUPS
    response["limit"] = page_size
    response["offset"] = (page - 1) * page_size
    return response


async def search_semantic(
    db: AsyncSession,
    *,
    query_text: str,
    dataset_id: Optional[UUID],
    cameras: list[str],
    min_similarity: float,
    top_k_frames: int,
    candidate_pool: Optional[int],
    page_size: int,
) -> dict:
    """Semantic scene search over CLIP frame embeddings (Chinese-CLIP)."""
    camera_list = split_filter_values(cameras) or None
    return await search_scenes_semantic(
        db,
        query_text=query_text,
        dataset_id=dataset_id,
        cameras=camera_list,
        min_similarity=min_similarity,
        top_k_frames=top_k_frames,
        candidate_pool=candidate_pool,
        limit=page_size,
    )


async def get_embedding_coverage(db: AsyncSession) -> dict:
    """Per-scene CLIP frame-embedding coverage."""
    rows = await embedding_coverage(db)
    return {"total_scenes": len(rows), "results": rows}


# ---------------------------------------------------------------------------
# Frame image lookup
# ---------------------------------------------------------------------------


def resolve_frame_image_path(file_paths: dict, camera: str) -> Path | None:
    """Resolve a frame's on-disk camera image.

    Three on-disk layouts are produced by the import pipelines:

    * canonical: ``<scene>/cameras/<camera>/<file>`` (multi-camera, with or
      without a sibling ``lidar/`` directory);
    * images fallback: ``<scene>/images/<file>`` with a single ``images`` key;
    * flat fallback: ``<scene>/<file>`` with a single ``default`` (or folder
      named) key.

    Bundles use either canonical keys ("front") or raw keys
    ("camera_0_front100"); disk directories follow the same split, so try
    both the canonical and raw camera directory. Single-camera bundles serve
    their only stream regardless of the requested alias.
    """
    cameras = file_paths.get("cameras") or {}
    filename = cameras.get(camera)
    raw_key = camera
    if filename is None:
        for key, value in cameras.items():
            normalized = re.sub(
                r"[0-9]+$", "", re.sub(r"^camera_[0-9]+_", "", key)
            )
            if normalized == camera:
                filename = value
                raw_key = key
                break
    if filename is None and len(cameras) == 1:
        raw_key, filename = next(iter(cameras.items()))
    if not filename:
        return None
    meta = file_paths.get("_meta") or {}
    absolute_path = meta.get("absolute_path", "")
    if not absolute_path:
        return None
    primary = Path(absolute_path)
    if not primary.is_absolute():
        return None
    relative_path = meta.get("relative_path") or ""
    if relative_path:
        depth = len(Path(relative_path).parts) - 1
        if depth >= len(primary.parents):
            return None
        scene_dir = primary.parents[depth]
    else:
        # Legacy rows only recorded absolute paths; the primary used to be a
        # lidar file two levels below the scene directory.
        scene_dir = primary.parent.parent
    candidates = (
        scene_dir / "cameras" / camera / filename,
        scene_dir / "cameras" / raw_key / filename,
        scene_dir / "images" / filename,
        scene_dir / filename,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


async def get_frame_camera_image_path(
    db: AsyncSession, scene_id: UUID, frame_index: int, camera: str
) -> Path:
    """Resolve the disk path for a frame's camera image or raise 404 errors."""
    result = await db.execute(
        select(Frame.file_paths).where(
            Frame.scene_id == scene_id,
            Frame.frame_index == frame_index,
        )
    )
    file_paths = result.scalar_one_or_none()
    if file_paths is None:
        raise FrameNotFoundError(frame_index, scene_id)

    image_path = resolve_frame_image_path(file_paths, camera)
    if image_path is None:
        raise FrameImageNotFoundError(camera, frame_index)
    return image_path


# ---------------------------------------------------------------------------
# Scene CRUD
# ---------------------------------------------------------------------------


async def _get_active_scene(db: AsyncSession, scene_id: UUID, *, with_tasks: bool = False) -> Scene:
    query = select(Scene).where(
        Scene.id == scene_id,
        Scene.is_deleted == False,  # noqa: E712
    )
    if with_tasks:
        query = query.options(selectinload(Scene.tasks))
    result = await db.execute(query)
    scene = result.scalar_one_or_none()
    if not scene:
        raise SceneNotFoundError(scene_id)
    return scene


async def create_scene(db: AsyncSession, scene_in: SceneCreate) -> Scene:
    from app.services.dataset_service import DatasetNotFoundError

    result = await db.execute(
        select(Dataset).where(
            Dataset.id == scene_in.dataset_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    if not result.scalar_one_or_none():
        raise DatasetNotFoundError(scene_in.dataset_id)

    existing_result = await db.execute(
        select(Scene).where(
            Scene.dataset_id == scene_in.dataset_id,
            Scene.name == scene_in.name,
            Scene.is_deleted == False,  # noqa: E712
        )
    )
    if existing_result.scalar_one_or_none():
        raise SceneConflictError(
            f"A scene with the name '{scene_in.name}' already exists in this dataset"
        )

    scene = Scene(
        dataset_id=scene_in.dataset_id,
        name=scene_in.name,
        description=scene_in.description,
        scene_metadata=scene_in.scene_metadata.model_dump(),
        frame_count=scene_in.frame_count,
        fps=scene_in.fps,
        calibration=scene_in.calibration.model_dump(),
        storage_paths=scene_in.storage_paths.model_dump(),
    )
    db.add(scene)
    await db.flush()
    await auto_create_tasks_for_scene(db, scene)
    await db.flush()
    await db.refresh(scene)
    return scene


async def list_scenes(
    db: AsyncSession,
    dataset_id: Optional[UUID] = None,
    page: int = 1,
    page_size: int = 20,
) -> list[Scene]:
    query = (
        select(Scene)
        .where(Scene.is_deleted == False)  # noqa: E712
        .options(selectinload(Scene.tasks))
    )
    if dataset_id:
        query = query.where(Scene.dataset_id == dataset_id)
    query = query.order_by(Scene.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_scene(db: AsyncSession, scene_id: UUID) -> Scene:
    return await _get_active_scene(db, scene_id, with_tasks=True)


async def get_calibration(db: AsyncSession, scene_id: UUID) -> dict:
    result = await db.execute(
        select(Scene.calibration).where(
            Scene.id == scene_id,
            Scene.is_deleted == False,  # noqa: E712
        )
    )
    calibration = result.scalar_one_or_none()
    if calibration is None:
        raise SceneNotFoundError(scene_id)
    return calibration


async def update_scene(
    db: AsyncSession, scene_id: UUID, scene_in: SceneUpdate
) -> Scene:
    update_data = scene_in.model_dump(exclude_unset=True)
    scene = await _get_active_scene(db, scene_id, with_tasks=True)

    for field, value in update_data.items():
        if value is not None or field == "selected_taxonomy_id":
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(scene, field, value)

    await db.flush()

    result = await db.execute(
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.tasks))
    )
    return result.scalar_one()


async def soft_delete_scene(db: AsyncSession, scene_id: UUID) -> None:
    scene = await _get_active_scene(db, scene_id)
    scene.is_deleted = True
    await db.flush()
