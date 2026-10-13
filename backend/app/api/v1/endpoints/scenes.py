"""
Scene endpoints with RBAC protection.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import Scene, Dataset, User, Permission
from app.api.v1.endpoints.datasets import auto_create_tasks_for_scene
from app.schemas.schemas import (
    SceneCreate,
    SceneUpdate,
    SceneResponse,
)
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
from app.services.rbac_service import (
    get_current_user,
    RequirePermissions,
)

router = APIRouter()


class SceneSearchResponse(BaseModel):
    """Structured scene search response."""

    query: Optional[str] = None
    classes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    class_groups: dict[str, list[str]]
    results: list[dict]


def _split_filter_values(values: list[str] | None) -> list[str]:
    result = []
    for value in values or []:
        for item in value.split(","):
            item = item.strip()
            if item:
                result.append(item)
    return result


@router.get("/search", response_model=SceneSearchResponse)
async def search_scenes_by_labels(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    q: Optional[str] = Query(
        None,
        description="Class or class group, e.g. car, motorcycle, bicycle, two_wheeler, vehicle, pedestrian",
    ),
    classes: list[str] = Query(default_factory=list, description="Required classes; repeat or comma-separate"),
    groups: list[str] = Query(default_factory=list, description="Required class groups; repeat or comma-separate"),
    dataset_id: Optional[UUID] = Query(None),
    name_contains: Optional[str] = Query(None),
    min_objects: int = Query(0, ge=0),
    min_class_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_frame_ratio: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> SceneSearchResponse:
    """Search scenes by imported label statistics (class presence/count/ratio)."""
    requested_classes: list[str] = []
    normalized_groups: list[str] = []
    invalid_groups: list[str] = []

    # Explicit ``classes`` are taxonomy class names; normalize but do not alias.
    for value in _split_filter_values(classes):
        class_name = normalize_class_name(value)
        if class_name and class_name not in requested_classes:
            requested_classes.append(class_name)

    # Explicit ``groups`` accept canonical group names and their aliases,
    # including member-class names (e.g. groups=motorcycle -> two_wheeler).
    for value in _split_filter_values(groups):
        kind, name = resolve_term(value)
        if kind == "group":
            if name not in normalized_groups:
                normalized_groups.append(name)
        else:
            invalid_groups.append(value)

    if invalid_groups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_class_group",
                "invalid_groups": invalid_groups,
                "valid_groups": sorted(CLASS_GROUPS),
            },
        )

    # Free-text query: each term resolves to either a concrete class or a group.
    if q:
        for raw_value in _split_filter_values([q]):
            kind, name = resolve_term(raw_value)
            if kind == "group":
                if name not in normalized_groups:
                    normalized_groups.append(name)
            elif name not in requested_classes:
                requested_classes.append(name)
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


@router.get("/search/semantic")
async def search_scenes_by_image_semantics(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    q: str = Query(..., min_length=1, description="Natural-language scene query, e.g. 二轮车场景, cars on highway"),
    dataset_id: Optional[UUID] = Query(None),
    cameras: list[str] = Query(default_factory=list, description="Filter cameras; repeat or comma-separate"),
    min_similarity: float = Query(0.18, ge=-1.0, le=1.0),
    top_k_frames: int = Query(200, ge=1, le=2000),
    candidate_pool: Optional[int] = Query(None, ge=100, le=100000, description="Limit ANN candidates; default scans all frames for accurate scene ranking"),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Semantic scene search over CLIP frame embeddings (Chinese-CLIP)."""
    camera_list = _split_filter_values(cameras) or None
    return await search_scenes_semantic(
        db,
        query_text=q,
        dataset_id=dataset_id,
        cameras=camera_list,
        min_similarity=min_similarity,
        top_k_frames=top_k_frames,
        candidate_pool=candidate_pool,
        limit=page_size,
    )


@router.get("/embeddings/coverage")
async def get_embedding_coverage(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-scene CLIP frame-embedding coverage."""
    rows = await embedding_coverage(db)
    return {"total_scenes": len(rows), "results": rows}


@router.post("", response_model=SceneResponse, status_code=status.HTTP_201_CREATED)
async def create_scene(
    scene_in: SceneCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Create a new scene with calibration matrices. Requires SCENES_CREATE permission."""
    dataset_query = select(Dataset).where(
        Dataset.id == scene_in.dataset_id,
        Dataset.is_deleted == False,
    )
    result = await db.execute(dataset_query)
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {scene_in.dataset_id} not found",
        )
    
    existing_scene_query = select(Scene).where(
        Scene.dataset_id == scene_in.dataset_id,
        Scene.name == scene_in.name,
        Scene.is_deleted == False,
    )
    existing_result = await db.execute(existing_scene_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A scene with the name '{scene_in.name}' already exists in this dataset",
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


@router.get("", response_model=list[SceneResponse])
async def list_scenes(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False))],
    dataset_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Scene]:
    """List scenes with optional dataset filter. Requires SCENES_READ permission."""
    query = select(Scene).where(Scene.is_deleted == False)
    query = query.options(selectinload(Scene.tasks))
    
    if dataset_id:
        query = query.where(Scene.dataset_id == dataset_id)
    
    query = query.order_by(Scene.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{scene_id}", response_model=SceneResponse)
async def get_scene(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Get a scene by ID. Requires SCENES_READ permission."""
    query = select(Scene).where(
        Scene.id == scene_id,
        Scene.is_deleted == False,
    )
    query = query.options(selectinload(Scene.tasks))
    result = await db.execute(query)
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    
    return scene


@router.get("/{scene_id}/calibration")
async def get_calibration(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get calibration matrices for a scene. Requires SCENES_READ permission."""
    query = select(Scene.calibration).where(
        Scene.id == scene_id,
        Scene.is_deleted == False,
    )
    result = await db.execute(query)
    calibration = result.scalar_one_or_none()
    
    if calibration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    
    return calibration


@router.patch("/{scene_id}", response_model=SceneResponse)
async def update_scene(
    scene_id: UUID,
    scene_in: SceneUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Update a scene. Requires SCENES_UPDATE permission."""
    query = select(Scene).where(
        Scene.id == scene_id,
        Scene.is_deleted == False,
    ).options(selectinload(Scene.tasks))
    result = await db.execute(query)
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    
    update_data = scene_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None or field == 'selected_taxonomy_id':
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(scene, field, value)
    
    await db.flush()
    
    query = select(Scene).where(Scene.id == scene_id).options(selectinload(Scene.tasks))
    result = await db.execute(query)
    scene = result.scalar_one()
    
    return scene


@router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_DELETE))],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a scene. Requires SCENES_DELETE permission (Admin only)."""
    query = select(Scene).where(
        Scene.id == scene_id,
        Scene.is_deleted == False,
    )
    result = await db.execute(query)
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found",
        )
    
    scene.is_deleted = True
    await db.flush()
