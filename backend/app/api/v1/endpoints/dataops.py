"""
DataOps API Endpoints

Provides endpoints for:
- Annotation version history
- Stage snapshots
- DataOps statistics
- Snapshot comparison
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Dataset, Scene, Task, User
from app.schemas.dataops import (
    AnnotationHistoryListResponse,
    AnnotationHistoryResponse,
    DatasetDataOpsStats,
    SnapshotCompareResponse,
    SnapshotDetailResponse,
    SnapshotListResponse,
    SnapshotSummaryResponse,
    TaskDataOpsStats,
)
from app.services.dataops_service import DataOpsService, get_dataops_service
from app.services.rbac_service import RequirePermissions, get_current_user

router = APIRouter(prefix="/dataops", tags=["dataops"])


@router.get("/tasks/{task_id}/history", response_model=AnnotationHistoryListResponse)
async def get_task_history(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    change_type: str | None = Query(None, description="Filter by change type: created, updated, deleted"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """Get annotation history for a specific task."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    dataops = get_dataops_service(db)

    history = await dataops.get_task_annotation_history(
        task_id=task_id,
        change_type=change_type,
        limit=limit,
        offset=offset,
    )

    total = await dataops.get_task_history_count(task_id, change_type)

    items = [
        AnnotationHistoryResponse(
            id=str(h.id),
            annotation_id=str(h.annotation_id),
            task_id=str(h.task_id),
            frame_id=str(h.frame_id),
            change_type=h.change_type,
            annotation_data=h.annotation_data,
            previous_data=h.previous_data,
            task_stage=h.task_stage,
            task_status=h.task_status,
            changed_by_id=str(h.changed_by_id) if h.changed_by_id else None,
            version=h.version,
            created_at=h.created_at.isoformat(),
        )
        for h in history
    ]

    return AnnotationHistoryListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{task_id}/snapshots", response_model=SnapshotListResponse)
async def get_task_snapshots(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
):
    """Get stage snapshots for a specific task."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    dataops = get_dataops_service(db)

    snapshots = await dataops.get_task_snapshots(task_id, limit, offset)
    total = await dataops.get_snapshot_count(task_id)

    items = [
        SnapshotSummaryResponse(
            id=str(s.id),
            task_id=str(s.task_id),
            from_stage=s.from_stage,
            to_stage=s.to_stage,
            from_status=s.from_status,
            to_status=s.to_status,
            snapshot_name=s.snapshot_name,
            total_annotations=s.total_annotations,
            annotations_by_class=s.annotations_by_class,
            annotations_by_type=s.annotations_by_type,
            triggered_by_id=str(s.triggered_by_id) if s.triggered_by_id else None,
            notes=s.notes,
            created_at=s.created_at.isoformat(),
        )
        for s in snapshots
    ]

    return SnapshotListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{task_id}/stats", response_model=TaskDataOpsStats)
async def get_task_stats(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get DataOps statistics for a specific task."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    dataops = get_dataops_service(db)
    stats = await dataops.get_task_dataops_stats(task_id)

    return TaskDataOpsStats(**stats)



@router.get("/datasets/{dataset_id}/history", response_model=AnnotationHistoryListResponse)
async def get_dataset_history(
    dataset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    change_type: str | None = Query(None, description="Filter by change type"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """Get annotation history for all tasks in a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataops = get_dataops_service(db)

    history = await dataops.get_dataset_history(
        dataset_id=dataset_id,
        change_type=change_type,
        limit=limit,
        offset=offset,
    )

    stats = await dataops.get_dataset_dataops_stats(dataset_id)

    items = [
        AnnotationHistoryResponse(
            id=str(h.id),
            annotation_id=str(h.annotation_id),
            task_id=str(h.task_id),
            frame_id=str(h.frame_id),
            change_type=h.change_type,
            annotation_data=h.annotation_data,
            previous_data=h.previous_data,
            task_stage=h.task_stage,
            task_status=h.task_status,
            changed_by_id=str(h.changed_by_id) if h.changed_by_id else None,
            version=h.version,
            created_at=h.created_at.isoformat(),
        )
        for h in history
    ]

    return AnnotationHistoryListResponse(
        items=items,
        total=stats["total_changes"],
        limit=limit,
        offset=offset,
    )


