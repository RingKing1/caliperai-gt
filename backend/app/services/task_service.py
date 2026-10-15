"""Task domain service: lifecycle, queries and editor bootstrap payloads.

Extracted from ``app/api/v1/endpoints/tasks.py`` so endpoints stay thin
(auth + HTTP mapping). Functions here raise plain domain exceptions
(:class:`TaskNotFoundError` / :class:`TaskForbiddenError` /
:class:`TaskValidationError`) instead of ``HTTPException``; the endpoints
translate them. The RBAC helper :func:`require_permission` already maps to
HTTP 403 itself.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from asyncpg import Range as PgRange
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Campaign,
    Dataset,
    Frame,
    QAReview,
    Scene,
    Task,
    TaskAssignmentHistory,
    TaskStage,
    TaskStageHistory,
    TaskStatus,
    Taxonomy,
    User,
    dataset_taxonomy_association,
)
from app.schemas.schemas import TaskCreate, TaskStatusUpdate, TaskUpdate
from app.services.organization_service import get_user_accessible_organization_ids
from app.services.rbac_service import Permission, require_permission

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class TaskServiceError(Exception):
    """Base class for task-domain errors."""


class TaskNotFoundError(TaskServiceError):
    def __init__(self, task_id: Any = "", message: str | None = None):
        self.task_id = task_id
        super().__init__(message or f"Task {task_id} not found")


class TaskForbiddenError(TaskServiceError):
    pass


class TaskValidationError(TaskServiceError):
    pass


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def frame_range_to_postgres(start: int, end: int) -> PgRange:
    """Convert inclusive frame range to PostgreSQL ``INT4RANGE`` [start, end+1)."""
    return PgRange(start, end + 1)


def compute_frame_window(
    frame_range: PgRange,
    context_before: int,
    context_after: int,
    include_context: bool,
) -> tuple[int, int]:
    """Inclusive ``(start, end)`` frame indexes to load for a task."""
    if include_context:
        return (
            max(0, frame_range.lower - context_before),
            (frame_range.upper - 1) + context_after,
        )
    return frame_range.lower, frame_range.upper - 1


VALID_TRANSITIONS: dict[str, list[str]] = {
    TaskStatus.PENDING.value: [TaskStatus.ASSIGNED.value, TaskStatus.IN_PROGRESS.value],
    TaskStatus.ASSIGNED.value: [TaskStatus.IN_PROGRESS.value, TaskStatus.PENDING.value],
    TaskStatus.IN_PROGRESS.value: [TaskStatus.SUBMITTED.value],
    TaskStatus.SUBMITTED.value: [TaskStatus.ACCEPTED.value, TaskStatus.REJECTED.value],
    TaskStatus.REJECTED.value: [TaskStatus.IN_PROGRESS.value],
    TaskStatus.ACCEPTED.value: [],
}


def revision_reset_reason(
    old_stage: str | None,
    new_stage: str | None,
    update_data: dict[str, Any],
    stage_changing: bool,
) -> Optional[str]:
    """Decide which revision/QA reset rule a PATCH hits.

    Returns ``"stage_change"`` / ``"same_stage_annotation"`` /
    ``"explicit_zero"`` / ``None``.
    """
    if stage_changing:
        return "stage_change"
    if new_stage == TaskStage.ANNOTATION.value:
        return "same_stage_annotation"
    if update_data.get("revision_count") == 0:
        return "explicit_zero"
    return None


def is_task_participant(user: User, task: Task) -> bool:
    return (
        task.assignee_id == user.id
        or task.reviewer_id == user.id
        or task.customer_reviewer_id == user.id
    )


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------


async def get_active_task(db: AsyncSession, task_id: UUID) -> Task:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.is_deleted == False)  # noqa: E712
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id)
    return task


def ensure_can_view(user: User, task: Task) -> None:
    if not user.has_permission(Permission.TASKS_READ_ALL) and not is_task_participant(
        user, task
    ):
        raise TaskForbiddenError("You can only view tasks assigned to you")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def get_task(db: AsyncSession, task_id: UUID, user: User) -> Task:
    task = await get_active_task(db, task_id)
    ensure_can_view(user, task)
    return task


async def list_tasks(
    db: AsyncSession,
    user: User,
    *,
    scene_id: Optional[UUID] = None,
    taxonomy_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    assignee_id: Optional[UUID] = None,
    reviewer_id: Optional[UUID] = None,
    my_tasks: bool = False,
    organization_id: Optional[UUID] = None,
    page: int = 1,
    page_size: int = 20,
) -> list[Task]:
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
    query = select(Task).where(
        Task.is_deleted == False,  # noqa: E712
        Task.scene_id.in_(active_scene_subq),
    )

    if not user.is_superuser:
        accessible_org_ids = await get_user_accessible_organization_ids(db, user.id)
        if organization_id:
            if organization_id not in accessible_org_ids:
                from app.services.rbac_service import PermissionDeniedError

                raise PermissionDeniedError(
                    "You do not have access to this organization"
                )
            org_filter = [organization_id]
        else:
            org_filter = accessible_org_ids

        query = query.where(
            Task.scene_id.in_(
                select(Scene.id)
                .join(Dataset, Scene.dataset_id == Dataset.id)
                .join(Campaign, Dataset.campaign_id == Campaign.id)
                .where(
                    Campaign.organization_id.in_(org_filter),
                    Campaign.is_deleted == False,  # noqa: E712
                    Dataset.is_deleted == False,  # noqa: E712
                    Scene.is_deleted == False,  # noqa: E712
                )
            )
        )
    elif organization_id:
        query = query.where(
            Task.scene_id.in_(
                select(Scene.id)
                .join(Dataset, Scene.dataset_id == Dataset.id)
                .join(Campaign, Dataset.campaign_id == Campaign.id)
                .where(
                    Campaign.organization_id == organization_id,
                    Campaign.is_deleted == False,  # noqa: E712
                    Dataset.is_deleted == False,  # noqa: E712
                    Scene.is_deleted == False,  # noqa: E712
                )
            )
        )

    participant_clause = or_(
        Task.assignee_id == user.id,
        Task.reviewer_id == user.id,
        Task.customer_reviewer_id == user.id,
    )
    if not user.has_permission(Permission.TASKS_READ_ALL):
        query = query.where(participant_clause)
    if my_tasks:
        query = query.where(participant_clause)

    if scene_id:
        query = query.where(Task.scene_id == scene_id)
    if taxonomy_id:
        query = query.where(Task.taxonomy_id == taxonomy_id)
    if status_filter:
        query = query.where(Task.status == status_filter)
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    if reviewer_id:
        query = query.where(Task.reviewer_id == reviewer_id)

    query = query.order_by(Task.priority.desc(), Task.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.options(selectinload(Task.taxonomy))

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_tasks_stats(
    db: AsyncSession,
    task_ids: list[UUID],
    taxonomy_id: Optional[UUID] = None,
) -> list[dict]:
    """Per-task label count, frames visited and total frames."""
    ids = task_ids
    if not ids:
        return []

    results: dict[str, dict] = {}
    for tid in [str(i) for i in ids]:
        results[tid] = {
            "task_id": tid,
            "label_count": 0,
            "frames_visited": 0,
            "total_frames": 0,
        }

    for model in [Annotation, Annotation3D, Annotation2D]:
        query = select(
            model.task_id,
            func.count(model.id).label("label_count"),
            func.count(distinct(model.frame_id)).label("frames_visited"),
        ).where(model.task_id.in_(ids))
        if taxonomy_id is not None:
            query = query.where(model.taxonomy_id == taxonomy_id)
        query = query.group_by(model.task_id)
        rows = await db.execute(query)
        for row in rows.all():
            tid = str(row.task_id)
            if tid in results:
                results[tid]["label_count"] += row.label_count
                results[tid]["frames_visited"] = max(
                    results[tid]["frames_visited"], row.frames_visited
                )

    if taxonomy_id is None:
        rows_fusion = await db.execute(
            select(
                AnnotationFusion.task_id,
                func.count(AnnotationFusion.id).label("label_count"),
                func.count(distinct(AnnotationFusion.frame_id)).label(
                    "frames_visited"
                ),
            )
            .where(AnnotationFusion.task_id.in_(ids))
            .group_by(AnnotationFusion.task_id)
        )
        for row in rows_fusion.all():
            tid = str(row.task_id)
            if tid in results:
                results[tid]["label_count"] += row.label_count
                results[tid]["frames_visited"] = max(
                    results[tid]["frames_visited"], row.frames_visited
                )

        rows_4d = await db.execute(
            select(
                Annotation4D.task_id,
                func.count(Annotation4D.id).label("label_count"),
            )
            .where(Annotation4D.task_id.in_(ids))
            .group_by(Annotation4D.task_id)
        )
        for row in rows_4d.all():
            tid = str(row.task_id)
            if tid in results:
                results[tid]["label_count"] += row.label_count

    frame_rows = await db.execute(
        select(Task.id, func.count(Frame.id).label("total_frames"))
        .join(Scene, Task.scene_id == Scene.id)
        .join(Frame, Frame.scene_id == Scene.id)
        .where(Task.id.in_(ids))
        .group_by(Task.id)
    )
    for row in frame_rows.all():
        tid = str(row.id)
        if tid in results:
            results[tid]["total_frames"] = row.total_frames

    return list(results.values())


async def get_editor_context(db: AsyncSession, task_id: UUID, user: User) -> dict:
    """Aggregated editor bootstrap payload (task + scene + dataset + taxonomies)."""
    task = await get_active_task(db, task_id)
    ensure_can_view(user, task)

    scene_result = await db.execute(
        select(Scene)
        .where(Scene.id == task.scene_id, Scene.is_deleted == False)  # noqa: E712
        .options(selectinload(Scene.tasks))
    )
    scene = scene_result.scalar_one_or_none()
    if not scene:
        raise TaskNotFoundError(message=f"Scene {task.scene_id} not found")

    dataset_result = await db.execute(
        select(Dataset)
        .where(Dataset.id == scene.dataset_id)
        .options(selectinload(Dataset.taxonomies))
    )
    dataset = dataset_result.scalar_one_or_none()
    if not dataset or dataset.is_deleted:
        raise TaskNotFoundError(message=f"Dataset {scene.dataset_id} not found")

    taxonomies = [t for t in dataset.taxonomies if not t.is_deleted]

    primary_taxonomies: dict[str, Optional[Taxonomy]] = {}
    for mode in ("fusion_3d", "2d_only"):
        primary_result = await db.execute(
            select(Taxonomy)
            .join(
                dataset_taxonomy_association,
                dataset_taxonomy_association.c.taxonomy_id == Taxonomy.id,
            )
            .where(
                dataset_taxonomy_association.c.dataset_id == dataset.id,
                Taxonomy.annotation_mode == mode,
                dataset_taxonomy_association.c.is_primary == True,  # noqa: E712
                Taxonomy.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        primary_taxonomies[mode] = primary_result.scalar_one_or_none()

    selected_taxonomy = None
    if scene.selected_taxonomy_id:
        selected_taxonomy = await db.get(Taxonomy, scene.selected_taxonomy_id)
        if selected_taxonomy and selected_taxonomy.is_deleted:
            selected_taxonomy = None

    return {
        "task": task,
        "scene": scene,
        "dataset": dataset,
        "taxonomies": taxonomies,
        "primary_taxonomies": primary_taxonomies,
        "selected_taxonomy": selected_taxonomy,
    }


async def get_task_frames(
    db: AsyncSession, task_id: UUID, include_context: bool = True
) -> dict:
    """All frames for a task, flagging context-buffer frames as read-only."""
    task = await get_active_task(db, task_id)
    frame_range = task.frame_range
    start_frame, end_frame = compute_frame_window(
        frame_range,
        task.context_buffer_before,
        task.context_buffer_after,
        include_context,
    )

    frame_result = await db.execute(
        select(Frame)
        .where(
            Frame.scene_id == task.scene_id,
            Frame.frame_index >= start_frame,
            Frame.frame_index <= end_frame,
        )
        .order_by(Frame.frame_index)
    )
    frames = frame_result.scalars().all()

    frames_data = []
    for frame in frames:
        is_context = (
            frame.frame_index < frame_range.lower
            or frame.frame_index >= frame_range.upper
        )
        frames_data.append(
            {
                "id": frame.id,
                "frame_index": frame.frame_index,
                "timestamp": frame.timestamp,
                "ego_pose": frame.ego_pose,
                "file_paths": frame.file_paths,
                "is_context": is_context,
                "is_readonly": is_context,
            }
        )

    return {
        "task_id": task_id,
        "frame_range": {
            "start": frame_range.lower,
            "end": frame_range.upper - 1,
        },
        "context_buffer": {
            "before": task.context_buffer_before,
            "after": task.context_buffer_after,
        },
        "frames": frames_data,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def create_task(db: AsyncSession, task_in: TaskCreate, user: User) -> Task:
    from app.services.workflow_service import WorkflowService

    scene_result = await db.execute(
        select(Scene).where(
            Scene.id == task_in.scene_id,
            Scene.is_deleted == False,  # noqa: E712
        )
    )
    scene = scene_result.scalar_one_or_none()
    if not scene:
        raise TaskNotFoundError(message=f"Scene {task_in.scene_id} not found")

    if task_in.frame_range.end >= scene.frame_count:
        raise TaskValidationError(
            f"Frame range exceeds scene frame count ({scene.frame_count})"
        )

    initial_status = (
        TaskStatus.ASSIGNED.value if task_in.assignee_id else TaskStatus.PENDING.value
    )

    task = Task(
        scene_id=task_in.scene_id,
        taxonomy_id=task_in.taxonomy_id,
        name=task_in.name,
        description=task_in.description,
        status=initial_status,
        assignee_id=task_in.assignee_id,
        assigned_at=datetime.utcnow() if task_in.assignee_id else None,
        frame_range=frame_range_to_postgres(
            task_in.frame_range.start,
            task_in.frame_range.end,
        ),
        context_buffer_before=task_in.context_buffer_before,
        context_buffer_after=task_in.context_buffer_after,
        priority=task_in.priority,
        deadline=task_in.deadline,
        config=task_in.config.model_dump(),
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    if task_in.assignee_id:
        workflow = WorkflowService(db)
        await workflow._record_history(
            task=task,
            from_stage="annotation",
            from_status="pending",
            to_stage="annotation",
            to_status="assigned",
            changed_by_id=user.id,
            reason=f"Task created with assignee {task_in.assignee_id}",
        )

    root_path = scene.storage_paths.get("root")
    if root_path:
        scene_dir = Path(root_path)
        if scene_dir.exists():
            try:
                from app.services.dataset_import import import_scene_annotations

                annotations_3d, annotations_2d = await import_scene_annotations(
                    db=db,
                    scene=scene,
                    scene_dir=scene_dir,
                    task=task,
                )
                if annotations_3d > 0 or annotations_2d > 0:
                    logger.info(
                        f"[TASK-CREATE] Auto-imported {annotations_3d} 3D and "
                        f"{annotations_2d} 2D annotations for task {task.id}"
                    )
            except Exception as e:  # noqa: BLE001 - import never blocks creation
                logger.warning("[TASK-CREATE] Failed to auto-import annotations: %s", e)

    return task


async def update_task(
    db: AsyncSession, task_id: UUID, task_in: TaskUpdate, user: User
) -> Task:
    task = await get_active_task(db, task_id)
    update_data = task_in.model_dump(exclude_unset=True)

    logger.info(
        "[Task Update] task_id=%s, update_data=%s, current_stage=%s, "
        "current_revision_count=%s",
        task_id,
        update_data,
        task.stage,
        task.revision_count,
    )

    old_stage = task.stage
    new_stage = update_data.get("stage")
    stage_changing = new_stage is not None and new_stage != old_stage

    logger.info(
        "[Task Update] old_stage=%s, new_stage=%s, stage_changing=%s",
        old_stage,
        new_stage,
        stage_changing,
    )

    for field, value in update_data.items():
        if value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(task, field, value)

    reset_reason = revision_reset_reason(
        old_stage, new_stage, update_data, stage_changing
    )

    if reset_reason == "stage_change":
        cleared_roles = []
        if task.assignee_id:
            cleared_roles.append(("annotator", task.assignee_id))
        if task.reviewer_id:
            cleared_roles.append(("reviewer", task.reviewer_id))
        if task.customer_reviewer_id:
            cleared_roles.append(("customer_reviewer", task.customer_reviewer_id))

        for role, uid in cleared_roles:
            db.add(
                TaskAssignmentHistory(
                    task_id=task.id,
                    action="stage_change_cleared",
                    user_id=uid,
                    role=role,
                    stage=new_stage,
                    changed_by_id=user.id,
                    reason=f"Stage changed from {old_stage} to {new_stage}",
                )
            )

        db.add(
            TaskStageHistory(
                task_id=task.id,
                from_stage=old_stage,
                from_status=task.status,
                to_stage=new_stage,
                to_status=TaskStatus.PENDING.value,
                changed_by_id=user.id,
                reason=f"Manual stage change from {old_stage} to {new_stage}",
            )
        )

        task.assignee_id = None
        task.assigned_at = None
        task.reviewer_id = None
        task.reviewed_at = None
        task.customer_reviewer_id = None
        task.customer_reviewed_at = None
        task.status = TaskStatus.PENDING.value

        if new_stage == TaskStage.ANNOTATION.value:
            logger.info(
                "[Task Update] Stage changing TO annotation, resetting revision_count"
            )
            task.revision_count = 0
            task.review_notes = None
            task.customer_review_notes = None
            await db.execute(delete(QAReview).where(QAReview.task_id == task.id))

    elif reset_reason == "same_stage_annotation":
        logger.info(
            "[Task Update] Same-stage annotation patch, resetting revision_count"
        )
        task.revision_count = 0
        task.review_notes = None
        task.customer_review_notes = None
        await db.execute(delete(QAReview).where(QAReview.task_id == task.id))

    elif reset_reason == "explicit_zero":
        logger.info("[Task Update] Explicit revision_count=0, resetting")
        task.revision_count = 0
        task.review_notes = None
        task.customer_review_notes = None
        await db.execute(delete(QAReview).where(QAReview.task_id == task.id))
    else:
        logger.info("[Task Update] No revision reset path matched")

    await db.flush()
    await db.refresh(task)
    logger.info("[Task Update] After save: task.revision_count=%s", task.revision_count)
    return task


async def assign_task(db: AsyncSession, task_id: UUID, assignee_id: UUID) -> Task:
    task = await get_active_task(db, task_id)
    if task.status not in [
        TaskStatus.PENDING.value,
        TaskStatus.ASSIGNED.value,
    ]:
        raise TaskValidationError(
            f"Cannot assign task in status '{task.status}'"
        )

    task.assignee_id = assignee_id
    task.assigned_at = datetime.utcnow()
    task.status = TaskStatus.ASSIGNED.value

    await db.flush()
    await db.refresh(task)
    return task


def _authorize_status_transition(
    user: User, task: Task, new_status: str
) -> None:
    if new_status == TaskStatus.IN_PROGRESS.value:
        if task.assignee_id != user.id:
            require_permission(user, Permission.TASKS_UPDATE)
    elif new_status == TaskStatus.SUBMITTED.value:
        if task.assignee_id != user.id:
            require_permission(user, Permission.TASKS_UPDATE)
    elif new_status in [
        TaskStatus.ACCEPTED.value,
        TaskStatus.REJECTED.value,
    ]:
        require_permission(user, Permission.QA_REVIEW)


async def update_task_status(
    db: AsyncSession,
    task_id: UUID,
    status_update: TaskStatusUpdate,
    user: User,
) -> Task:
    task = await get_active_task(db, task_id)
    new_status = (
        status_update.status.value
        if hasattr(status_update.status, "value")
        else status_update.status
    )

    _authorize_status_transition(user, task, new_status)

    if new_status not in VALID_TRANSITIONS.get(task.status, []):
        raise TaskValidationError(
            f"Invalid transition from '{task.status}' to '{new_status}'"
        )

    task.status = new_status

    if new_status == TaskStatus.IN_PROGRESS.value and not task.started_at:
        task.started_at = datetime.utcnow()
    elif new_status == TaskStatus.SUBMITTED.value:
        task.submitted_at = datetime.utcnow()
    elif new_status in [TaskStatus.ACCEPTED.value, TaskStatus.REJECTED.value]:
        task.reviewed_at = datetime.utcnow()
        task.reviewer_id = user.id
        if status_update.review_notes:
            task.review_notes = status_update.review_notes

    await db.flush()
    await db.refresh(task)
    return task


async def soft_delete_task(db: AsyncSession, task_id: UUID) -> None:
    task = await get_active_task(db, task_id)
    task.is_deleted = True
    await db.flush()


async def split_task(
    db: AsyncSession,
    task_id: UUID,
    sub_tasks: list[tuple[str, int, int]],
) -> list[Task]:
    """Split a task into sub-tasks by frame range and redistribute labels."""
    try:
        task = await get_active_task(db, task_id)
    except TaskNotFoundError:
        raise TaskNotFoundError(task_id, message="Task not found")

    if len(sub_tasks) < 2:
        raise TaskValidationError("Provide at least 2 sub-tasks to split into")

    frames_result = await db.execute(
        select(Frame.id, Frame.frame_index).where(Frame.scene_id == task.scene_id)
    )
    frame_index_map: dict = {
        row.id: row.frame_index for row in frames_result.all()
    }

    new_tasks: list[Task] = []
    for name, frame_start, frame_end in sub_tasks:
        new_task = Task(
            scene_id=task.scene_id,
            taxonomy_id=task.taxonomy_id,
            name=name,
            status=TaskStatus.PENDING.value,
            stage=TaskStage.ANNOTATION.value,
            frame_range=frame_range_to_postgres(frame_start, frame_end),
            context_buffer_before=task.context_buffer_before,
            context_buffer_after=task.context_buffer_after,
            priority=task.priority,
            deadline=task.deadline,
            config=task.config,
        )
        db.add(new_task)
        new_tasks.append(new_task)

    await db.flush()

    annotation_models = [
        Annotation,
        Annotation3D,
        Annotation2D,
        AnnotationFusion,
        Annotation4D,
    ]
    for model in annotation_models:
        ann_result = await db.execute(
            select(model).where(model.task_id == task_id)
        )
        for ann in ann_result.scalars().all():
            frame_idx = frame_index_map.get(ann.frame_id)
            if frame_idx is None:
                continue
            for new_task, (_name, frame_start, frame_end) in zip(
                new_tasks, sub_tasks
            ):
                if frame_start <= frame_idx <= frame_end:
                    ann.task_id = new_task.id
                    break

    await db.flush()

    task.is_deleted = True
    await db.flush()

    for new_task in new_tasks:
        await db.refresh(new_task)

    return new_tasks
