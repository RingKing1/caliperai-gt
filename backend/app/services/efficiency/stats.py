"""Efficiency analytics: personal stats, live team status, team stats, leaderboard."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Campaign,
    DailyUserStats,
    Dataset,
    OrganizationMember,
    Scene,
    Task,
    TaskStatus,
    TimeSession,
    User,
    UserLoginSession,
)
from app.services.efficiency.common import get_display_name
from app.services.efficiency.schemas import (
    AnnotationBreakdown,
    EfficiencyStats,
    LeaderboardEntry,
    LiveUserStatus,
    QualityMetrics,
    TeamMemberStats,
    WorkflowMetrics,
)

logger = logging.getLogger(__name__)

_AUTO_SOURCES = (
    "auto",
    "airflow_model_v1",
    "airflow_model_v2",
    "auto_interpolated",
    "imported",
)
_ANNOTATION_MODELS = [
    Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion,
]
_MIN_TRACKING_SECONDS = 60


def team_period_start(now: datetime, period: str) -> datetime:
    """Start timestamp for the team-stats period filter."""
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    return now - timedelta(days=30)


def leaderboard_period_start(now: datetime, period: str) -> datetime:
    """Start timestamp for the leaderboard period filter."""
    if period == "all_time":
        return datetime(2020, 1, 1)
    return team_period_start(now, period)


def build_quality_metrics(
    tasks_accepted: int, tasks_rejected: int, revision_count: int
) -> QualityMetrics:
    """Derive quality metrics from workflow counters (zero-reviewed => zeros)."""
    total_reviewed = tasks_accepted + tasks_rejected
    first_time_acceptance_rate = 0.0
    rejection_rate = 0.0
    quality_score = 0.0

    if total_reviewed > 0:
        first_time_acceptance_rate = round(
            (
                (tasks_accepted - min(revision_count, tasks_accepted))
                / max(tasks_accepted, 1)
            )
            * 100,
            1,
        )
        rejection_rate = round((tasks_rejected / total_reviewed) * 100, 1)
        workflow_score = max(
            0.0, min(100.0, 100 - (rejection_rate * 0.5) - (revision_count * 2))
        )
        quality_score = round(workflow_score, 1)

    return QualityMetrics(
        first_time_acceptance_rate=first_time_acceptance_rate,
        rejection_rate=rejection_rate,
        revision_turnaround_hours=0.0,
        quality_score=round(quality_score, 1),
    )


def throughput_metrics(active_time: int, total_annotations: int) -> tuple[float, float]:
    """Labels/hour and avg seconds/label; requires >=60s tracked time."""
    labels_per_hour = 0.0
    avg_time_per_label = 0.0
    if active_time >= _MIN_TRACKING_SECONDS and total_annotations > 0:
        hours = active_time / 3600
        labels_per_hour = round(total_annotations / hours, 1)
        avg_time_per_label = round(active_time / total_annotations, 1)
    return labels_per_hour, avg_time_per_label


def resolve_active_time(
    task_total_time: int, task_session_time: int, login_session_time: int
) -> int:
    """Prefer aggregated task time, then task-session time, then login-session time."""
    if task_total_time > 0:
        return task_total_time
    if task_session_time > 0:
        return task_session_time
    return login_session_time


async def get_my_stats(
    db: AsyncSession,
    current_user: User,
    organization_id: Optional[UUID],
    days: int,
) -> EfficiencyStats:
    """Get personal efficiency statistics for a given period."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = today_start - timedelta(days=days - 1)
    week_start = today_start - timedelta(days=today_start.weekday())

    async def count_user_annotations(since: datetime) -> int:
        """Count manual annotations for the current user since a given date."""
        total = 0
        for model in _ANNOTATION_MODELS:
            result = await db.execute(
                select(func.count(model.id))
                .join(Task, model.task_id == Task.id)
                .where(
                    and_(
                        Task.assignee_id == current_user.id,
                        model.created_at >= since,
                        cast(model.source, String).notin_(_AUTO_SOURCES),
                    )
                )
            )
            total += result.scalar() or 0
        return total

    period_labels = await count_user_annotations(period_start)
    week_labels = await count_user_annotations(week_start)

    sessions_period_result = await db.execute(
        select(func.sum(UserLoginSession.active_duration_seconds)).where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.session_start >= period_start,
            )
        )
    )
    period_active_time = int(sessions_period_result.scalar() or 0)

    week_sessions_result = await db.execute(
        select(func.sum(UserLoginSession.active_duration_seconds)).where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.session_start >= week_start,
            )
        )
    )
    week_active_time = int(week_sessions_result.scalar() or 0)

    total_hours = period_active_time / 3600 if period_active_time > 0 else 0
    labels_per_hour = (period_labels / total_hours) if total_hours > 0 else 0

    streak = 0
    streak_cutoff = today_start - timedelta(days=365)
    active_days: set[str] = set()
    for model in _ANNOTATION_MODELS:
        rows = await db.execute(
            select(func.date_trunc('day', model.created_at).label('day'))
            .join(Task, model.task_id == Task.id)
            .where(
                and_(
                    Task.assignee_id == current_user.id,
                    model.created_at >= streak_cutoff,
                    cast(model.source, String).notin_(_AUTO_SOURCES),
                )
            )
            .distinct()
        )
        for row in rows.all():
            if row[0]:
                active_days.add(row[0].strftime('%Y-%m-%d'))

    check_date = today_start
    for _ in range(365):
        if check_date.strftime('%Y-%m-%d') in active_days:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    sessions_result = await db.execute(
        select(func.count(UserLoginSession.id)).where(
            and_(
                UserLoginSession.user_id == current_user.id,
                or_(
                    UserLoginSession.session_start >= period_start,
                    and_(
                        UserLoginSession.is_active == True,  # noqa: E712
                        UserLoginSession.last_heartbeat_at >= period_start,
                    ),
                ),
            )
        )
    )
    period_sessions = sessions_result.scalar() or 0

    acceptance_result = await db.execute(
        select(
            func.count(Task.id).filter(Task.status == TaskStatus.ACCEPTED),
            func.count(Task.id).filter(
                or_(
                    Task.status.in_(
                        [TaskStatus.ACCEPTED, TaskStatus.REJECTED, TaskStatus.SUBMITTED]
                    ),
                    Task.stage.in_(["qa", "customer_qa", "accepted"]),
                )
            ),
        ).where(Task.assignee_id == current_user.id)
    )
    acceptance_data = acceptance_result.first()
    accepted_count = acceptance_data[0] or 0
    total_reviewed = acceptance_data[1] or 0
    acceptance_rate = (
        round(accepted_count / total_reviewed * 100, 1) if total_reviewed > 0 else None
    )

    return EfficiencyStats(
        today_labels=period_labels,
        today_active_time_seconds=period_active_time,
        today_sessions=period_sessions,
        week_labels=week_labels,
        week_active_time_seconds=week_active_time,
        labels_per_hour=round(labels_per_hour, 2),
        acceptance_rate=acceptance_rate,
        current_streak_days=streak,
        rank_in_team=None,
        vs_team_avg_percentage=0,
    )


