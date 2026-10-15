"""Time-tracking sessions: per-task sessions and global login sessions."""
import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    ActivityEvent,
    ActivityEventType,
    Task,
    TimeSession,
    User,
    UserLoginSession,
)
from app.services.efficiency.common import update_daily_stats
from app.services.efficiency.errors import (
    EfficiencyForbiddenError,
    EfficiencyNotFoundError,
    EfficiencyValidationError,
)
from app.services.efficiency.schemas import (
    HeartbeatRequest,
    HeartbeatResponse,
    LoginSessionEndRequest,
    LoginSessionEndResponse,
    LoginSessionHeartbeatRequest,
    LoginSessionHeartbeatResponse,
    LoginSessionStartRequest,
    LoginSessionStartResponse,
    SessionEndRequest,
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
)

_IDLE_THRESHOLD_SECONDS = 180


async def start_session(
    db: AsyncSession, request: SessionStartRequest, current_user: User
) -> SessionStartResponse:
    """Start a new time tracking session for a task."""
    task = await db.get(Task, request.task_id)
    if not task:
        raise EfficiencyNotFoundError("Task not found")

    await db.execute(
        update(TimeSession)
        .where(
            and_(
                TimeSession.user_id == current_user.id,
                TimeSession.task_id == request.task_id,
                TimeSession.is_active == True,  # noqa: E712
            )
        )
        .values(
            is_active=False,
            session_end=datetime.utcnow(),
        )
    )

    session = TimeSession(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        task_id=request.task_id,
        client_info=(
            request.client_info.model_dump() if request.client_info else {}
        ),
    )
    db.add(session)

    event = ActivityEvent(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        task_id=request.task_id,
        session_id=session.id,
        event_type=ActivityEventType.SESSION_START.value,
        metadata={"client_info": session.client_info},
    )
    db.add(event)

    await db.commit()

    return SessionStartResponse(
        session_id=session.id,
        started_at=session.session_start,
        message="Session started successfully",
    )


async def session_heartbeat(
    db: AsyncSession, request: HeartbeatRequest, current_user: User
) -> HeartbeatResponse:
    """Heartbeat to keep a task session alive."""
    session = await db.get(TimeSession, request.session_id)
    if not session:
        raise EfficiencyNotFoundError("Session not found")
    if session.user_id != current_user.id:
        raise EfficiencyForbiddenError("Not your session")
    if not session.is_active:
        raise EfficiencyValidationError("Session already ended")

    now = datetime.utcnow()
    time_since_last = (now - session.last_heartbeat_at).total_seconds()

    if time_since_last > _IDLE_THRESHOLD_SECONDS:
        session.idle_duration_seconds += int(time_since_last)
        if not session.is_idle:
            event = ActivityEvent(
                id=uuid_lib.uuid4(),
                user_id=current_user.id,
                task_id=session.task_id,
                session_id=session.id,
                event_type=ActivityEventType.SESSION_PAUSE.value,
            )
            db.add(event)
        session.is_idle = True
    else:
        if request.is_active:
            session.active_duration_seconds += int(min(time_since_last, 30))
            if session.is_idle:
                event = ActivityEvent(
                    id=uuid_lib.uuid4(),
                    user_id=current_user.id,
                    task_id=session.task_id,
                    session_id=session.id,
                    event_type=ActivityEventType.SESSION_RESUME.value,
                )
                db.add(event)
            session.is_idle = False
        else:
            session.idle_duration_seconds += int(min(time_since_last, 30))
            session.is_idle = True

    session.heartbeat_count += 1
    session.last_heartbeat_at = now

    if request.current_frame is not None:
        session.frames_visited += 1

    await db.commit()

    return HeartbeatResponse(
        session_id=session.id,
        active_duration_seconds=session.active_duration_seconds,
        idle_duration_seconds=session.idle_duration_seconds,
        is_idle=session.is_idle,
    )


async def end_session(
    db: AsyncSession, request: SessionEndRequest, current_user: User
) -> SessionEndResponse:
    """End a time tracking session."""
    session = await db.get(TimeSession, request.session_id)
    if not session:
        raise EfficiencyNotFoundError("Session not found")
    if session.user_id != current_user.id:
        raise EfficiencyForbiddenError("Not your session")

    now = datetime.utcnow()

    if session.is_active:
        time_since_last = (now - session.last_heartbeat_at).total_seconds()
        if time_since_last < _IDLE_THRESHOLD_SECONDS:
            session.active_duration_seconds += int(min(time_since_last, 30))

    session.is_active = False
    session.session_end = now

    event = ActivityEvent(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        task_id=session.task_id,
        session_id=session.id,
        event_type=ActivityEventType.SESSION_END.value,
        metadata={
            "active_seconds": session.active_duration_seconds,
            "idle_seconds": session.idle_duration_seconds,
            "action_count": session.action_count,
        },
    )
    db.add(event)

    await update_daily_stats(
        db,
        current_user.id,
        active_time_seconds=session.active_duration_seconds,
        idle_time_seconds=session.idle_duration_seconds,
    )

    task = await db.get(Task, session.task_id)
    if task:
        task.total_time_seconds += session.active_duration_seconds

    await db.commit()

    return SessionEndResponse(
        session_id=session.id,
        total_active_seconds=session.active_duration_seconds,
        total_idle_seconds=session.idle_duration_seconds,
        action_count=session.action_count,
    )


