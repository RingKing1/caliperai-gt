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
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import (
    Permission,
    User,
)
from app.services.efficiency import achievements as achievement_service
from app.services.efficiency import activity as activity_service
from app.services.efficiency import alerts as alert_service
from app.services.efficiency import challenges as challenge_service
from app.services.efficiency import goals as goal_service
from app.services.efficiency import reports as report_service
from app.services.efficiency import sessions as session_service
from app.services.efficiency import stats as stats_service
from app.services.efficiency.errors import (
    EfficiencyForbiddenError,
    EfficiencyNotFoundError,
    EfficiencyValidationError,
)
from app.services.efficiency.schemas import (
    AchievementResponse,
    ActivityEventRequest,
    ActivityEventResponse,
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
    SessionEndRequest,
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
    TeamChallengeResponse,
    TeamMemberStats,
    UserGoalCreate,
    UserGoalResponse,
)
from app.services.rbac_service import RequirePermissions, get_current_user

router = APIRouter()




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


# ---------------------------------------------------------------------------
# Achievements (services/efficiency/achievements.py)
# ---------------------------------------------------------------------------


@router.get("/achievements/my", response_model=List[AchievementResponse])
async def get_my_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> List[AchievementResponse]:
    """Get current user's achievements."""
    return await achievement_service.list_my_achievements(db, current_user)


@router.get("/achievements/unseen", response_model=List[AchievementResponse])
async def get_unseen_achievements(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> List[AchievementResponse]:
    """Get current user's unseen achievements for notification purposes."""
    return await achievement_service.list_unseen_achievements(db, current_user)


@router.post("/achievements/{achievement_id}/mark-seen")
async def mark_achievement_seen(
    achievement_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark an achievement as seen."""
    try:
        return await achievement_service.mark_achievement_seen(
            db, achievement_id, current_user
        )
    except (EfficiencyNotFoundError, EfficiencyForbiddenError) as exc:
        raise _http_for_efficiency_error(exc)


# ---------------------------------------------------------------------------
# Efficiency analytics (business logic in services/efficiency/stats.py)
# ---------------------------------------------------------------------------


@router.get("/stats/my", response_model=EfficiencyStats)
async def get_my_efficiency_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    days: int = Query(
        1, description="Number of days for the period (1=today, 7=week, etc.)"
    ),
) -> EfficiencyStats:
    """Get personal efficiency statistics for a given period."""
    return await stats_service.get_my_stats(db, current_user, organization_id, days)


@router.get("/live/team", response_model=List[LiveUserStatus])
async def get_team_live_status(
    current_user: Annotated[
        User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))
    ],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
) -> List[LiveUserStatus]:
    """Get real-time status of team members."""
    return await stats_service.get_team_live_status(db, current_user, organization_id)


@router.get("/team-stats", response_model=List[TeamMemberStats])
async def get_team_stats(
    current_user: Annotated[
        User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))
    ],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    dataset_id: Optional[UUID] = Query(None),
    campaign_id: Optional[UUID] = Query(None),
    period: str = Query("today", enum=["today", "week", "month"]),
) -> List[TeamMemberStats]:
    """Get per-member annotation, workflow and quality stats for the team."""
    return await stats_service.get_team_stats(
        db, current_user, organization_id, dataset_id, campaign_id, period
    )


@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    period: str = Query("week", enum=["today", "week", "month", "all_time"]),
    limit: int = Query(10, ge=1, le=100),
) -> List[LeaderboardEntry]:
    """Get leaderboard for the organization."""
    return await stats_service.get_leaderboard(
        db, current_user, organization_id, period, limit
    )


# ---------------------------------------------------------------------------
# Performance alerts (services/efficiency/alerts.py)
# ---------------------------------------------------------------------------


@router.get("/alerts", response_model=List[PerformanceAlertResponse])
async def get_performance_alerts(
    current_user: Annotated[
        User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))
    ],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    include_acknowledged: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
) -> List[PerformanceAlertResponse]:
    """Get performance alerts for team."""
    return await alert_service.list_alerts(
        db, current_user, organization_id, include_acknowledged, limit
    )


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID,
    current_user: Annotated[
        User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_TEAM))
    ],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge a performance alert."""
    try:
        return await alert_service.acknowledge_alert(db, alert_id, current_user)
    except EfficiencyNotFoundError as exc:
        raise _http_for_efficiency_error(exc)


# ---------------------------------------------------------------------------
# Team challenges (services/efficiency/challenges.py)
# ---------------------------------------------------------------------------


@router.get("/challenges", response_model=List[TeamChallengeResponse])
async def get_challenges(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    include_completed: bool = Query(False),
) -> List[TeamChallengeResponse]:
    """Get team challenges with live progress from annotation counts."""
    return await challenge_service.list_challenges(
        db, current_user, organization_id, include_completed
    )


@router.post("/challenges", response_model=TeamChallengeResponse)
async def create_challenge(
    request: CreateChallengeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TeamChallengeResponse:
    """Create a new team challenge."""
    try:
        return await challenge_service.create_challenge(db, request, current_user)
    except EfficiencyValidationError as exc:
        raise _http_for_efficiency_error(exc)


@router.put("/challenges/{challenge_id}", response_model=TeamChallengeResponse)
async def update_challenge(
    challenge_id: UUID,
    request: CreateChallengeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> TeamChallengeResponse:
    """Update a team challenge."""
    try:
        return await challenge_service.update_challenge(
            db, challenge_id, request, current_user
        )
    except (EfficiencyNotFoundError, EfficiencyForbiddenError) as exc:
        raise _http_for_efficiency_error(exc)


@router.delete("/challenges/{challenge_id}")
async def delete_challenge(
    challenge_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a team challenge."""
    try:
        return await challenge_service.delete_challenge(
            db, challenge_id, current_user
        )
    except (EfficiencyNotFoundError, EfficiencyForbiddenError) as exc:
        raise _http_for_efficiency_error(exc)


# ---------------------------------------------------------------------------
# Team member reports (business logic in services/efficiency/reports.py)
# ---------------------------------------------------------------------------


@router.get("/team-member-report/{user_id}")
async def get_team_member_report(
    user_id: UUID,
    current_user: Annotated[
        User, Depends(RequirePermissions(Permission.DASHBOARD_VIEW_GLOBAL))
    ],
    db: AsyncSession = Depends(get_db),
    organization_id: Optional[UUID] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """Return full stats for one team member as a JSON dict for CSV export."""
    try:
        return await report_service.get_team_member_report(
            db, user_id, organization_id, days
        )
    except EfficiencyNotFoundError as exc:
        raise _http_for_efficiency_error(exc)
