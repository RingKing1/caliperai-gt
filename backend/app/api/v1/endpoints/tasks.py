"""
Task endpoints - Core workflow management with RBAC protection.

Business logic lives in ``app.services.task_service``; this module only
handles authentication/authorization dependencies and HTTP status mapping.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Permission, Task, User
from app.schemas.schemas import (
    SplitTaskRequest,
    TaskAssignment,
    TaskCreate,
    TaskEditorContextResponse,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)
from app.services import task_service
from app.services.rbac_service import (
    RequirePermissions,
    get_current_user,
)
from app.services.task_service import (
    TaskForbiddenError,
    TaskNotFoundError,
    TaskValidationError,
)

router = APIRouter()


def _http_for_task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaskNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TaskForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, TaskValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.get("/{task_id}/editor-context", response_model=TaskEditorContextResponse)
async def get_task_editor_context(
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated editor bootstrap payload (task + scene + dataset + taxonomies)."""
    try:
        return await task_service.get_editor_context(db, task_id, current_user)
    except (TaskNotFoundError, TaskForbiddenError) as exc:
        raise _http_for_task_error(exc)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Create a new annotation task. Requires TASKS_CREATE permission."""
    try:
        return await task_service.create_task(db, task_in, current_user)
    except (TaskNotFoundError, TaskValidationError) as exc:
        raise _http_for_task_error(exc)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    scene_id: Optional[UUID] = None,
    taxonomy_id: Optional[UUID] = Query(None, description="Filter by taxonomy"),
    status: Optional[str] = None,
    assignee_id: Optional[UUID] = None,
    reviewer_id: Optional[UUID] = None,
    my_tasks: bool = Query(False, description="Return tasks where I am assignee/reviewer"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Task]:
    """List tasks with organization/assignment scoping and filters."""
    try:
        return await task_service.list_tasks(
            db,
            current_user,
            scene_id=scene_id,
            taxonomy_id=taxonomy_id,
            status_filter=status,
            assignee_id=assignee_id,
            reviewer_id=reviewer_id,
            my_tasks=my_tasks,
            organization_id=organization_id,
            page=page,
            page_size=page_size,
        )
    except TaskForbiddenError as exc:
        raise _http_for_task_error(exc)


@router.get("/stats", response_model=list[dict])
async def get_tasks_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    task_ids: str = Query(..., description="Comma-separated task IDs"),
    taxonomy_id: Optional[UUID] = Query(None, description="Filter counts by taxonomy"),
    db: AsyncSession = Depends(get_db),
):
    """Per-task label count, frames visited, and total frames."""
    ids = [UUID(t.strip()) for t in task_ids.split(",") if t.strip()]
    return await task_service.get_tasks_stats(db, ids, taxonomy_id)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Get a task by ID (assignees see their tasks; PM/Admin see all)."""
    try:
        return await task_service.get_task(db, task_id, current_user)
    except (TaskNotFoundError, TaskForbiddenError) as exc:
        raise _http_for_task_error(exc)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    task_in: TaskUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Update a task (stage changes reset assignments and QA state)."""
    try:
        return await task_service.update_task(db, task_id, task_in, current_user)
    except TaskNotFoundError as exc:
        raise _http_for_task_error(exc)


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: UUID,
    assignment: TaskAssignment,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_ASSIGN))],
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Assign a task to a user."""
    try:
        return await task_service.assign_task(db, task_id, assignment.assignee_id)
    except (TaskNotFoundError, TaskValidationError) as exc:
        raise _http_for_task_error(exc)


@router.post("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: UUID,
    status_update: TaskStatusUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Task state-machine transition; permission depends on the transition."""
    try:
        return await task_service.update_task_status(
            db, task_id, status_update, current_user
        )
    except (TaskNotFoundError, TaskValidationError) as exc:
        raise _http_for_task_error(exc)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_DELETE))],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a task."""
    try:
        await task_service.soft_delete_task(db, task_id)
    except TaskNotFoundError as exc:
        raise _http_for_task_error(exc)


@router.get("/{task_id}/frames")
async def get_task_frames(
    task_id: UUID,
    include_context: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """All frames for a task including context-buffer frames."""
    try:
        return await task_service.get_task_frames(db, task_id, include_context)
    except TaskNotFoundError as exc:
        raise _http_for_task_error(exc)


@router.post("/{task_id}/split", response_model=list[TaskResponse])
async def split_task(
    task_id: UUID,
    body: SplitTaskRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> list[Task]:
    """Split a task into sub-tasks by frame range, redistributing annotations."""
    try:
        return await task_service.split_task(
            db,
            task_id,
            [(s.name, s.frame_start, s.frame_end) for s in body.sub_tasks],
        )
    except (TaskNotFoundError, TaskValidationError) as exc:
        raise _http_for_task_error(exc)
