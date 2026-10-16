"""Team challenges with live label-count progress."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, and_, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    OrganizationMember,
    Task,
    TeamChallenge,
    User,
)
from app.services.efficiency.common import get_display_name
from app.services.efficiency.errors import (
    EfficiencyForbiddenError,
    EfficiencyNotFoundError,
    EfficiencyValidationError,
)
from app.services.efficiency.schemas import (
    CreateChallengeRequest,
    LeaderboardEntry,
    TeamChallengeResponse,
)

CHALLENGE_LABEL_TYPES = {"total_labels", "daily_labels", "weekly_labels", "labels"}
_CHALLENGE_AUTO_SOURCES = (
    "auto",
    "airflow_model_v1",
    "airflow_model_v2",
    "auto_interpolated",
    "imported",
)


def _progress_percentage(current_value: float, target_value: float) -> float:
    if target_value > 0:
        return min((current_value / target_value) * 100, 100)
    return 0


async def compute_challenge_progress(
    db: AsyncSession,
    challenge: TeamChallenge,
    org_member_ids: list,
) -> dict[UUID, float]:
    """Count each org member's label contributions within the challenge period.

    Returns ``{user_id: label_count}``.
    """
    if challenge.goal_type not in CHALLENGE_LABEL_TYPES:
        return {}

    start = challenge.start_date
    end = challenge.end_date
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    user_counts: dict[UUID, float] = {}
    for model in [
        Annotation,
        Annotation3D,
        Annotation2D,
        Annotation4D,
        AnnotationFusion,
    ]:
        result = await db.execute(
            select(Task.assignee_id, func.count(model.id).label("cnt"))
            .join(Task, model.task_id == Task.id)
            .where(
                and_(
                    Task.assignee_id.in_(org_member_ids),
                    model.created_at >= start,
                    model.created_at < end,
                    cast(model.source, String).notin_(_CHALLENGE_AUTO_SOURCES),
                )
            )
            .group_by(Task.assignee_id)
        )
        for row in result.all():
            uid, cnt = row[0], row[1]
            user_counts[uid] = user_counts.get(uid, 0.0) + float(cnt)

    return user_counts


async def list_challenges(
    db: AsyncSession,
    current_user: User,
    organization_id: UUID | None = None,
    include_completed: bool = False,
) -> list[TeamChallengeResponse]:
    """Team challenges with live progress from annotation counts."""
    now = datetime.now(timezone.utc)

    query = select(TeamChallenge).options(
        selectinload(TeamChallenge.participants)
    )
    if organization_id:
        query = query.where(TeamChallenge.organization_id == organization_id)
    if not include_completed:
        query = query.where(TeamChallenge.is_active == True)  # noqa: E712
    query = query.order_by(desc(TeamChallenge.start_date))

    result = await db.execute(query)
    challenges = result.scalars().all()

    responses = []
    for challenge in challenges:
        members_result = await db.execute(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == challenge.organization_id
            )
        )
        org_member_ids = [row[0] for row in members_result.all()]

        user_counts = await compute_challenge_progress(
            db, challenge, org_member_ids
        )

        total = sum(user_counts.values())

        if total != challenge.current_value:
            challenge.current_value = total
            if total >= challenge.target_value and not challenge.is_completed:
                challenge.is_completed = True
                challenge.completed_at = now

        sorted_users = sorted(
            user_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]
        top_contributors = []
        for rank, (uid, cnt) in enumerate(sorted_users, 1):
            if cnt <= 0:
                continue
            user = await db.get(User, uid)
            if user:
                display_name = await get_display_name(
                    db, user, current_user, organization_id
                )
                top_contributors.append(
                    LeaderboardEntry(
                        rank=rank,
                        user_id=uid,
                        display_name=display_name,
                        labels_count=int(cnt),
                        acceptance_rate=0,
                        avg_time_per_label_seconds=0,
                        streak_days=0,
                    )
                )

        participant_count = sum(1 for c in user_counts.values() if c > 0)

        responses.append(
            TeamChallengeResponse(
                id=challenge.id,
                title=challenge.title,
                description=challenge.description,
                goal_type=challenge.goal_type,
                target_value=challenge.target_value,
                current_value=total,
                progress_percentage=_progress_percentage(
                    total, challenge.target_value
                ),
                start_date=challenge.start_date,
                end_date=challenge.end_date,
                is_active=challenge.is_active,
                is_completed=challenge.is_completed,
                participant_count=participant_count,
                top_contributors=top_contributors,
            )
        )

    await db.commit()
    return responses


async def create_challenge(
    db: AsyncSession, request: CreateChallengeRequest, current_user: User
) -> TeamChallengeResponse:
    """Create a new team challenge."""
    org_id = request.organization_id
    if not org_id:
        result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == current_user.id)
            .limit(1)
        )
        org_id = result.scalar_one_or_none()
        if not org_id:
            raise EfficiencyValidationError("No organization found for user")

    challenge = TeamChallenge(
        organization_id=org_id,
        title=request.title,
        description=request.description,
        goal_type=request.goal_type,
        target_value=request.target_value,
        current_value=0,
        start_date=request.start_date,
        end_date=request.end_date,
        is_active=True,
        is_completed=False,
        created_by_id=current_user.id,
    )

    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    return TeamChallengeResponse(
        id=challenge.id,
        title=challenge.title,
        description=challenge.description,
        goal_type=challenge.goal_type,
        target_value=challenge.target_value,
        current_value=0,
        progress_percentage=0,
        start_date=challenge.start_date,
        end_date=challenge.end_date,
        is_active=True,
        is_completed=False,
        participant_count=0,
        top_contributors=[],
    )


async def update_challenge(
    db: AsyncSession,
    challenge_id: UUID,
    request: CreateChallengeRequest,
    current_user: User,
) -> TeamChallengeResponse:
    """Update a team challenge."""
    result = await db.execute(
        select(TeamChallenge)
        .options(selectinload(TeamChallenge.participants))
        .where(TeamChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise EfficiencyNotFoundError("Challenge not found")

    if challenge.created_by_id != current_user.id and current_user.role != "admin":
        raise EfficiencyForbiddenError("Not authorized to edit this challenge")

    challenge.title = request.title
    challenge.description = request.description
    challenge.goal_type = request.goal_type
    challenge.target_value = request.target_value
    challenge.start_date = request.start_date
    challenge.end_date = request.end_date

    await db.commit()
    await db.refresh(challenge)

    return TeamChallengeResponse(
        id=challenge.id,
        title=challenge.title,
        description=challenge.description,
        goal_type=challenge.goal_type,
        target_value=challenge.target_value,
        current_value=challenge.current_value,
        progress_percentage=_progress_percentage(
            challenge.current_value, challenge.target_value
        ),
        start_date=challenge.start_date,
        end_date=challenge.end_date,
        is_active=challenge.is_active,
        is_completed=challenge.is_completed,
        participant_count=len(challenge.participants),
        top_contributors=[],
    )


async def delete_challenge(
    db: AsyncSession, challenge_id: UUID, current_user: User
) -> dict:
    """Delete a team challenge."""
    result = await db.execute(
        select(TeamChallenge).where(TeamChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()

    if not challenge:
        raise EfficiencyNotFoundError("Challenge not found")

    if challenge.created_by_id != current_user.id and current_user.role != "admin":
        raise EfficiencyForbiddenError(
            "Not authorized to delete this challenge"
        )

    await db.delete(challenge)
    await db.commit()

    return {"status": "deleted"}
