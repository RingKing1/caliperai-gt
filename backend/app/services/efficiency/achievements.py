"""Achievements: display metadata and per-user read/seen state."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Achievement, AchievementType, User
from app.services.efficiency.errors import (
    EfficiencyForbiddenError,
    EfficiencyNotFoundError,
)
from app.services.efficiency.schemas import AchievementResponse

ACHIEVEMENT_INFO = {
    AchievementType.SPEED_DEMON.value: {
        "title": "Speed Demon",
        "description": "Complete 10 labels in under 30 minutes",
        "icon": "⚡"
    },
    AchievementType.LIGHTNING_FAST.value: {
        "title": "Lightning Fast",
        "description": "Top 10% speed for a week",
        "icon": "🏎️"
    },
    AchievementType.QUALITY_CHAMPION.value: {
        "title": "Quality Champion",
        "description": "Achieve 95%+ acceptance rate",
        "icon": "🏆"
    },
    AchievementType.PERFECTIONIST.value: {
        "title": "Perfectionist",
        "description": "10 tasks in a row without revision",
        "icon": "💎"
    },
    AchievementType.ZERO_DEFECT.value: {
        "title": "Zero Defect",
        "description": "50 first-time accepts",
        "icon": "✨"
    },
    AchievementType.CONSISTENCY_STAR.value: {
        "title": "Consistency Star",
        "description": "5-day streak of meeting goals",
        "icon": "⭐"
    },
    AchievementType.MARATHON_RUNNER.value: {
        "title": "Marathon Runner",
        "description": "10-day streak of activity",
        "icon": "🏃"
    },
    AchievementType.DEDICATED.value: {
        "title": "Dedicated",
        "description": "30-day active streak",
        "icon": "🎖️"
    },
    AchievementType.CENTURY_CLUB.value: {
        "title": "Century Club",
        "description": "100 labels in a day",
        "icon": "💯"
    },
    AchievementType.THOUSAND_LABELS.value: {
        "title": "Thousand Labels",
        "description": "1000 labels in a day",
        "icon": "🎯"
    },
    AchievementType.MILESTONE_5K.value: {
        "title": "5K Milestone",
        "description": "5000 labels in a day",
        "icon": "🌟"
    },
    AchievementType.ON_THE_RISE.value: {
        "title": "On the Rise",
        "description": "20% efficiency improvement",
        "icon": "📈"
    },
    AchievementType.COMEBACK_KID.value: {
        "title": "Comeback Kid",
        "description": "Recovered from low performance",
        "icon": "💪"
    },
}


def achievement_display(achievement_type: str) -> tuple[str, str, str]:
    """Resolve ``(title, description, icon)`` for an achievement type."""
    info = ACHIEVEMENT_INFO.get(achievement_type, {})
    title = info.get("title", achievement_type)
    description = info.get("description", "")
    icon = info.get("icon", "🏅")
    return title, description, icon


def _to_response(achievement: Achievement) -> AchievementResponse:
    title, description, icon = achievement_display(achievement.achievement_type)
    return AchievementResponse(
        id=achievement.id,
        achievement_type=achievement.achievement_type,
        earned_at=achievement.earned_at,
        metadata=achievement.achievement_metadata or {},
        is_seen=achievement.is_seen,
        title=title,
        description=description,
        icon=icon,
    )


async def list_my_achievements(
    db: AsyncSession, current_user: User
) -> list[AchievementResponse]:
    """Get current user's achievements."""
    result = await db.execute(
        select(Achievement)
        .where(Achievement.user_id == current_user.id)
        .order_by(desc(Achievement.earned_at))
    )
    achievements = result.scalars().all()
    return [_to_response(a) for a in achievements]


async def list_unseen_achievements(
    db: AsyncSession, current_user: User
) -> list[AchievementResponse]:
    """Get current user's unseen achievements for notification purposes."""
    result = await db.execute(
        select(Achievement)
        .where(
            and_(
                Achievement.user_id == current_user.id,
                Achievement.is_seen == False,  # noqa: E712
            )
        )
        .order_by(desc(Achievement.earned_at))
    )
    achievements = result.scalars().all()
    return [_to_response(a) for a in achievements]


async def mark_achievement_seen(
    db: AsyncSession, achievement_id: UUID, current_user: User
) -> dict:
    """Mark an achievement as seen."""
    achievement = await db.get(Achievement, achievement_id)
    if not achievement:
        raise EfficiencyNotFoundError("Achievement not found")
    if achievement.user_id != current_user.id:
        raise EfficiencyForbiddenError("Not your achievement")

    achievement.is_seen = True
    achievement.seen_at = datetime.utcnow()
    await db.commit()

    return {"status": "marked_seen"}