async def start_login_session(
    db: AsyncSession,
    request: LoginSessionStartRequest,
    current_user: User,
) -> LoginSessionStartResponse:
    """Start (or reconnect to) the global login session."""
    now = datetime.now(timezone.utc)

    existing_result = await db.execute(
        select(UserLoginSession).where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.is_active == True,  # noqa: E712
            )
        )
    )
    existing_session = existing_result.scalar_one_or_none()

    if existing_session:
        return LoginSessionStartResponse(
            session_id=existing_session.id,
            started_at=existing_session.session_start,
            message="Reconnected to existing session",
        )

    client_info_dict = {}
    if request.client_info:
        client_info_dict = {
            "browser": request.client_info.browser,
            "os": request.client_info.os,
            "screen_resolution": request.client_info.screen_resolution,
            "timezone": request.client_info.timezone,
        }

    session = UserLoginSession(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        organization_id=request.organization_id,
        session_start=now,
        last_heartbeat_at=now,
        last_active_at=now,
        is_active=True,
        is_window_focused=True,
        is_mouse_in_window=True,
        active_duration_seconds=0,
        idle_duration_seconds=0,
        heartbeat_count=0,
        client_info=client_info_dict,
    )
    db.add(session)
    await db.commit()

    return LoginSessionStartResponse(
        session_id=session.id,
        started_at=session.session_start,
        message="Login session started",
    )


async def login_session_heartbeat(
    db: AsyncSession,
    request: LoginSessionHeartbeatRequest,
    current_user: User,
) -> LoginSessionHeartbeatResponse:
    """Heartbeat for a global login session."""
    session = await db.get(UserLoginSession, request.session_id)
    if not session:
        raise EfficiencyNotFoundError("Login session not found")
    if session.user_id != current_user.id:
        raise EfficiencyForbiddenError("Not your session")
    if not session.is_active:
        raise EfficiencyValidationError("Session already ended")

    now = datetime.now(timezone.utc)
    time_since_last_heartbeat = (
        now - session.last_heartbeat_at
    ).total_seconds()

    time_to_add = min(time_since_last_heartbeat, 60)

    is_truly_active = (
        request.is_window_focused
        and request.is_mouse_in_window
        and request.is_active
    )

    if is_truly_active:
        session.active_duration_seconds += int(time_to_add)
        session.last_active_at = now
    else:
        session.idle_duration_seconds += int(time_to_add)

    session.last_heartbeat_at = now
    session.heartbeat_count += 1
    session.is_window_focused = request.is_window_focused
    session.is_mouse_in_window = request.is_mouse_in_window

    await db.commit()

    total_session_seconds = int(
        (now - session.session_start).total_seconds()
    )

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_sessions_result = await db.execute(
        select(func.sum(UserLoginSession.active_duration_seconds)).where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.session_start >= today_start,
            )
        )
    )
    today_active_seconds = today_sessions_result.scalar() or 0

    return LoginSessionHeartbeatResponse(
        session_id=session.id,
        active_duration_seconds=session.active_duration_seconds,
        idle_duration_seconds=session.idle_duration_seconds,
        total_session_seconds=total_session_seconds,
        today_active_seconds=int(today_active_seconds),
    )


async def end_login_session(
    db: AsyncSession,
    request: LoginSessionEndRequest,
    current_user: User,
) -> LoginSessionEndResponse:
    """End a global login session."""
    session = await db.get(UserLoginSession, request.session_id)
    if not session:
        raise EfficiencyNotFoundError("Login session not found")
    if session.user_id != current_user.id:
        raise EfficiencyForbiddenError("Not your session")

    now = datetime.now(timezone.utc)

    if session.is_active:
        time_since_last = (now - session.last_heartbeat_at).total_seconds()
        if time_since_last < 60:
            if session.is_window_focused and session.is_mouse_in_window:
                session.active_duration_seconds += int(time_since_last)
            else:
                session.idle_duration_seconds += int(time_since_last)

    session.is_active = False
    session.session_end = now

    await db.commit()

    total_session_seconds = int(
        (now - session.session_start).total_seconds()
    )

    return LoginSessionEndResponse(
        session_id=session.id,
        total_active_seconds=session.active_duration_seconds,
        total_idle_seconds=session.idle_duration_seconds,
        total_session_seconds=total_session_seconds,
    )


async def get_current_login_session(db: AsyncSession, current_user: User) -> dict:
    """Get the current active login session for the user."""
    result = await db.execute(
        select(UserLoginSession)
        .where(
            and_(
                UserLoginSession.user_id == current_user.id,
                UserLoginSession.is_active == True,  # noqa: E712
            )
        )
        .order_by(UserLoginSession.session_start.desc())
    )
    session = result.scalar_one_or_none()

    if not session:
        return {"session": None, "message": "No active login session"}

    now = datetime.now(timezone.utc)
    total_session_seconds = int(
        (now - session.session_start).total_seconds()
    )

    return {
        "session_id": session.id,
        "started_at": session.session_start,
        "active_duration_seconds": session.active_duration_seconds,
        "idle_duration_seconds": session.idle_duration_seconds,
        "total_session_seconds": total_session_seconds,
        "is_window_focused": session.is_window_focused,
        "is_mouse_in_window": session.is_mouse_in_window,
    }
