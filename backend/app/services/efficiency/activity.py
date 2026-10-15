"""Activity event logging (single and buffered batch)."""
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    ActivityEvent,
    ActivityEventType,
    TimeSession,
    User,
)
from app.services.efficiency.schemas import (
    ActivityEventRequest,
    ActivityEventResponse,
    BatchActivityRequest,
)


async def log_activity(
    db: AsyncSession, request: ActivityEventRequest, current_user: User
) -> ActivityEventResponse:
    """Log a single activity event."""
    event = ActivityEvent(
        id=uuid_lib.uuid4(),
        user_id=current_user.id,
        task_id=request.task_id,
        session_id=request.session_id,
        event_type=request.event_type,
        event_metadata=request.metadata or {},
    )
    db.add(event)

    if request.session_id:
        session = await db.get(TimeSession, request.session_id)
        if session and session.is_active:
            session.action_count += 1
            session.last_action_at = datetime.utcnow()

            if request.event_type == ActivityEventType.ANNOTATION_CREATE.value:
                session.annotations_created += 1
            elif request.event_type == ActivityEventType.ANNOTATION_UPDATE.value:
                session.annotations_updated += 1
            elif request.event_type == ActivityEventType.ANNOTATION_DELETE.value:
                session.annotations_deleted += 1

    await db.commit()

    return ActivityEventResponse(
        event_id=event.id,
        timestamp=event.timestamp,
    )


async def log_activity_batch(
    db: AsyncSession, request: BatchActivityRequest, current_user: User
) -> dict:
    """Log multiple activity events at once (for buffered logging)."""
    events_logged = 0

    for event_req in request.events:
        event = ActivityEvent(
            id=uuid_lib.uuid4(),
            user_id=current_user.id,
            task_id=event_req.task_id or request.task_id,
            session_id=event_req.session_id or request.session_id,
            event_type=event_req.event_type,
            event_metadata=event_req.metadata or {},
        )
        db.add(event)
        events_logged += 1

    await db.commit()

    return {"events_logged": events_logged}