async def get_team_live_status(
    db: AsyncSession,
    current_user: User,
    organization_id: Optional[UUID],
) -> list[LiveUserStatus]:
    """Get real-time status of team members."""
    now = datetime.utcnow()
    active_threshold = now - timedelta(minutes=5)

    query = (
        select(TimeSession, User, Task)
        .join(User, TimeSession.user_id == User.id)
        .join(Task, TimeSession.task_id == Task.id)
        .where(TimeSession.is_active == True)  # noqa: E712
        .where(TimeSession.last_heartbeat_at >= active_threshold)
    )

    result = await db.execute(query)
    active_sessions = result.all()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    statuses = []
    for session, user, task in active_sessions:
        labels_result = await db.execute(
            select(DailyUserStats.labels_created).where(
                and_(
                    DailyUserStats.user_id == user.id,
                    DailyUserStats.stats_date == today_start,
                )
            )
        )
        labels_today = labels_result.scalar() or 0

        display_name = await get_display_name(db, user, current_user, organization_id)

        statuses.append(
            LiveUserStatus(
                user_id=user.id,
                display_name=display_name,
                current_task_id=task.id,
                current_task_name=task.name,
                is_active=not session.is_idle,
                last_activity=session.last_action_at or session.last_heartbeat_at,
                session_duration_seconds=session.active_duration_seconds,
                labels_today=labels_today,
            )
        )

    return sorted(statuses, key=lambda x: x.labels_today, reverse=True)


