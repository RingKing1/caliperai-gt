"""
Fusion Annotation endpoints - Combined 3D + 2D annotations.

These store annotations that combine 3D LiDAR cuboids with 2D camera projections.
Can be created directly or migrated from 3D annotations.
"""
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Annotation3D, AnnotationFusion, Permission, User
from app.schemas.schemas import (
    AnnotationFusionCreate,
    AnnotationFusionResponse,
    AnnotationFusionUpdate,
    BulkAnnotationFusionCreate,
    Migrate3DToFusionRequest,
    Migrate3DToFusionResponse,
)
from app.services.annotation_service import AnnotationService
from app.services.rbac_service import RequirePermissions

router = APIRouter(prefix="/annotations-fusion", tags=["annotations-fusion"])


@router.post("/", response_model=AnnotationFusionResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation_fusion(
    annotation: AnnotationFusionCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Create a new Fusion annotation. Requires ANNOTATIONS_CREATE permission."""
    service = AnnotationService(db)
    task = await service.get_task(annotation.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    frame = await service.get_frame(annotation.frame_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")

    await service.maybe_start_work(task, current_user.id)
    db_annotation = await service.create_fusion(annotation)

    return db_annotation


@router.get("", response_model=list[AnnotationFusionResponse])
async def list_annotations_fusion(
    task_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_READ))],
    frame_id: UUID | None = Query(None, description="Frame ID to filter by"),
    track_id: UUID | None = Query(None, description="Track ID to filter by"),
    db: AsyncSession = Depends(get_db),
):
    """List Fusion annotations for a task. Requires ANNOTATIONS_READ permission."""
    query = select(AnnotationFusion).where(AnnotationFusion.task_id == task_id)

    if frame_id:
        query = query.where(AnnotationFusion.frame_id == frame_id)
    if track_id:
        query = query.where(AnnotationFusion.track_id == track_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{annotation_id}", response_model=AnnotationFusionResponse)
async def get_annotation_fusion(
    annotation_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_READ))],
    db: AsyncSession = Depends(get_db),
):
    """Get a single Fusion annotation. Requires ANNOTATIONS_READ permission."""
    annotation = await db.get(AnnotationFusion, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Fusion Annotation not found")
    return annotation


@router.put("/{annotation_id}", response_model=AnnotationFusionResponse)
async def update_annotation_fusion(
    annotation_id: UUID,
    update: AnnotationFusionUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_UPDATE))],
    db: AsyncSession = Depends(get_db),
):
    """Update a Fusion annotation. Requires ANNOTATIONS_UPDATE permission."""
    updated = await AnnotationService(db).update_fusion(annotation_id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Fusion Annotation not found")

    return updated


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation_fusion(
    annotation_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_DELETE))],
    db: AsyncSession = Depends(get_db),
):
    """Delete a Fusion annotation. Requires ANNOTATIONS_DELETE permission."""
    annotation = await db.get(AnnotationFusion, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Fusion Annotation not found")

    await db.delete(annotation)
    await db.commit()


@router.post("/bulk", response_model=list[AnnotationFusionResponse], status_code=status.HTTP_201_CREATED)
async def create_annotations_fusion_bulk(
    bulk_in: BulkAnnotationFusionCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Bulk create Fusion annotations. Requires ANNOTATIONS_CREATE permission."""
    created = await AnnotationService(db).bulk_create_fusion(
        bulk_in.annotations, current_user.id
    )

    return created


@router.post("/migrate-from-3d", response_model=Migrate3DToFusionResponse)
async def migrate_3d_to_fusion(
    request: Migrate3DToFusionRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_UPDATE))],
    task_id: UUID = Query(..., description="Task ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Migrate 3D annotations to Fusion annotations. Requires ANNOTATIONS_UPDATE permission.

    For each 3D annotation:
    - Creates a Fusion annotation with the same UUID (preserving identity)
    - Copies 3D data to data_3d field
    - Initializes empty data_2d (to be populated in Fusion editor)
    - Marks the 3D annotation as migrated
    """
    query = select(Annotation3D).where(
        and_(
            Annotation3D.task_id == task_id,
            Annotation3D.is_migrated_to_fusion == False,
        )
    )

    if request.annotation_3d_ids:
        query = query.where(Annotation3D.id.in_(request.annotation_3d_ids))

    result = await db.execute(query)
    annotations_3d = result.scalars().all()

    created_annotation_ids = []
    errors = []
    migrated_count = 0

    for ann_3d in annotations_3d:
        try:
            fusion_id = ann_3d.id if request.preserve_uuids else uuid4()

            db_fusion = AnnotationFusion(
                id=fusion_id,
                task_id=ann_3d.task_id,
                frame_id=ann_3d.frame_id,
                track_id=ann_3d.track_id,
                type="cuboid_fusion",
                class_id=ann_3d.class_id,
                data_3d=ann_3d.data,
                data_2d={},
                attributes={
                    **ann_3d.attributes,
                    "migrated_from_3d": str(ann_3d.id),
                },
                source="migrated_from_3d",
                source_3d_annotation_id=ann_3d.id,
                is_verified=False,
            )

            db.add(db_fusion)
            created_annotation_ids.append(fusion_id)

            ann_3d.is_migrated_to_fusion = True
            ann_3d.migrated_at = datetime.utcnow()
            ann_3d.fusion_annotation_id = fusion_id
            migrated_count += 1

        except Exception as e:
            errors.append({
                "annotation_3d_id": str(ann_3d.id),
                "error": str(e)
            })

    await db.commit()

    return Migrate3DToFusionResponse(
        migrated_count=migrated_count,
        created_annotation_ids=created_annotation_ids,
        errors=errors,
    )


@router.get("/by-track/{track_id}", response_model=list[AnnotationFusionResponse])
async def get_annotations_fusion_by_track(
    track_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_READ))],
    db: AsyncSession = Depends(get_db),
):
    """Get all Fusion annotations for a track. Requires ANNOTATIONS_READ permission."""
    query = select(AnnotationFusion).where(AnnotationFusion.track_id == track_id)
    result = await db.execute(query)
    return result.scalars().all()
