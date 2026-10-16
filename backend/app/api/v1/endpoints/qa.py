"""
QA Review API Endpoints with RBAC protection.

Provides endpoints for:
- QA review session management
- Annotation reviews (approve/reject/flag)
- Comments on annotations
- AI-generated suggestions

Business logic lives in ``app.services.qa_service``; this module only handles
authentication/authorization dependencies and HTTP status mapping.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Permission, User
from app.schemas.schemas import (
    AnnotationCommentCreate,
    AnnotationCommentResponse,
    AnnotationCommentUpdate,
    AnnotationReviewCreate,
    AnnotationReviewResponse,
    BulkAnnotationReviewCreate,
    BulkAnnotationReviewResponse,
    CreateManualSuggestionRequest,
    DismissSuggestionRequest,
    QAReviewComplete,
    QAReviewCreate,
    QAReviewResponse,
    QAReviewUpdate,
    QASuggestionResponse,
    QATaskStats,
    ResolveCommentRequest,
)
from app.services import qa_service
from app.services.qa_service import QANotFoundError, QAValidationError
from app.services.rbac_service import (
    RequirePermissions,
)

router = APIRouter(prefix="/qa", tags=["qa"])


def _http_for_qa_error(exc: Exception) -> HTTPException:
    if isinstance(exc, QANotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, QAValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("/reviews", response_model=QAReviewResponse)
async def start_qa_review(
    review_data: QAReviewCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Start a new QA review session for a task. Requires QA_REVIEW permission."""
    try:
        return await qa_service.start_review(db, review_data, current_user)
    except (QANotFoundError, QAValidationError) as exc:
        raise _http_for_qa_error(exc)


@router.get("/reviews/{review_id}", response_model=QAReviewResponse)
async def get_qa_review(
    review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    db: AsyncSession = Depends(get_db),
):
    """Get a QA review session by ID. Requires QA_ISSUES_READ permission."""
    try:
        return await qa_service.get_review(db, review_id)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.get("/tasks/{task_id}/reviews", response_model=list[QAReviewResponse])
