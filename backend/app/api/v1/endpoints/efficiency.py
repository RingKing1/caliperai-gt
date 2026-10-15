"""
Efficiency Monitoring API endpoints.

Provides session tracking, activity logging, and efficiency analytics:
- Session heartbeats for real-time presence
- Activity event logging
- User goals management  
- Achievements system
- Performance alerts
- Leaderboards and gamification
"""
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import (
    Achievement,
    AchievementType,
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Campaign,
    DailyUserStats,
    Dataset,
    OrganizationMember,
    PerformanceAlert,
    Permission,
    Scene,
    Task,
    TaskStatus,
    Taxonomy,
    TeamChallenge,
    TimeSession,
    User,
    UserLoginSession,
)
from app.services.efficiency import activity as activity_service
from app.services.efficiency import goals as goal_service
from app.services.efficiency import sessions as session_service
from app.services.efficiency.common import get_display_name
from app.services.efficiency.errors import (
    EfficiencyForbiddenError,
    EfficiencyNotFoundError,
    EfficiencyValidationError,
)
from app.services.efficiency.schemas import (
    AchievementResponse,
    ActivityEventRequest,
    ActivityEventResponse,
    AnnotationBreakdown,
    BatchActivityRequest,
    CreateChallengeRequest,
    EfficiencyStats,
    HeartbeatRequest,
    HeartbeatResponse,
    LeaderboardEntry,
    LiveUserStatus,
    LoginSessionEndRequest,
    LoginSessionEndResponse,
    LoginSessionHeartbeatRequest,
    LoginSessionHeartbeatResponse,
    LoginSessionStartRequest,
    LoginSessionStartResponse,
    PerformanceAlertResponse,
    QualityMetrics,
    SessionEndRequest,
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
    TeamChallengeResponse,
    TeamMemberStats,
    UserGoalCreate,
    UserGoalResponse,
    WorkflowMetrics,
)
from app.services.rbac_service import RequirePermissions, get_current_user

router = APIRouter()



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



# ---------------------------------------------------------------------------
# Time-tracking sessions (business logic in services/efficiency/sessions.py)
# ---------------------------------------------------------------------------


