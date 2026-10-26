"""Track-level refinement flags for 3D cuboids.

A track is either "Human-refined" (an annotator explicitly reviewed it) or
"AI-only". The state lives in ``tracks_3d`` — a sparse table keyed by
track_id — so toggling it never rewrites ``annotations_3d``.
"""
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Annotation3D, Permission, Track3DRefinement, User
from app.schemas.schemas import (
    Track3DRefinementResponse,
    Track3DRefinementUpdate,
)
from app.services.rbac_service import RequirePermissions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks-3d")


async def _resolve_task_id(db: AsyncSession, track_id: UUID) -> UUID:
    """Resolve the owning task of a track from its annotations."""
    result = await db.execute(
        select(Annotation3D.task_id)
        .where(Annotation3D.track_id == track_id)
        .limit(1)
    )
    task_id = result.scalar_one_or_none()
    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track has no annotations",
        )
    return task_id


@router.get("", response_model=list[Track3DRefinementResponse])
async def list_track_refinements(
    task_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_READ))],
    db: AsyncSession = Depends(get_db),
):
    """List explicitly-set refinement states for a task.

    Tracks without a row are AI-only and are not returned; clients treat a
    missing entry as ``is_refined = false``.
    """
    result = await db.execute(
        select(Track3DRefinement).where(Track3DRefinement.task_id == task_id)
    )
    return list(result.scalars().all())


@router.put("/{track_id}", response_model=Track3DRefinementResponse)
async def set_track_refinement(
    track_id: UUID,
    payload: Track3DRefinementUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_UPDATE))],
    db: AsyncSession = Depends(get_db),
):
    """Mark a single track as Human-refined, or revert it to AI-only."""
    task_id = await _resolve_task_id(db, track_id)

    stmt = (
        pg_insert(Track3DRefinement)
        .values(
            track_id=track_id,
            task_id=task_id,
            is_refined=payload.is_refined,
            refined_by=current_user.id,
            refined_at=func.now() if payload.is_refined else None,
        )
        .on_conflict_do_update(
            index_elements=[Track3DRefinement.track_id],
            set_={
                "is_refined": payload.is_refined,
                "refined_by": current_user.id,
                "refined_at": func.now() if payload.is_refined else None,
                "updated_at": func.now(),
            },
        )
        .returning(Track3DRefinement)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.commit()
    await db.refresh(row)

    logger.info(
        "[tracks_3d] user=%s track=%s is_refined=%s",
        current_user.username,
        track_id,
        payload.is_refined,
    )
    return row
