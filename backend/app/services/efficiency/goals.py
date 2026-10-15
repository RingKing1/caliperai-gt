"""Personal goals with live progress from annotation counts."""
import uuid as uuid_lib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, and_, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Task,
    User,
    UserGoal,
)
from app.services.efficiency.errors import EfficiencyNotFoundError
from app.services.efficiency.schemas import (
    UserGoalCreate,
    UserGoalResponse,
)

LABEL_GOAL_TYPES = {"daily_labels", "weekly_labels", "monthly_labels"}
_AUTO_SOURCES_GOAL = (
    "auto",
    "airflow_model_v1",
    "airflow_model_v2",
    "auto_interpolated",
    "imported",
)


async def count_labels_in_period(
    db: AsyncSession,
    user_id: UUID,
    period_start: datetime,
    period_end: datetime,
) -> int:
    """Count human-created annotations for a user within a time window."""
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    total = 0
    for model in [
        Annotation,
        Annotation3D,
        Annotation2D,
        Annotation4D,
        AnnotationFusion,
    ]:
        result = await db.execute(
            select(func.count(model.id))
            .join(Task, model.task_id == Task.id)
            .where(
                and_(
                    Task.assignee_id == user_id,
                    model.created_at >= period_start,
                    model.created_at < period_end,
                    cast(model.source, String).notin_(_AUTO_SOURCES_GOAL),
                )
            )
        )
        total += result.scalar() or 0
    return total


def _progress_percentage(current_value: float, target_value: float) -> float:
    if target_value > 0:
        return min((current_value / target_value) * 100, 100)
    return 0


async def list_my_goals(
    db: AsyncSession,
    current_user: User,
    include_completed: bool = False,
) -> list[UserGoalResponse]:
    """Current user's goals with live progress from annotation counts."""
    now = datetime.utcnow()

    query = select(UserGoal).where(UserGoal.user_id == current_user.id)
    if not include_completed:
        query = query.where(UserGoal.period_end >= now)
    query = query.order_by(desc(UserGoal.period_start))

    result = await db.execute(query)
    goals = result.scalars().all()

    responses = []
    for goal in goals:
        if goal.goal_type in LABEL_GOAL_TYPES:
            current_value = float(
                await count_labels_in_period(
                    db, current_user.id, goal.period_start, goal.period_end
                )
            )
            if current_value != goal.current_value:
                goal.current_value = current_value
                if current_value >= goal.target_value and not goal.is_achieved:
                    goal.is_achieved = True
                    goal.achieved_at = now
        else:
            current_value = goal.current_value

        responses.append(
            UserGoalResponse(
                id=goal.id,
                goal_type=goal.goal_type,
                target_value=goal.target_value,
                current_value=current_value,
                period_start=goal.period_start,
                period_end=goal.period_end,
                is_achieved=goal.is_achieved,
                achieved_at=goal.achieved_at,
                progress_percentage=_progress_percentage(
                    current_value, goal.target_value
                ),
                is_self_assigned=goal.is_self_assigned,
            )
        )

    await db.commit()
    return responses


async def create_goal(
    db: AsyncSession, goal: UserGoalCreate, current_user: User
) -> UserGoalResponse:
    """Create a new personal goal."""
    new_goal = UserGoal(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        goal_type=goal.goal_type,
        target_value=goal.target_value,
        period_start=goal.period_start,
        period_end=goal.period_end,
        is_self_assigned=True,
    )
    db.add(new_goal)
    await db.commit()

    return UserGoalResponse(
        id=new_goal.id,
        goal_type=new_goal.goal_type,
        target_value=new_goal.target_value,
        current_value=new_goal.current_value,
        period_start=new_goal.period_start,
        period_end=new_goal.period_end,
        is_achieved=new_goal.is_achieved,
        achieved_at=new_goal.achieved_at,
        progress_percentage=0,
        is_self_assigned=True,
    )


async def update_goal(
    db: AsyncSession,
    goal_id: UUID,
    goal: UserGoalCreate,
    current_user: User,
) -> UserGoalResponse:
    """Update a personal goal."""
    result = await db.execute(
        select(UserGoal).where(
            and_(
                UserGoal.id == goal_id,
                UserGoal.user_id == current_user.id,
            )
        )
    )
    existing_goal = result.scalar_one_or_none()

    if not existing_goal:
        raise EfficiencyNotFoundError("Goal not found")

    existing_goal.goal_type = goal.goal_type
    existing_goal.target_value = goal.target_value
    existing_goal.period_start = goal.period_start
    existing_goal.period_end = goal.period_end

    await db.commit()
    await db.refresh(existing_goal)

    return UserGoalResponse(
        id=existing_goal.id,
        goal_type=existing_goal.goal_type,
        target_value=existing_goal.target_value,
        current_value=existing_goal.current_value,
        period_start=existing_goal.period_start,
        period_end=existing_goal.period_end,
        is_achieved=existing_goal.is_achieved,
        achieved_at=existing_goal.achieved_at,
        progress_percentage=_progress_percentage(
            existing_goal.current_value, existing_goal.target_value
        ),
        is_self_assigned=existing_goal.is_self_assigned,
    )


async def delete_goal(
    db: AsyncSession, goal_id: UUID, current_user: User
) -> dict:
    """Delete a personal goal."""
    result = await db.execute(
        select(UserGoal).where(
            and_(
                UserGoal.id == goal_id,
                UserGoal.user_id == current_user.id,
            )
        )
    )
    goal = result.scalar_one_or_none()

    if not goal:
        raise EfficiencyNotFoundError("Goal not found")

    await db.delete(goal)
    await db.commit()

    return {"status": "deleted"}