def _http_for_efficiency_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EfficiencyNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, EfficiencyForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, EfficiencyValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.post("/sessions/start", response_model=SessionStartResponse)
async def start_session(
    request: SessionStartRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionStartResponse:
    """Start a new time tracking session for a task."""
    try:
        return await session_service.start_session(db, request, current_user)
    except EfficiencyNotFoundError as exc:
        raise _http_for_efficiency_error(exc)


@router.post("/sessions/heartbeat", response_model=HeartbeatResponse)
async def session_heartbeat(
    request: HeartbeatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    """Send heartbeat to keep session alive (every 30s while on task)."""
    try:
        return await session_service.session_heartbeat(db, request, current_user)
    except (
        EfficiencyNotFoundError,
        EfficiencyForbiddenError,
        EfficiencyValidationError,
    ) as exc:
        raise _http_for_efficiency_error(exc)


@router.post("/sessions/end", response_model=SessionEndResponse)
async def end_session(
    request: SessionEndRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> SessionEndResponse:
    """End a time tracking session."""
    try:
        return await session_service.end_session(db, request, current_user)
    except (EfficiencyNotFoundError, EfficiencyForbiddenError) as exc:
        raise _http_for_efficiency_error(exc)


@router.post("/login-sessions/start", response_model=LoginSessionStartResponse)
async def start_login_session(
    request: LoginSessionStartRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> LoginSessionStartResponse:
    """Start a global login session for activity tracking."""
    return await session_service.start_login_session(db, request, current_user)


@router.post("/login-sessions/heartbeat", response_model=LoginSessionHeartbeatResponse)
async def login_session_heartbeat(
    request: LoginSessionHeartbeatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> LoginSessionHeartbeatResponse:
    """Send heartbeat for a global login session (every 30s while in app)."""
    try:
        return await session_service.login_session_heartbeat(
            db, request, current_user
        )
    except (
        EfficiencyNotFoundError,
        EfficiencyForbiddenError,
        EfficiencyValidationError,
    ) as exc:
        raise _http_for_efficiency_error(exc)


@router.post("/login-sessions/end", response_model=LoginSessionEndResponse)
async def end_login_session(
    request: LoginSessionEndRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> LoginSessionEndResponse:
    """End a global login session."""
    try:
        return await session_service.end_login_session(db, request, current_user)
    except (EfficiencyNotFoundError, EfficiencyForbiddenError) as exc:
        raise _http_for_efficiency_error(exc)


@router.get("/login-sessions/current")
async def get_current_login_session(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Get the current active login session for the user."""
    return await session_service.get_current_login_session(db, current_user)


# ---------------------------------------------------------------------------
# Activity events (services/efficiency/activity.py)
# ---------------------------------------------------------------------------


@router.post("/activity/log", response_model=ActivityEventResponse)
async def log_activity(
    request: ActivityEventRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ActivityEventResponse:
    """Log a single activity event."""
    return await activity_service.log_activity(db, request, current_user)


@router.post("/activity/batch")
async def log_activity_batch(
    request: BatchActivityRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Log multiple activity events at once (for buffered logging)."""
    return await activity_service.log_activity_batch(db, request, current_user)


# ---------------------------------------------------------------------------
# Personal goals (services/efficiency/goals.py)
# ---------------------------------------------------------------------------


@router.get("/goals/my", response_model=List[UserGoalResponse])
async def get_my_goals(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    include_completed: bool = Query(False),
) -> List[UserGoalResponse]:
    """Get current user's goals with live progress from annotation counts."""
    return await goal_service.list_my_goals(db, current_user, include_completed)


@router.post("/goals", response_model=UserGoalResponse)
async def create_goal(
    goal: UserGoalCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UserGoalResponse:
    """Create a new personal goal."""
    return await goal_service.create_goal(db, goal, current_user)


@router.put("/goals/{goal_id}", response_model=UserGoalResponse)
async def update_goal(
    goal_id: UUID,
    goal: UserGoalCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UserGoalResponse:
    """Update a personal goal."""
    try:
        return await goal_service.update_goal(db, goal_id, goal, current_user)
    except EfficiencyNotFoundError as exc:
        raise _http_for_efficiency_error(exc)


@router.delete("/goals/{goal_id}")
async def delete_goal(
    goal_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a personal goal."""
    try:
        return await goal_service.delete_goal(db, goal_id, current_user)
    except EfficiencyNotFoundError as exc:
        raise _http_for_efficiency_error(exc)


@router.get("/achievements/my", response_model=List[AchievementResponse])
async def get_my_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> List[AchievementResponse]:
    """Get current user's achievements."""
    result = await db.execute(
        select(Achievement)
        .where(Achievement.user_id == current_user.id)
        .order_by(desc(Achievement.earned_at))
    )
    achievements = result.scalars().all()
    
    return [
        AchievementResponse(
            id=a.id,
            achievement_type=a.achievement_type,
            earned_at=a.earned_at,
            metadata=a.achievement_metadata or {},
            is_seen=a.is_seen,
            title=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("title", a.achievement_type),
            description=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("description", ""),
            icon=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("icon", "🏅"),
        )
        for a in achievements
    ]


@router.get("/achievements/unseen", response_model=List[AchievementResponse])
async def get_unseen_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> List[AchievementResponse]:
    """Get current user's unseen achievements for notification purposes."""
    result = await db.execute(
        select(Achievement)
        .where(
            and_(
                Achievement.user_id == current_user.id,
                Achievement.is_seen == False,
            )
        )
        .order_by(desc(Achievement.earned_at))
    )
    achievements = result.scalars().all()
    
    return [
        AchievementResponse(
            id=a.id,
            achievement_type=a.achievement_type,
            earned_at=a.earned_at,
            metadata=a.achievement_metadata or {},
            is_seen=a.is_seen,
            title=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("title", a.achievement_type),
            description=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("description", ""),
            icon=ACHIEVEMENT_INFO.get(a.achievement_type, {}).get("icon", "🏅"),
        )
        for a in achievements
    ]


@router.post("/achievements/{achievement_id}/mark-seen")
async def mark_achievement_seen(
    achievement_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark an achievement as seen."""
    achievement = await db.get(Achievement, achievement_id)
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    if achievement.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your achievement")
    
    achievement.is_seen = True
    achievement.seen_at = datetime.utcnow()
    await db.commit()
    
    return {"status": "marked_seen"}



@router.get("/stats/my", response_model=EfficiencyStats)
async def get_my_efficiency_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    days: int = Query(1, description="Number of days for the period (1=today, 7=week, etc.)"),
) -> EfficiencyStats:
    """Get personal efficiency statistics for a given period."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = today_start - timedelta(days=days - 1)
    week_start = today_start - timedelta(days=today_start.weekday())
    
    _AUTO_SOURCES = ("auto", "airflow_model_v1", "airflow_model_v2", "auto_interpolated", "imported")

    async def count_user_annotations(since: datetime) -> int:
        """Count manually-created annotations for the current user since a given date."""
        total = 0

        for Model in [Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion]:
            result = await db.execute(
                select(func.count(Model.id))
                .join(Task, Model.task_id == Task.id)
                .where(
                    and_(
                        Task.assignee_id == current_user.id,
                        Model.created_at >= since,
                        cast(Model.source, String).notin_(_AUTO_SOURCES),
                    )
                )
            )
            total += result.scalar() or 0

        return total
    
    period_labels = await count_user_annotations(period_start)
    week_labels = await count_user_annotations(week_start)
    
    period_active_time = 0
    
    sessions_period_result = await db.execute(
        select(func.sum(UserLoginSession.active_duration_seconds))
        .where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.session_start >= period_start,
            )
        )
    )
    sessions_period_time = int(sessions_period_result.scalar() or 0)

    period_active_time = sessions_period_time

    week_sessions_result = await db.execute(
        select(func.sum(UserLoginSession.active_duration_seconds))
        .where(
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
    for AnnotationModel in [Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion]:
        rows = await db.execute(
            select(func.date_trunc('day', AnnotationModel.created_at).label('day'))
            .join(Task, AnnotationModel.task_id == Task.id)
            .where(
                and_(
                    Task.assignee_id == current_user.id,
                    AnnotationModel.created_at >= streak_cutoff,
                    cast(AnnotationModel.source, String).notin_(_AUTO_SOURCES),
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
        select(func.count(UserLoginSession.id))
        .where(
            and_(
                UserLoginSession.user_id == current_user.id,
                or_(
                    UserLoginSession.session_start >= period_start,
                    and_(
                        UserLoginSession.is_active == True,
                        UserLoginSession.last_heartbeat_at >= period_start,
                    )
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
                    Task.status.in_([TaskStatus.ACCEPTED, TaskStatus.REJECTED, TaskStatus.SUBMITTED]),
                    Task.stage.in_(["qa", "customer_qa", "accepted"]),
                )
            ),
        )
        .where(Task.assignee_id == current_user.id)
    )
    acceptance_data = acceptance_result.first()
    accepted_count = acceptance_data[0] or 0
    total_reviewed = acceptance_data[1] or 0
    acceptance_rate = round(accepted_count / total_reviewed * 100, 1) if total_reviewed > 0 else None

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



@router.get("/live/team", response_model=List[LiveUserStatus])
async def get_team_live_status(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
) -> List[LiveUserStatus]:
    """Get real-time status of team members."""
    now = datetime.utcnow()
    active_threshold = now - timedelta(minutes=5)
    
    query = (
        select(TimeSession, User, Task)
        .join(User, TimeSession.user_id == User.id)
        .join(Task, TimeSession.task_id == Task.id)
        .where(TimeSession.is_active == True)
        .where(TimeSession.last_heartbeat_at >= active_threshold)
    )
    
    result = await db.execute(query)
    active_sessions = result.all()
    
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    statuses = []
    for session, user, task in active_sessions:
        labels_result = await db.execute(
            select(DailyUserStats.labels_created)
            .where(
                and_(
                    DailyUserStats.user_id == user.id,
                    DailyUserStats.stats_date == today_start,
                )
            )
        )
        labels_today = labels_result.scalar() or 0
        
        display_name = await get_display_name(db, user, current_user, organization_id)
        
        statuses.append(LiveUserStatus(
            user_id=user.id,
            display_name=display_name,
            current_task_id=task.id,
            current_task_name=task.name,
            is_active=not session.is_idle,
            last_activity=session.last_action_at or session.last_heartbeat_at,
            session_duration_seconds=session.active_duration_seconds,
            labels_today=labels_today,
        ))
    
    return sorted(statuses, key=lambda x: x.labels_today, reverse=True)


@router.get("/team-stats", response_model=List[TeamMemberStats])
async def get_team_stats(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    dataset_id: Optional[UUID] = Query(None),
    campaign_id: Optional[UUID] = Query(None),
    period: str = Query("today", enum=["today", "week", "month"]),
) -> List[TeamMemberStats]:
    """
    Get comprehensive statistics for all team members in the organization.
    Includes annotation breakdowns, workflow metrics, and quality scores.
    Can be filtered by dataset or campaign.
    """
    now = datetime.utcnow()
    active_threshold = now - timedelta(minutes=5)
    
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now - timedelta(days=7)
    else:
        start_date = now - timedelta(days=30)
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Team stats filters: organization_id={organization_id}, campaign_id={campaign_id}, dataset_id={dataset_id}, period={period}")
    
    derived_org_id = organization_id
    
    if not derived_org_id and (campaign_id or dataset_id):
        if campaign_id:
            campaign_result = await db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            )
            campaign = campaign_result.scalar_one_or_none()
            if campaign:
                derived_org_id = campaign.organization_id
                logger.info(f"Derived organization_id {derived_org_id} from campaign {campaign_id}")
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
            .where(User.is_active == True)
        )
        members = [(om, u) for om, u in members_result.all()]
    else:
        members_result = await db.execute(
            select(User).where(User.is_active == True)
        )
        members = [(None, u) for u in members_result.scalars().all()]
    
    active_sessions_result = await db.execute(
        select(TimeSession, Task)
        .join(Task, TimeSession.task_id == Task.id)
        .where(TimeSession.is_active == True)
        .where(TimeSession.last_heartbeat_at >= active_threshold)
    )
    active_sessions = {s.user_id: (s, t) for s, t in active_sessions_result.all()}

    login_online_threshold = now - timedelta(minutes=2)
    login_online_result = await db.execute(
        select(UserLoginSession.user_id)
        .where(
            UserLoginSession.is_active == True,
            UserLoginSession.last_heartbeat_at >= login_online_threshold,
        )
    )
    login_online_users = {row[0] for row in login_online_result.all()}
    
    
    AUTO_SOURCES = ("auto", "airflow_model_v1", "airflow_model_v2", "auto_interpolated", "imported")

    annotation3d_query = (
        select(
            Task.assignee_id.label("user_id"),
            func.count(Annotation3D.id).label("count"),
        )
        .select_from(Task)
        .join(Scene, Task.scene_id == Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .join(Annotation3D, Annotation3D.task_id == Task.id)
        .where(Task.assignee_id.isnot(None))
        .where(Annotation3D.created_at >= start_date)
        .where(cast(Annotation3D.source, String).notin_(AUTO_SOURCES))
    )
    if dataset_id:
        annotation3d_query = annotation3d_query.where(Scene.dataset_id == dataset_id)
    if campaign_id:
        annotation3d_query = annotation3d_query.where(Dataset.campaign_id == campaign_id)
    annotation3d_query = annotation3d_query.group_by(Task.assignee_id)

    annotation3d_result = await db.execute(annotation3d_query)
    annotation3d_counts = {row.user_id: row.count for row in annotation3d_result.all()}

    annotation2d_query = (
        select(
            Task.assignee_id.label("user_id"),
            func.count(Annotation2D.id).label("count"),
        )
        .select_from(Task)
        .join(Scene, Task.scene_id == Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .join(Annotation2D, Annotation2D.task_id == Task.id)
        .where(Task.assignee_id.isnot(None))
        .where(Annotation2D.created_at >= start_date)
        .where(cast(Annotation2D.source, String).notin_(AUTO_SOURCES))
    )
    if dataset_id:
        annotation2d_query = annotation2d_query.where(Scene.dataset_id == dataset_id)
    if campaign_id:
        annotation2d_query = annotation2d_query.where(Dataset.campaign_id == campaign_id)
    annotation2d_query = annotation2d_query.group_by(Task.assignee_id)

    annotation2d_result = await db.execute(annotation2d_query)
    annotation2d_counts = {row.user_id: row.count for row in annotation2d_result.all()}

    fusion_query = (
        select(
            Task.assignee_id.label("user_id"),
            func.count(AnnotationFusion.id).label("count"),
        )
        .select_from(Task)
        .join(Scene, Task.scene_id == Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .join(AnnotationFusion, AnnotationFusion.task_id == Task.id)
        .where(Task.assignee_id.isnot(None))
        .where(AnnotationFusion.created_at >= start_date)
        .where(cast(AnnotationFusion.source, String).notin_(AUTO_SOURCES))
    )
    if dataset_id:
        fusion_query = fusion_query.where(Scene.dataset_id == dataset_id)
    if campaign_id:
        fusion_query = fusion_query.where(Dataset.campaign_id == campaign_id)
    fusion_query = fusion_query.group_by(Task.assignee_id)
    
    fusion_result = await db.execute(fusion_query)
    fusion_counts = {row.user_id: row.count for row in fusion_result.all()}
    
    logger.info(f"Annotation counts with filters (campaign={campaign_id}, dataset={dataset_id}): 3D={len(annotation3d_counts)}, 2D={len(annotation2d_counts)}, Fusion={len(fusion_counts)}")
    logger.info(f"3D counts by user: {annotation3d_counts}")
    logger.info(f"2D counts by user: {annotation2d_counts}")
    
    _accepted_condition = or_(
        Task.status == TaskStatus.ACCEPTED.value,
        Task.stage.in_(["qa", "customer_qa", "accepted"]),
    )
    _rejected_condition = Task.revision_count > 0

    task_workflow_query = (
        select(
            Task.assignee_id.label("user_id"),
            func.count(Task.id).label("total_tasks"),
            func.count(Task.id).filter(Task.status == TaskStatus.ASSIGNED.value).label("assigned"),
            func.count(Task.id).filter(Task.status == TaskStatus.IN_PROGRESS.value).label("in_progress"),
            func.count(Task.id).filter(Task.status == TaskStatus.SUBMITTED.value).label("submitted"),
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
        task_workflow_query = task_workflow_query.where(Dataset.campaign_id == campaign_id)
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
    session_times = {row.user_id: row.total_active_time or 0 for row in session_time_result.all()}
    
    login_session_time_query = (
        select(
            UserLoginSession.user_id,
            func.sum(UserLoginSession.active_duration_seconds).label("total_active_time"),
        )
        .where(UserLoginSession.session_start >= start_date)
        .group_by(UserLoginSession.user_id)
    )
    login_session_time_result = await db.execute(login_session_time_query)
    login_session_times = {row.user_id: row.total_active_time or 0 for row in login_session_time_result.all()}

    task_time_query = (
        select(
            Task.assignee_id,
            func.sum(Task.total_time_seconds).label("total_task_time"),
        )
        .where(
            Task.assignee_id.isnot(None),
            Task.is_deleted == False,
            Task.total_time_seconds > 0,
        )
        .group_by(Task.assignee_id)
    )
    task_time_result = await db.execute(task_time_query)
    task_total_times = {row.assignee_id: row.total_task_time or 0 for row in task_time_result.all()}
    
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
                .where(UserLoginSession.user_id == user.id, UserLoginSession.is_active == True)
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
        
        total_reviewed = tasks_accepted + tasks_rejected
        first_time_acceptance_rate = 0.0
        rejection_rate = 0.0
        quality_score = 0.0

        if total_reviewed > 0:
            first_time_acceptance_rate = round(
                ((tasks_accepted - min(revision_count, tasks_accepted)) / max(tasks_accepted, 1)) * 100, 1
            )
            rejection_rate = round((tasks_rejected / total_reviewed) * 100, 1)
            workflow_score = max(0.0, min(100.0,
                100 - (rejection_rate * 0.5) - (revision_count * 2)
            ))
            quality_score = round(workflow_score, 1)

        quality = QualityMetrics(
            first_time_acceptance_rate=first_time_acceptance_rate,
            rejection_rate=rejection_rate,
            revision_turnaround_hours=0.0,
            quality_score=round(quality_score, 1),
        )
        
        task_session_time = session_times.get(user.id, 0)
        login_session_time = login_session_times.get(user.id, 0)
        task_total_time = task_total_times.get(user.id, 0)

        if task_total_time > 0:
            active_time = task_total_time
        elif task_session_time > 0:
            active_time = task_session_time
        else:
            active_time = login_session_time

        labels_per_hour = 0.0
        avg_time_per_label = 0.0

        MIN_TRACKING_TIME = 60
        if active_time >= MIN_TRACKING_TIME and total_annotations > 0:
            hours = active_time / 3600
            labels_per_hour = round(total_annotations / hours, 1)
            avg_time_per_label = round(active_time / total_annotations, 1)
        
        display_name = await get_display_name(db, user, current_user, derived_org_id)
        role = org_member.role if org_member else (user.role if hasattr(user, 'role') else None)
        
        team_stats.append(TeamMemberStats(
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
        ))
    
    return sorted(team_stats, key=lambda x: (not x.is_online, -x.annotations.total))



@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    period: str = Query("week", enum=["today", "week", "month", "all_time"]),
    limit: int = Query(10, ge=1, le=100),
) -> List[LeaderboardEntry]:
    """Get leaderboard for the organization."""
    now = datetime.utcnow()
    
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now - timedelta(days=7)
    elif period == "month":
        start_date = now - timedelta(days=30)
    else:
        start_date = datetime(2020, 1, 1)
    
    org_member_ids: set[UUID] = set()
    if organization_id:
        members_result = await db.execute(
            select(OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == organization_id)
        )
        org_member_ids = {row[0] for row in members_result.all()}
        if not org_member_ids:
            return []
    
    _LEADERBOARD_AUTO_SOURCES = ("auto", "airflow_model_v1", "airflow_model_v2", "auto_interpolated", "imported")

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
                    Task.is_deleted == False,
                    cast(annotation_model.source, String).notin_(_LEADERBOARD_AUTO_SOURCES),
                )
            )
            .group_by(Task.assignee_id)
        )
        result = await db.execute(query)
        return {row[0]: row[1] for row in result.all()}
    
    user_labels: dict[UUID, int] = {}
    
    for annotation_model in [Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion]:
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
                Task.is_deleted == False,
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
            
            for AnnotationModel in [Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion]:
                result = await db.execute(
                    select(func.count(AnnotationModel.id))
                    .join(Task, AnnotationModel.task_id == Task.id)
                    .where(
                        and_(
                            Task.assignee_id == user_id,
                            AnnotationModel.created_at >= day_start,
                            AnnotationModel.created_at < day_end,
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
        avg_time = (total_time / total_labels) if total_labels > 0 else 0
        
        streak = 0
        if rank <= 5:
            streak = await get_streak_days(user_id)
        
        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=user_id,
            display_name=display_name,
            labels_count=total_labels or 0,
            acceptance_rate=0,
            avg_time_per_label_seconds=avg_time,
            streak_days=streak,
        ))
    
    return entries



@router.get("/alerts", response_model=List[PerformanceAlertResponse])
async def get_performance_alerts(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    include_acknowledged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
) -> List[PerformanceAlertResponse]:
    """Get performance alerts for team."""
    query = (
        select(PerformanceAlert, User)
        .join(User, PerformanceAlert.user_id == User.id)
        .order_by(desc(PerformanceAlert.created_at))
        .limit(limit)
    )
    
    if not include_acknowledged:
        query = query.where(PerformanceAlert.is_acknowledged == False)
    
    result = await db.execute(query)
    alerts = result.all()
    
    responses = []
    for alert, user in alerts:
        display_name = await get_display_name(db, user, current_user, organization_id)
        responses.append(PerformanceAlertResponse(
            id=alert.id,
            user_id=user.id,
            display_name=display_name,
            alert_type=alert.alert_type,
            severity=alert.severity,
            title=alert.title,
            message=alert.message,
            metrics=alert.metrics or {},
            is_acknowledged=alert.is_acknowledged,
            created_at=alert.created_at,
        ))
    
    return responses


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge a performance alert."""
    alert = await db.get(PerformanceAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_acknowledged = True
    alert.acknowledged_by_id = current_user.id
    alert.acknowledged_at = datetime.utcnow()
    
    await db.commit()
    
    return {"status": "acknowledged"}



_CHALLENGE_LABEL_TYPES = {"total_labels", "daily_labels", "weekly_labels", "labels"}
_CHALLENGE_AUTO_SOURCES = ("auto", "airflow_model_v1", "airflow_model_v2", "auto_interpolated", "imported")


async def _compute_challenge_progress(
    db: AsyncSession,
    challenge: "TeamChallenge",
    org_member_ids: list,
) -> dict[uuid_lib.UUID, float]:
    """
    Count each org member's label contributions within the challenge period.
    Returns {user_id: label_count}.
    """
    if challenge.goal_type not in _CHALLENGE_LABEL_TYPES:
        return {}

    start = challenge.start_date
    end = challenge.end_date
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    user_counts: dict[uuid_lib.UUID, float] = {}
    for Model in [Annotation, Annotation3D, Annotation2D, Annotation4D, AnnotationFusion]:
        result = await db.execute(
            select(Task.assignee_id, func.count(Model.id).label("cnt"))
            .join(Task, Model.task_id == Task.id)
            .where(
                and_(
                    Task.assignee_id.in_(org_member_ids),
                    Model.created_at >= start,
                    Model.created_at < end,
                    cast(Model.source, String).notin_(_CHALLENGE_AUTO_SOURCES),
                )
            )
            .group_by(Task.assignee_id)
        )
        for row in result.all():
            uid, cnt = row[0], row[1]
            user_counts[uid] = user_counts.get(uid, 0.0) + float(cnt)

    return user_counts


@router.get("/challenges", response_model=List[TeamChallengeResponse])
async def get_challenges(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    include_completed: bool = Query(False),
) -> List[TeamChallengeResponse]:
    """Get team challenges with live progress computed from actual annotation counts."""
    now = datetime.now(timezone.utc)

    query = (
        select(TeamChallenge)
        .options(selectinload(TeamChallenge.participants))
    )
    if organization_id:
        query = query.where(TeamChallenge.organization_id == organization_id)
    if not include_completed:
        query = query.where(TeamChallenge.is_active == True)
    query = query.order_by(desc(TeamChallenge.start_date))

    result = await db.execute(query)
    challenges = result.scalars().all()

    responses = []
    for challenge in challenges:
        members_result = await db.execute(
            select(OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == challenge.organization_id)
        )
        org_member_ids = [row[0] for row in members_result.all()]

        user_counts = await _compute_challenge_progress(db, challenge, org_member_ids)

        total = sum(user_counts.values())

        if total != challenge.current_value:
            challenge.current_value = total
            if total >= challenge.target_value and not challenge.is_completed:
                challenge.is_completed = True
                challenge.completed_at = now

        sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_contributors = []
        for rank, (uid, cnt) in enumerate(sorted_users, 1):
            if cnt <= 0:
                continue
            user = await db.get(User, uid)
            if user:
                display_name = await get_display_name(db, user, current_user, organization_id)
                top_contributors.append(LeaderboardEntry(
                    rank=rank,
                    user_id=uid,
                    display_name=display_name,
                    labels_count=int(cnt),
                    acceptance_rate=0,
                    avg_time_per_label_seconds=0,
                    streak_days=0,
                ))

        participant_count = sum(1 for c in user_counts.values() if c > 0)

        progress = min((total / challenge.target_value * 100), 100) if challenge.target_value > 0 else 0

        responses.append(TeamChallengeResponse(
            id=challenge.id,
            title=challenge.title,
            description=challenge.description,
            goal_type=challenge.goal_type,
            target_value=challenge.target_value,
            current_value=total,
            progress_percentage=progress,
            start_date=challenge.start_date,
            end_date=challenge.end_date,
            is_active=challenge.is_active,
            is_completed=challenge.is_completed,
            participant_count=participant_count,
            top_contributors=top_contributors,
        ))

    await db.commit()
    return responses


@router.post("/challenges", response_model=TeamChallengeResponse)
async def create_challenge(
    request: CreateChallengeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TeamChallengeResponse:
    """Create a new team challenge."""
    org_id = request.organization_id
    if not org_id:
        from app.models import OrganizationMember
        result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == current_user.id)
            .limit(1)
        )
        org_id = result.scalar_one_or_none()
        if not org_id:
            raise HTTPException(
                status_code=400,
                detail="No organization found for user",
            )
    
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


@router.put("/challenges/{challenge_id}", response_model=TeamChallengeResponse)
async def update_challenge(
    challenge_id: UUID,
    request: CreateChallengeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TeamChallengeResponse:
    """Update a team challenge."""
    result = await db.execute(
        select(TeamChallenge)
        .options(selectinload(TeamChallenge.participants))
        .where(TeamChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.created_by_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to edit this challenge")
    
    challenge.title = request.title
    challenge.description = request.description
    challenge.goal_type = request.goal_type
    challenge.target_value = request.target_value
    challenge.start_date = request.start_date
    challenge.end_date = request.end_date
    
    await db.commit()
    await db.refresh(challenge)
    
    progress = (challenge.current_value / challenge.target_value * 100) if challenge.target_value > 0 else 0
    
    return TeamChallengeResponse(
        id=challenge.id,
        title=challenge.title,
        description=challenge.description,
        goal_type=challenge.goal_type,
        target_value=challenge.target_value,
        current_value=challenge.current_value,
        progress_percentage=min(progress, 100),
        start_date=challenge.start_date,
        end_date=challenge.end_date,
        is_active=challenge.is_active,
        is_completed=challenge.is_completed,
        participant_count=len(challenge.participants),
        top_contributors=[],
    )


@router.delete("/challenges/{challenge_id}")
async def delete_challenge(
    challenge_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a team challenge."""
    result = await db.execute(
        select(TeamChallenge).where(TeamChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge.created_by_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this challenge")
    
    await db.delete(challenge)
    await db.commit()
    
    return {"status": "deleted"}


@router.get("/team-member-report/{user_id}")
async def get_team_member_report(
    user_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_GLOBAL))],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """Return full stats for one team member as a JSON dict for CSV export."""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    display_name = user.full_name or user.username

    base_user_filter = [Task.assignee_id == user_id, Task.is_deleted == False]
    if organization_id:
        base_user_filter.append(
            Task.scene_id.in_(
                select(Scene.id)
                .join(Dataset, Scene.dataset_id == Dataset.id)
                .join(Campaign, Dataset.campaign_id == Campaign.id)
                .where(Campaign.organization_id == organization_id, Campaign.is_deleted == False)
            )
        )

    task_rows = await db.execute(
        select(
            func.count(Task.id).label("total_tasks"),
            func.sum(Task.total_time_seconds).label("total_time"),
            func.sum(func.upper(Task.frame_range) - func.lower(Task.frame_range)).label("total_frames"),
            func.sum(Task.revision_count).label("total_revisions"),
            func.sum(case((Task.status == "accepted", 1), else_=0)).label("accepted"),
            func.sum(case((Task.status == "rejected", 1), else_=0)).label("rejected"),
            func.sum(case((Task.status.in_(["submitted", "accepted"]), 1), else_=0)).label("submitted"),
        )
        .where(and_(*base_user_filter))
    )
    t = task_rows.fetchone()
    total_tasks = t.total_tasks or 0
    total_time = t.total_time or 0
    total_frames = t.total_frames or 0
    total_revisions = t.total_revisions or 0
    accepted = t.accepted or 0
    rejected = t.rejected or 0
    submitted = t.submitted or 0
    total_reviewed = accepted + rejected

    total_labels = 0
    for model in [Annotation, Annotation3D, Annotation2D, AnnotationFusion]:
        r = await db.scalar(
            select(func.count(model.id))
            .join(Task, model.task_id == Task.id)
            .where(and_(*base_user_filter))
        )
        total_labels += r or 0
    r4d = await db.scalar(
        select(func.count(Annotation4D.id))
        .join(Task, Annotation4D.task_id == Task.id)
        .where(and_(*base_user_filter))
    )
    total_labels += r4d or 0

    hours = total_time / 3600 if total_time > 0 else 0
    labels_per_hour = round(total_labels / hours, 1) if hours > 0 else 0.0
    frames_per_hour = round(total_frames / hours, 1) if hours > 0 else 0.0
    avg_time_per_task = round(total_time / total_tasks, 1) if total_tasks > 0 else 0.0
    avg_time_per_frame = round(total_time / total_frames, 1) if total_frames > 0 else 0.0
    avg_time_per_label = round(total_time / total_labels, 1) if total_labels > 0 else 0.0

    acceptance_rate = round(accepted / total_reviewed * 100, 1) if total_reviewed > 0 else None
    rejection_rate = round(rejected / total_reviewed * 100, 1) if total_reviewed > 0 else None

    def fmt(secs: int) -> str:
        if not secs: return "0s"
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        if h: return f"{h}h {m}m {s}s"
        if m: return f"{m}m {s}s"
        return f"{s}s"

    slowest_task_row = await db.execute(
        select(Task.name, Task.total_time_seconds)
        .where(and_(*base_user_filter, Task.total_time_seconds > 0))
        .order_by(desc(Task.total_time_seconds)).limit(1)
    )
    slowest = slowest_task_row.fetchone()

    fastest_task_row = await db.execute(
        select(Task.name, Task.total_time_seconds)
        .where(and_(*base_user_filter, Task.total_time_seconds > 0))
        .order_by(Task.total_time_seconds).limit(1)
    )
    fastest = fastest_task_row.fetchone()

    active_scene_subq = (
        select(Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .join(Campaign, Dataset.campaign_id == Campaign.id)
        .where(
            Scene.is_deleted == False,
            Dataset.is_deleted == False,
            Campaign.is_deleted == False,
        )
    )
    if organization_id:
        active_scene_subq = active_scene_subq.where(Campaign.organization_id == organization_id)

    task_filter = [
        Task.assignee_id == user_id,
        Task.is_deleted == False,
        Task.scene_id.in_(active_scene_subq),
        or_(
            Task.total_time_seconds > 0,
            Task.started_at != None,
        ),
    ]

    all_tasks_result = await db.execute(
        select(
            Task.id, Task.name, Task.status, Task.stage,
            Task.total_time_seconds, Task.revision_count,
            Task.frame_range, Task.assigned_at, Task.submitted_at, Task.started_at,
            Task.taxonomy_id,
            Scene.name.label("scene_name"),
            Dataset.name.label("dataset_name"),
            Taxonomy.name.label("taxonomy_name"),
        )
        .join(Scene, Task.scene_id == Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .outerjoin(Taxonomy, Task.taxonomy_id == Taxonomy.id)
        .where(and_(*task_filter))
        .order_by(Task.created_at)
    )
    all_tasks_rows = all_tasks_result.mappings().all()

    from sqlalchemy import distinct as _distinct

    task_details = []
    for row in all_tasks_rows:
        task_id = row["id"]
        frame_range = row["frame_range"]
        frame_count = (frame_range.upper - frame_range.lower) if frame_range else 0
        task_time = row["total_time_seconds"] or 0
        tax_id = row["taxonomy_id"]
        tax_name = row["taxonomy_name"] or ""

        task_labels = 0
        for model in [Annotation3D, Annotation2D, Annotation]:
            q = select(func.count(model.id)).where(model.task_id == task_id)
            if tax_id is not None and hasattr(model, 'taxonomy_id'):
                q = q.where(model.taxonomy_id == tax_id)
            task_labels += await db.scalar(q) or 0

        frames_visited = 0
        for model in [Annotation3D, Annotation2D]:
            q = select(func.count(_distinct(model.frame_id))).where(model.task_id == task_id)
            if tax_id is not None:
                q = q.where(model.taxonomy_id == tax_id)
            frames_visited = max(frames_visited, await db.scalar(q) or 0)

        avg_time_per_frame = round(task_time / frames_visited, 1) if frames_visited > 0 else 0
        started_at = row["started_at"]
        submitted_at = row["submitted_at"] if row["stage"] != "annotation" else None

        task_details.append({
            "task_name": row["name"] or "",
            "taxonomy": tax_name,
            "scene": row["scene_name"] or "",
            "dataset": row["dataset_name"] or "",
            "status": row["status"] or "",
            "stage": row["stage"] or "",
            "total_frames": frame_count,
            "frames_visited": frames_visited,
            "labels_created": task_labels,
            "active_time": fmt(task_time),
            "avg_time_per_frame": fmt(int(avg_time_per_frame)) if avg_time_per_frame else "—",
            "revision_count": row["revision_count"] or 0,
            "start_time": started_at.strftime("%Y-%m-%d %H:%M") if started_at else "",
            "end_time": submitted_at.strftime("%Y-%m-%d %H:%M") if submitted_at else "—",
        })

    return {
        "annotator": display_name,
        "report_period_days": days,
        "total_tasks_worked": total_tasks,
        "total_frames_completed": total_frames,
        "total_labels_created": total_labels,
        "active_time_seconds": total_time,
        "active_time_formatted": fmt(total_time),
        "avg_time_per_task_seconds": avg_time_per_task,
        "avg_time_per_task_formatted": fmt(int(avg_time_per_task)),
        "avg_time_per_frame_seconds": avg_time_per_frame,
        "avg_time_per_frame_formatted": fmt(int(avg_time_per_frame)),
        "avg_time_per_label_seconds": avg_time_per_label,
        "avg_time_per_label_formatted": fmt(int(avg_time_per_label)),
        "labels_per_hour": labels_per_hour,
        "frames_per_hour": frames_per_hour,
        "acceptance_rate_pct": acceptance_rate,
        "rejection_rate_pct": rejection_rate,
        "rework_count": total_revisions,
        "tasks_submitted": submitted,
        "tasks_accepted": accepted,
        "tasks_rejected": rejected,
        "most_time_consuming_task": slowest.name if slowest else "N/A",
        "most_time_consuming_task_time": fmt(slowest.total_time_seconds) if slowest else "N/A",
        "fastest_task": fastest.name if fastest else "N/A",
        "fastest_task_time": fmt(fastest.total_time_seconds) if fastest else "N/A",
        "task_details": task_details,
    }
