"""Performance alerts for team dashboards."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import PerformanceAlert, User
from app.services.efficiency.common import get_display_name
from app.services.efficiency.errors import EfficiencyNotFoundError
from app.services.efficiency.schemas import PerformanceAlertResponse


async def list_alerts(
    db: AsyncSession,
    current_user: User,
    organization_id: UUID | None = None,
    include_acknowledged: bool = False,
    limit: int = 50,
) -> list[PerformanceAlertResponse]:
    """Get performance alerts for team."""
    query = (
        select(PerformanceAlert, User)
        .join(User, PerformanceAlert.user_id == User.id)
        .order_by(desc(PerformanceAlert.created_at))
        .limit(limit)
    )

    if not include_acknowledged:
        query = query.where(PerformanceAlert.is_acknowledged == False)  # noqa: E712

    result = await db.execute(query)
    alerts = result.all()

    responses = []
    for alert, user in alerts:
        display_name = await get_display_name(
            db, user, current_user, organization_id
        )
        responses.append(
            PerformanceAlertResponse(
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
            )
        )

    return responses


async def acknowledge_alert(
    db: AsyncSession, alert_id: UUID, current_user: User
) -> dict:
    """Acknowledge a performance alert."""
    alert = await db.get(PerformanceAlert, alert_id)
    if not alert:
        raise EfficiencyNotFoundError("Alert not found")

    alert.is_acknowledged = True
    alert.acknowledged_by_id = current_user.id
    alert.acknowledged_at = datetime.utcnow()

    await db.commit()

    return {"status": "acknowledged"}
