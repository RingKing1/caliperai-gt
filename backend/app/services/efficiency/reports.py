"""Per-member efficiency report for CSV export."""
from uuid import UUID

from sqlalchemy import and_, case, desc, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Campaign,
    Dataset,
    Scene,
    Task,
    Taxonomy,
    User,
)
from app.services.efficiency.errors import EfficiencyNotFoundError


def format_duration(secs) -> str:
    """Human-readable duration: '0s', 'Mm Ss' or 'Hh Mm Ss'."""
    if not secs:
        return "0s"
    h, remainder = divmod(secs, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


async def get_team_member_report(
    db: AsyncSession,
    user_id: UUID,
    organization_id: UUID | None,
    days: int,
) -> dict:
    """Return full stats for one team member as a JSON dict for CSV export."""

    user = await db.get(User, user_id)
    if not user:
        raise EfficiencyNotFoundError("User not found")

    display_name = user.full_name or user.username

    base_user_filter = [Task.assignee_id == user_id, Task.is_deleted == False]  # noqa: E712
    if organization_id:
        base_user_filter.append(
            Task.scene_id.in_(
                select(Scene.id)
                .join(Dataset, Scene.dataset_id == Dataset.id)
                .join(Campaign, Dataset.campaign_id == Campaign.id)
                .where(
                    Campaign.organization_id == organization_id,
                    Campaign.is_deleted == False,  # noqa: E712
                )
            )
        )

    task_rows = await db.execute(
        select(
            func.count(Task.id).label("total_tasks"),
            func.sum(Task.total_time_seconds).label("total_time"),
            func.sum(
                func.upper(Task.frame_range) - func.lower(Task.frame_range)
            ).label("total_frames"),
            func.sum(Task.revision_count).label("total_revisions"),
            func.sum(case((Task.status == "accepted", 1), else_=0)).label("accepted"),
            func.sum(case((Task.status == "rejected", 1), else_=0)).label("rejected"),
            func.sum(
                case((Task.status.in_(["submitted", "accepted"]), 1), else_=0)
            ).label("submitted"),
        ).where(and_(*base_user_filter))
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
    avg_time_per_frame = (
        round(total_time / total_frames, 1) if total_frames > 0 else 0.0
    )
    avg_time_per_label = (
        round(total_time / total_labels, 1) if total_labels > 0 else 0.0
    )

    acceptance_rate = (
        round(accepted / total_reviewed * 100, 1) if total_reviewed > 0 else None
    )
    rejection_rate = (
        round(rejected / total_reviewed * 100, 1) if total_reviewed > 0 else None
    )

    slowest_task_row = await db.execute(
        select(Task.name, Task.total_time_seconds)
        .where(and_(*base_user_filter, Task.total_time_seconds > 0))
        .order_by(desc(Task.total_time_seconds))
        .limit(1)
    )
    slowest = slowest_task_row.fetchone()

    fastest_task_row = await db.execute(
        select(Task.name, Task.total_time_seconds)
        .where(and_(*base_user_filter, Task.total_time_seconds > 0))
        .order_by(Task.total_time_seconds)
        .limit(1)
    )
    fastest = fastest_task_row.fetchone()

    active_scene_subq = (
        select(Scene.id)
        .join(Dataset, Scene.dataset_id == Dataset.id)
        .join(Campaign, Dataset.campaign_id == Campaign.id)
        .where(
            Scene.is_deleted == False,  # noqa: E712
            Dataset.is_deleted == False,  # noqa: E712
            Campaign.is_deleted == False,  # noqa: E712
        )
    )
    if organization_id:
        active_scene_subq = active_scene_subq.where(
            Campaign.organization_id == organization_id
        )

    task_filter = [
        Task.assignee_id == user_id,
        Task.is_deleted == False,  # noqa: E712
        Task.scene_id.in_(active_scene_subq),
        or_(
            Task.total_time_seconds > 0,
            Task.started_at.isnot(None),
        ),
    ]

    all_tasks_result = await db.execute(
        select(
            Task.id,
            Task.name,
            Task.status,
            Task.stage,
            Task.total_time_seconds,
            Task.revision_count,
            Task.frame_range,
            Task.assigned_at,
            Task.submitted_at,
            Task.started_at,
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
            q = select(func.count(distinct(model.frame_id))).where(
                model.task_id == task_id
            )
            if tax_id is not None:
                q = q.where(model.taxonomy_id == tax_id)
            frames_visited = max(frames_visited, await db.scalar(q) or 0)

        avg_time_per_frame = (
            round(task_time / frames_visited, 1) if frames_visited > 0 else 0
        )
        started_at = row["started_at"]
        submitted_at = row["submitted_at"] if row["stage"] != "annotation" else None

        task_details.append(
            {
                "task_name": row["name"] or "",
                "taxonomy": tax_name,
                "scene": row["scene_name"] or "",
                "dataset": row["dataset_name"] or "",
                "status": row["status"] or "",
                "stage": row["stage"] or "",
                "total_frames": frame_count,
                "frames_visited": frames_visited,
                "labels_created": task_labels,
                "active_time": format_duration(task_time),
                "avg_time_per_frame": (
                    format_duration(int(avg_time_per_frame))
                    if avg_time_per_frame
                    else "—"
                ),
                "revision_count": row["revision_count"] or 0,
                "start_time": (
                    started_at.strftime("%Y-%m-%d %H:%M") if started_at else ""
                ),
                "end_time": (
                    submitted_at.strftime("%Y-%m-%d %H:%M") if submitted_at else "—"
                ),
            }
        )

    return {
        "annotator": display_name,
        "report_period_days": days,
        "total_tasks_worked": total_tasks,
        "total_frames_completed": total_frames,
        "total_labels_created": total_labels,
        "active_time_seconds": total_time,
        "active_time_formatted": format_duration(total_time),
        "avg_time_per_task_seconds": avg_time_per_task,
        "avg_time_per_task_formatted": format_duration(int(avg_time_per_task)),
        "avg_time_per_frame_seconds": avg_time_per_frame,
        "avg_time_per_frame_formatted": format_duration(int(avg_time_per_frame)),
        "avg_time_per_label_seconds": avg_time_per_label,
        "avg_time_per_label_formatted": format_duration(int(avg_time_per_label)),
        "labels_per_hour": labels_per_hour,
        "frames_per_hour": frames_per_hour,
        "acceptance_rate_pct": acceptance_rate,
        "rejection_rate_pct": rejection_rate,
        "rework_count": total_revisions,
        "tasks_submitted": submitted,
        "tasks_accepted": accepted,
        "tasks_rejected": rejected,
        "most_time_consuming_task": slowest.name if slowest else "N/A",
        "most_time_consuming_task_time": (
            format_duration(slowest.total_time_seconds) if slowest else "N/A"
        ),
        "fastest_task": fastest.name if fastest else "N/A",
        "fastest_task_time": (
            format_duration(fastest.total_time_seconds) if fastest else "N/A"
        ),
        "task_details": task_details,
    }
