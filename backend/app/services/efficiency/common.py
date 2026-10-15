"""Shared helpers for the efficiency domain: identities and daily rollups."""
import uuid as uuid_lib
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import DailyUserStats, Organization, User


def generate_alias(user_id: UUID, seed: int = 0) -> str:
    """Generate consistent anonymous alias for a user."""
    user_bytes = user_id.bytes[:4]
    index = int.from_bytes(user_bytes, "big") % 100
    return f"Annotator {index + 1}"


async def get_display_name(
    db: AsyncSession,
    user: User,
    requesting_user: User,
    organization_id: Optional[UUID] = None,
) -> str:
    """Get display name based on organization settings."""
    if user.id == requesting_user.id:
        return user.full_name or user.username

    if organization_id:
        result = await db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        org = result.scalar_one_or_none()
        if org and org.settings:
            display_real_names = org.settings.get("display_real_names", True)
            if not display_real_names:
                return generate_alias(user.id)

    return user.full_name or user.username


async def update_daily_stats(
    db: AsyncSession,
    user_id: UUID,
    labels_created: int = 0,
    labels_updated: int = 0,
    labels_deleted: int = 0,
    active_time_seconds: int = 0,
    idle_time_seconds: int = 0,
) -> None:
    """Update or create daily stats for a user."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(DailyUserStats).where(
            and_(
                DailyUserStats.user_id == user_id,
                DailyUserStats.stats_date == today,
            )
        )
    )
    stats = result.scalar_one_or_none()

    if stats:
        stats.labels_created += labels_created
        stats.labels_updated += labels_updated
        stats.labels_deleted += labels_deleted
        stats.total_active_time += active_time_seconds
        stats.total_idle_time += idle_time_seconds
        stats.updated_at = datetime.utcnow()
    else:
        stats = DailyUserStats(
            id=uuid_lib.uuid4(),
            user_id=user_id,
            stats_date=today,
            labels_created=labels_created,
            labels_updated=labels_updated,
            labels_deleted=labels_deleted,
            total_active_time=active_time_seconds,
            total_idle_time=idle_time_seconds,
            total_session_count=1 if active_time_seconds > 0 else 0,
        )
        db.add(stats)