async def get_team_stats(
    db: AsyncSession,
    current_user: User,
    organization_id: Optional[UUID],
    dataset_id: Optional[UUID],
    campaign_id: Optional[UUID],
    period: str,
) -> list[TeamMemberStats]:
    """
    Get comprehensive statistics for all team members in the organization.
    Includes annotation breakdowns, workflow metrics, and quality scores.
    Can be filtered by dataset or campaign.
    """
    now = datetime.utcnow()
    active_threshold = now - timedelta(minutes=5)
    start_date = team_period_start(now, period)

    logger.info(
        "Team stats filters: org=%s, campaign=%s, dataset=%s, period=%s",
        organization_id,
        campaign_id,
        dataset_id,
        period,
    )

    derived_org_id = organization_id

    if not derived_org_id and (campaign_id or dataset_id):
        if campaign_id:
            campaign_result = await db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            )
            campaign = campaign_result.scalar_one_or_none()
            if campaign:
                derived_org_id = campaign.organization_id
                logger.info(
                    "Derived organization_id %s from campaign %s",
                    derived_org_id,
                    campaign_id,
                )
        elif dataset_id:
            dataset_result = await db.execute(
                select(Dataset).where(Dataset.id == dataset_id)
            )
            dataset = dataset_result.scalar_one_or_none()
            if dataset:
                campaign_result = await db.execute(
                    select(Campaign).where(Campaign.id == dataset.campaign_id)
                )
                campaign = campaign_result.scalar_one_or_none()
                if campaign:
                    derived_org_id = campaign.organization_id

    if derived_org_id:
        members_result = await db.execute(
            select(OrganizationMember, User)
            .join(User, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == derived_org_id)
            .where(User.is_active == True)  # noqa: E712
        )
        members = [(om, u) for om, u in members_result.all()]
    else:
        members_result = await db.execute(
            select(User).where(User.is_active == True)  # noqa: E712
        )
        members = [(None, u) for u in members_result.scalars().all()]

    active_sessions_result = await db.execute(
        select(TimeSession, Task)
        .join(Task, TimeSession.task_id == Task.id)
        .where(TimeSession.is_active == True)  # noqa: E712
        .where(TimeSession.last_heartbeat_at >= active_threshold)
    )
    active_sessions = {s.user_id: (s, t) for s, t in active_sessions_result.all()}

    login_online_threshold = now - timedelta(minutes=2)
    login_online_result = await db.execute(
        select(UserLoginSession.user_id).where(
            UserLoginSession.is_active == True,  # noqa: E712
            UserLoginSession.last_heartbeat_at >= login_online_threshold,
        )
    )
    login_online_users = {row[0] for row in login_online_result.all()}

    def _annotation_counts(annotation_model):
        query = (
            select(
                Task.assignee_id.label("user_id"),
                func.count(annotation_model.id).label("count"),
            )
            .select_from(Task)
            .join(Scene, Task.scene_id == Scene.id)
            .join(Dataset, Scene.dataset_id == Dataset.id)
            .join(annotation_model, annotation_model.task_id == Task.id)
            .where(Task.assignee_id.isnot(None))
            .where(annotation_model.created_at >= start_date)
            .where(cast(annotation_model.source, String).notin_(_AUTO_SOURCES))
        )
        if dataset_id:
            query = query.where(Scene.dataset_id == dataset_id)
        if campaign_id:
            query = query.where(Dataset.campaign_id == campaign_id)
        return query.group_by(Task.assignee_id)

    annotation3d_result = await db.execute(_annotation_counts(Annotation3D))
    annotation3d_counts = {row.user_id: row.count for row in annotation3d_result.all()}

    annotation2d_result = await db.execute(_annotation_counts(Annotation2D))
    annotation2d_counts = {row.user_id: row.count for row in annotation2d_result.all()}

    fusion_result = await db.execute(_annotation_counts(AnnotationFusion))
    fusion_counts = {row.user_id: row.count for row in fusion_result.all()}

    logger.info(
        "Annotation counts (campaign=%s, dataset=%s): 3D=%d, 2D=%d, Fusion=%d",
        campaign_id,
        dataset_id,
        len(annotation3d_counts),
        len(annotation2d_counts),
        len(fusion_counts),
    )
    logger.info("3D counts by user: %s", annotation3d_counts)
    logger.info("2D counts by user: %s", annotation2d_counts)

    _accepted_condition = or_(
        Task.status == TaskStatus.ACCEPTED.value,
        Task.stage.in_(["qa", "customer_qa", "accepted"]),
    )
    _rejected_condition = Task.revision_count > 0

    task_workflow_query = (
        select(
            Task.assignee_id.label("user_id"),
            func.count(Task.id).label("total_tasks"),
            func.count(Task.id)
            .filter(Task.status == TaskStatus.ASSIGNED.value)
            .label("assigned"),
            func.count(Task.id)
            .filter(Task.status == TaskStatus.IN_PROGRESS.value)
            .label("in_progress"),
            func.count(Task.id)
            .filter(Task.status == TaskStatus.SUBMITTED.value)
            .label("submitted"),
            func.count(Task.id).filter(_accepted_condition).label("accepted"),
            func.count(Task.id).filter(_rejected_condition).label("rejected"),
            func.sum(Task.revision_count).label("total_revisions"),
        )
        .select_from(Task)
        .join(Scene, Task.scene_id == Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .where(Task.assignee_id.isnot(None))
        .where(Task.updated_at >= start_date)
    )
    if dataset_id:
        task_workflow_query = task_workflow_query.where(Scene.dataset_id == dataset_id)
    if campaign_id:
        task_workflow_query = task_workflow_query.where(
            Dataset.campaign_id == campaign_id
        )
    task_workflow_query = task_workflow_query.group_by(Task.assignee_id)

    task_workflow_result = await db.execute(task_workflow_query)
    task_workflow = {row.user_id: row for row in task_workflow_result.all()}

    session_time_query = (
        select(
            TimeSession.user_id,
            func.sum(TimeSession.active_duration_seconds).label("total_active_time"),
        )
        .where(TimeSession.session_start >= start_date)
        .group_by(TimeSession.user_id)
    )
    session_time_result = await db.execute(session_time_query)
    session_times = {
        row.user_id: row.total_active_time or 0 for row in session_time_result.all()
    }

    login_session_time_query = (
        select(
            UserLoginSession.user_id,
            func.sum(UserLoginSession.active_duration_seconds).label("total_active_time"),
        )
        .where(UserLoginSession.session_start >= start_date)
        .group_by(UserLoginSession.user_id)
    )
    login_session_time_result = await db.execute(login_session_time_query)
    login_session_times = {
        row.user_id: row.total_active_time or 0
        for row in login_session_time_result.all()
    }

    task_time_query = (
        select(
            Task.assignee_id,
            func.sum(Task.total_time_seconds).label("total_task_time"),
        )
        .where(
            Task.assignee_id.isnot(None),
            Task.is_deleted == False,  # noqa: E712
            Task.total_time_seconds > 0,
        )
        .group_by(Task.assignee_id)
    )
    task_time_result = await db.execute(task_time_query)
    task_total_times = {
        row.assignee_id: row.total_task_time or 0 for row in task_time_result.all()
    }

    team_stats = []
    for org_member, user in members:
        session_data = active_sessions.get(user.id)
        is_online = session_data is not None or user.id in login_online_users
        current_task_id = None
        current_task_name = None
        session_duration = 0
        is_active = False
        last_activity = None

        if session_data:
            session, task = session_data
            current_task_id = task.id
            current_task_name = task.name
            session_duration = session.active_duration_seconds or 0
            is_active = not session.is_idle
            last_activity = session.last_action_at or session.last_heartbeat_at
        elif user.id in login_online_users:
            login_sess_result = await db.execute(
                select(UserLoginSession)
                .where(
                    UserLoginSession.user_id == user.id,
                    UserLoginSession.is_active == True,  # noqa: E712
                )
                .order_by(UserLoginSession.last_heartbeat_at.desc())
                .limit(1)
            )
            login_sess = login_sess_result.scalar_one_or_none()
            if login_sess:
                last_activity = login_sess.last_heartbeat_at

        cuboids_3d = annotation3d_counts.get(user.id, 0)
        boxes_2d = annotation2d_counts.get(user.id, 0)
        fusion = fusion_counts.get(user.id, 0)
        total_annotations = cuboids_3d + boxes_2d + fusion

        annotations = AnnotationBreakdown(
            cuboids_3d=cuboids_3d,
            boxes_2d=boxes_2d,
            fusion=fusion,
            total=total_annotations,
        )

        wf = task_workflow.get(user.id)
        tasks_assigned = wf.assigned if wf else 0
        tasks_in_progress = wf.in_progress if wf else 0
        tasks_submitted = wf.submitted if wf else 0
        tasks_accepted = wf.accepted if wf else 0
        tasks_rejected = wf.rejected if wf else 0
        revision_count = int(wf.total_revisions or 0) if wf else 0

        workflow = WorkflowMetrics(
            tasks_assigned=tasks_assigned,
            tasks_in_progress=tasks_in_progress,
            tasks_submitted=tasks_submitted,
            tasks_accepted=tasks_accepted,
            tasks_rejected=tasks_rejected,
            revision_count=revision_count,
        )

        quality = build_quality_metrics(tasks_accepted, tasks_rejected, revision_count)

        active_time = resolve_active_time(
            task_total_times.get(user.id, 0),
            session_times.get(user.id, 0),
            login_session_times.get(user.id, 0),
        )
        labels_per_hour, avg_time_per_label = throughput_metrics(
            active_time, total_annotations
        )

        display_name = await get_display_name(db, user, current_user, derived_org_id)
        role = (
            org_member.role
            if org_member
            else (user.role if hasattr(user, 'role') else None)
        )

        team_stats.append(
            TeamMemberStats(
                user_id=user.id,
                display_name=display_name,
                email=user.email if hasattr(user, 'email') else None,
                role=role,
                is_online=is_online,
                is_active=is_active,
                current_task_id=current_task_id,
                current_task_name=current_task_name,
                last_activity=last_activity,
                session_duration_seconds=session_duration,
                annotations=annotations,
                workflow=workflow,
                quality=quality,
                active_time_seconds=active_time,
                labels_per_hour=labels_per_hour,
                avg_time_per_label_seconds=avg_time_per_label,
                period_start=start_date,
                period_end=now,
            )
        )

    return sorted(team_stats, key=lambda x: (not x.is_online, -x.annotations.total))


async def get_leaderboard(
    db: AsyncSession,
    current_user: User,
    organization_id: Optional[UUID],
    period: str,
    limit: int,
) -> list[LeaderboardEntry]:
    """Get leaderboard for the organization."""
    now = datetime.utcnow()
    start_date = leaderboard_period_start(now, period)

    org_member_ids: set[UUID] = set()
    if organization_id:
        members_result = await db.execute(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == organization_id
            )
        )
        org_member_ids = {row[0] for row in members_result.all()}
        if not org_member_ids:
            return []

    async def get_user_annotation_counts(annotation_model) -> dict:
        """Get annotation counts grouped by user (via task assignment)."""
        query = (
            select(
                Task.assignee_id,
                func.count(annotation_model.id).label("count"),
            )
            .join(Task, annotation_model.task_id == Task.id)
            .where(
                and_(
                    annotation_model.created_at >= start_date,
                    Task.assignee_id.isnot(None),
                    Task.is_deleted == False,  # noqa: E712
                    cast(annotation_model.source, String).notin_(_AUTO_SOURCES),
                )
            )
            .group_by(Task.assignee_id)
        )
        result = await db.execute(query)
        return {row[0]: row[1] for row in result.all()}

    user_labels: dict[UUID, int] = {}
    for annotation_model in _ANNOTATION_MODELS:
        counts = await get_user_annotation_counts(annotation_model)
        for user_id, count in counts.items():
            if organization_id and user_id not in org_member_ids:
                continue
            user_labels[user_id] = user_labels.get(user_id, 0) + count

    sorted_users = sorted(user_labels.items(), key=lambda x: x[1], reverse=True)[:limit]

    if not sorted_users:
        return []

    user_times: dict[UUID, int] = {}
    user_ids = [u[0] for u in sorted_users]

    time_result = await db.execute(
        select(
            Task.assignee_id,
            func.sum(Task.total_time_seconds).label("total_time"),
        )
        .where(
            and_(
                Task.assignee_id.in_(user_ids),
                Task.is_deleted == False,  # noqa: E712
                Task.total_time_seconds > 0,
            )
        )
        .group_by(Task.assignee_id)
    )
    for row in time_result.all():
        user_times[row[0]] = row[1] or 0

    async def get_streak_days(user_id: UUID) -> int:
        streak = 0
        check_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(365):
            day_start = check_date
            day_end = check_date + timedelta(days=1)
            has_labels = False

            for annotation_model in _ANNOTATION_MODELS:
                result = await db.execute(
                    select(func.count(annotation_model.id))
                    .join(Task, annotation_model.task_id == Task.id)
                    .where(
                        and_(
                            Task.assignee_id == user_id,
                            annotation_model.created_at >= day_start,
                            annotation_model.created_at < day_end,
                        )
                    )
                )
                if (result.scalar() or 0) > 0:
                    has_labels = True
                    break

            if has_labels:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break
        return streak

    entries = []
    for rank, (user_id, total_labels) in enumerate(sorted_users, 1):
        user = await db.get(User, user_id)
        if not user:
            continue

        display_name = await get_display_name(db, user, current_user, organization_id)

        total_time = user_times.get(user_id, 0)
        avg_time = (total_time / total_labels) if total_time > 0 else 0

        streak = 0
        if rank <= 5:
            streak = await get_streak_days(user_id)

        entries.append(
            LeaderboardEntry(
                rank=rank,
                user_id=user_id,
                display_name=display_name,
                labels_count=total_labels or 0,
                acceptance_rate=0,
                avg_time_per_label_seconds=avg_time,
                streak_days=streak,
            )
        )

    return entries