async def get_task_reviews(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all QA reviews for a task. Requires QA_ISSUES_READ permission."""
    return await qa_service.list_task_reviews(db, task_id, status_filter=status)


@router.get("/tasks/{task_id}/active-review", response_model=QAReviewResponse | None)
async def get_active_review(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    db: AsyncSession = Depends(get_db),
    review_stage: str | None = None,
):
    """Get the active QA review for a task, if any. Requires QA_ISSUES_READ permission.

    If review_stage is provided, only returns active reviews for that specific stage.
    This is important for separating QA reviews from Customer QA reviews.
    """
    return await qa_service.get_active_review(db, task_id, review_stage)


@router.patch("/reviews/{review_id}", response_model=QAReviewResponse)
async def update_qa_review(
    review_id: uuid.UUID,
    update_data: QAReviewUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Update a QA review session. Requires QA_REVIEW permission."""
    try:
        return await qa_service.update_review(db, review_id, update_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/reviews/{review_id}/complete", response_model=QAReviewResponse)
async def complete_qa_review(
    review_id: uuid.UUID,
    complete_data: QAReviewComplete,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Complete a QA review session. Requires QA_REVIEW permission."""
    try:
        return await qa_service.complete_review(db, review_id, complete_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/reviews/{review_id}/pause", response_model=QAReviewResponse)
async def pause_qa_review(
    review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Pause a QA review session. Requires QA_REVIEW permission."""
    try:
        return await qa_service.pause_review(db, review_id)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/reviews/{review_id}/resume", response_model=QAReviewResponse)
async def resume_qa_review(
    review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused QA review session. Requires QA_REVIEW permission."""
    try:
        return await qa_service.resume_review(db, review_id)
    except (QANotFoundError, QAValidationError) as exc:
        raise _http_for_qa_error(exc)


@router.post("/reviews/{review_id}/annotations", response_model=AnnotationReviewResponse)
async def review_annotation(
    review_id: uuid.UUID,
    review_data: AnnotationReviewCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Review a specific annotation. Requires QA_ISSUES_CREATE permission."""
    try:
        return await qa_service.review_annotation(db, review_id, review_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/reviews/{review_id}/annotations/bulk", response_model=BulkAnnotationReviewResponse)
async def bulk_review_annotations(
    review_id: uuid.UUID,
    bulk_data: BulkAnnotationReviewCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Bulk review multiple annotations. Requires QA_ISSUES_CREATE permission."""
    try:
        return await qa_service.bulk_review_annotations(db, review_id, bulk_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.get("/reviews/{review_id}/annotations", response_model=list[AnnotationReviewResponse])
async def get_annotation_reviews(
    review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    verdict: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all annotation reviews for a QA review session. Requires QA_ISSUES_READ permission."""
    return await qa_service.list_annotation_reviews(db, review_id, verdict)


@router.get("/annotations/{annotation_id}/review", response_model=AnnotationReviewResponse | None)
async def get_annotation_review_status(
    annotation_id: str,
    qa_review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    db: AsyncSession = Depends(get_db),
):
    """Get review status for a specific annotation. Requires QA_ISSUES_READ permission."""
    return await qa_service.get_annotation_review_status(
        db, annotation_id, qa_review_id
    )


@router.post(
    "/annotation-reviews/{review_id}/resolve",
    response_model=AnnotationReviewResponse,
)
async def resolve_annotation_review(
    review_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_UPDATE))],
    db: AsyncSession = Depends(get_db),
):
    """Annotator marks an issue as fixed during a revision round.

    One-way: an issue cannot be unresolved through this endpoint. The
    task's Submit button on the frontend is blocked until every issue
    on the task has annotator_resolved=true.

    Requires ANNOTATIONS_UPDATE because it's the annotator (not the
    reviewer) acknowledging their fix.
    """
    try:
        return await qa_service.resolve_annotation_review(db, review_id)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/comments", response_model=AnnotationCommentResponse)
async def create_comment(
    comment_data: AnnotationCommentCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Create a comment on an annotation. Requires QA_ISSUES_CREATE permission."""
    return await qa_service.create_comment(db, comment_data)


@router.get("/annotations/{annotation_id}/comments", response_model=list[AnnotationCommentResponse])
async def get_annotation_comments(
    annotation_id: str,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    include_resolved: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Get comments for an annotation. Requires QA_ISSUES_READ permission."""
    return await qa_service.list_annotation_comments(
        db, annotation_id, include_resolved
    )


@router.patch("/comments/{comment_id}", response_model=AnnotationCommentResponse)
async def update_comment(
    comment_id: uuid.UUID,
    update_data: AnnotationCommentUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Update a comment. Requires QA_ISSUES_CREATE permission."""
    try:
        return await qa_service.update_comment(db, comment_id, update_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    """Delete a comment. Requires QA_ISSUES_CREATE permission."""
    try:
        return await qa_service.delete_comment(db, comment_id)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/comments/{comment_id}/resolve", response_model=AnnotationCommentResponse)
async def resolve_comment(
    comment_id: uuid.UUID,
    resolve_data: ResolveCommentRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Resolve or unresolve a comment thread. Requires QA_REVIEW permission."""
    try:
        return await qa_service.resolve_comment(db, comment_id, resolve_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.get("/tasks/{task_id}/suggestions", response_model=list[QASuggestionResponse])
async def get_task_suggestions(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    include_dismissed: bool = False,
    severity: str | None = None,
    suggestion_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get AI suggestions for a task. Requires QA_ISSUES_READ permission."""
    return await qa_service.list_task_suggestions(
        db, task_id, include_dismissed, severity, suggestion_type
    )


@router.post("/suggestions/manual", response_model=QASuggestionResponse)
async def create_manual_suggestion(
    request: CreateManualSuggestionRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Create a manual QA suggestion (e.g., false negative flag).

    Used when QA reviewer identifies a missing annotation in the point cloud.
    Requires QA_REVIEW permission.
    """
    try:
        return await qa_service.create_manual_suggestion(db, request, current_user)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=QASuggestionResponse)
async def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    dismiss_data: DismissSuggestionRequest,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a QA suggestion. Requires QA_REVIEW permission."""
    try:
        return await qa_service.dismiss_suggestion(db, suggestion_id, dismiss_data)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.delete("/suggestions/{suggestion_id}")
async def delete_suggestion(
    suggestion_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_REVIEW))],
    db: AsyncSession = Depends(get_db),
):
    """Delete a suggestion. Requires QA_REVIEW permission."""
    try:
        return await qa_service.delete_suggestion(db, suggestion_id)
    except QANotFoundError as exc:
        raise _http_for_qa_error(exc)


@router.get("/tasks/{task_id}/stats", response_model=QATaskStats)
async def get_task_qa_stats(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.QA_ISSUES_READ))],
    db: AsyncSession = Depends(get_db),
):
    """Get QA statistics for a task. Requires QA_ISSUES_READ permission."""
    return await qa_service.get_task_stats(db, task_id)