@router.get("/datasets/{dataset_id}/snapshots", response_model=SnapshotListResponse)
async def get_dataset_snapshots(
    dataset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    """Get all stage snapshots for tasks in a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataops = get_dataops_service(db)

    snapshots = await dataops.get_dataset_snapshots(dataset_id, limit, offset)
    stats = await dataops.get_dataset_dataops_stats(dataset_id)

    items = [
        SnapshotSummaryResponse(
            id=str(s.id),
            task_id=str(s.task_id),
            from_stage=s.from_stage,
            to_stage=s.to_stage,
            from_status=s.from_status,
            to_status=s.to_status,
            snapshot_name=s.snapshot_name,
            total_annotations=s.total_annotations,
            annotations_by_class=s.annotations_by_class,
            annotations_by_type=s.annotations_by_type,
            triggered_by_id=str(s.triggered_by_id) if s.triggered_by_id else None,
            notes=s.notes,
            created_at=s.created_at.isoformat(),
        )
        for s in snapshots
    ]

    return SnapshotListResponse(
        items=items,
        total=stats["total_snapshots"],
        limit=limit,
        offset=offset,
    )


@router.get("/datasets/{dataset_id}/stats", response_model=DatasetDataOpsStats)
async def get_dataset_stats(
    dataset_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get aggregated DataOps statistics for a dataset."""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataops = get_dataops_service(db)
    stats = await dataops.get_dataset_dataops_stats(dataset_id)

    return DatasetDataOpsStats(**stats)



@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetailResponse)
async def get_snapshot_detail(
    snapshot_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get full details of a specific snapshot including annotation data."""
    dataops = get_dataops_service(db)
    snapshot = await dataops.get_snapshot(snapshot_id)

    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return SnapshotDetailResponse(
        id=str(snapshot.id),
        task_id=str(snapshot.task_id),
        from_stage=snapshot.from_stage,
        to_stage=snapshot.to_stage,
        from_status=snapshot.from_status,
        to_status=snapshot.to_status,
        snapshot_name=snapshot.snapshot_name,
        total_annotations=snapshot.total_annotations,
        annotations_by_class=snapshot.annotations_by_class,
        annotations_by_type=snapshot.annotations_by_type,
        annotations_by_frame=snapshot.annotations_by_frame,
        annotations_snapshot=snapshot.annotations_snapshot,
        triggered_by_id=str(snapshot.triggered_by_id) if snapshot.triggered_by_id else None,
        notes=snapshot.notes,
        created_at=snapshot.created_at.isoformat(),
    )


@router.get("/snapshots/compare", response_model=SnapshotCompareResponse)
async def compare_snapshots(
    snapshot_id_1: uuid.UUID = Query(..., description="First snapshot ID"),
    snapshot_id_2: uuid.UUID = Query(..., description="Second snapshot ID"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Compare two snapshots and return the differences."""
    dataops = get_dataops_service(db)
    result = await dataops.compare_snapshots(snapshot_id_1, snapshot_id_2)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return SnapshotCompareResponse(**result)



@router.get("/annotations/{annotation_id}/history", response_model=list[AnnotationHistoryResponse])
async def get_annotation_version_history(
    annotation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
):
    """Get version history for a specific annotation."""
    dataops = get_dataops_service(db)
    history = await dataops.get_annotation_history(annotation_id, limit, offset)

    return [
        AnnotationHistoryResponse(
            id=str(h.id),
            annotation_id=str(h.annotation_id),
            task_id=str(h.task_id),
            frame_id=str(h.frame_id),
            change_type=h.change_type,
            annotation_data=h.annotation_data,
            previous_data=h.previous_data,
            task_stage=h.task_stage,
            task_status=h.task_status,
            changed_by_id=str(h.changed_by_id) if h.changed_by_id else None,
            version=h.version,
            created_at=h.created_at.isoformat(),
        )
        for h in history
    ]
