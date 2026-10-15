"""QA domain service: review sessions, annotation verdicts, comments, suggestions.

Extracted from ``app/api/v1/endpoints/qa.py`` so endpoints stay thin
(auth + HTTP mapping). Functions raise plain domain exceptions
(:class:`QANotFoundError` / :class:`QAValidationError`) instead of
``HTTPException``; the endpoints translate them.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    AnnotationComment,
    AnnotationReview,
    QAReview,
    QAReviewStatus,
    QASuggestion,
    ReviewVerdict,
    Task,
    TaskStage,
    TaskStatus,
    User,
)
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
    QAReviewSummary,
    QAReviewUpdate,
    QASuggestionResponse,
    QATaskStats,
    ResolveCommentRequest,
)

# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class QAServiceError(Exception):
    """Base class for QA-domain errors."""


class QANotFoundError(QAServiceError):
    def __init__(self, kind: str, entity_id: Any = ""):
        self.kind = kind
        self.entity_id = entity_id
        super().__init__(f"{kind} not found" if not entity_id else f"{kind} {entity_id} not found")


class QAValidationError(QAServiceError):
    pass


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------

SUGGESTION_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def next_stage_after_qa(
    current_stage: Optional[str], skip_customer_qa: bool
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(next_stage, next_status)`` when a QA review completes.

    Returns ``(None, None)`` when the task is in an unexpected stage (the
    task's stage/status is then left untouched). Outcome is always
    ``"accepted"`` historically.
    """
    if current_stage == TaskStage.QA.value:
        if skip_customer_qa:
            return TaskStage.ACCEPTED.value, TaskStatus.ACCEPTED.value
        return TaskStage.CUSTOMER_QA.value, TaskStatus.IN_PROGRESS.value
    if current_stage == TaskStage.CUSTOMER_QA.value:
        return TaskStage.ACCEPTED.value, TaskStatus.ACCEPTED.value
    return None, None


def sort_suggestions(suggestions: list[QASuggestion]) -> list[QASuggestion]:
    """Order suggestions by severity (unknown severity defaults to medium)."""
    return sorted(
        suggestions,
        key=lambda s: (SUGGESTION_SEVERITY_ORDER.get(s.severity, 2), s.created_at),
    )


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------


async def _format_review_response(
    review: QAReview, db: AsyncSession
) -> QAReviewResponse:
    reviewer_name = None
    if review.reviewer_id:
        result = await db.execute(select(User).where(User.id == review.reviewer_id))
        reviewer = result.scalar_one_or_none()
        if reviewer:
            reviewer_name = reviewer.full_name or reviewer.username

    summary = QAReviewSummary(**review.summary) if review.summary else None

    return QAReviewResponse(
        id=review.id,
        task_id=review.task_id,
        reviewer_id=review.reviewer_id,
        reviewer_name=reviewer_name,
        status=review.status,
        mode=review.mode,
        review_stage=review.review_stage,
        started_at=review.started_at,
        completed_at=review.completed_at,
        summary=summary,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


async def _format_annotation_review_response(
    review: AnnotationReview, db: AsyncSession
) -> AnnotationReviewResponse:
    frame_id = review.frame_id if hasattr(review, "frame_id") else None
    class_id = review.class_id if hasattr(review, "class_id") else None

    if not frame_id or not class_id:
        try:
            result = await db.execute(
                select(Annotation).where(Annotation.id == review.annotation_id)
            )
            annotation = result.scalar_one_or_none()
            if annotation:
                frame_id = frame_id or annotation.frame_id
                class_id = class_id or annotation.class_id
        except Exception:  # noqa: BLE001 - formatting must never mask the payload
            pass

    return AnnotationReviewResponse(
        id=review.id,
        qa_review_id=review.qa_review_id,
        annotation_id=review.annotation_id,
        annotation_table=review.annotation_table,
        verdict=review.verdict,
        issue_types=review.issue_types,
        notes=review.notes,
        reviewed_at=review.reviewed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        frame_id=frame_id,
        class_id=class_id,
        location_x=getattr(review, "location_x", None),
        location_y=getattr(review, "location_y", None),
        location_z=getattr(review, "location_z", None),
        annotator_resolved=getattr(review, "annotator_resolved", False),
    )


async def _format_comment_response(
    comment: AnnotationComment,
    db: AsyncSession,
    include_replies: bool = False,
) -> AnnotationCommentResponse:
    user_name = None
    if comment.user_id:
        result = await db.execute(select(User).where(User.id == comment.user_id))
        user = result.scalar_one_or_none()
        if user:
            user_name = user.full_name or user.username

    replies = []
    if include_replies:
        result = await db.execute(
            select(AnnotationComment)
            .where(AnnotationComment.parent_id == comment.id)
            .order_by(AnnotationComment.created_at.asc())
        )
        reply_records = result.scalars().all()
        replies = [
            await _format_comment_response(r, db, include_replies=False)
            for r in reply_records
        ]

    return AnnotationCommentResponse(
        id=comment.id,
        annotation_id=comment.annotation_id,
        annotation_table=comment.annotation_table,
        user_id=comment.user_id,
        user_name=user_name,
        parent_id=comment.parent_id,
        content=comment.content,
        is_resolved=comment.is_resolved,
        resolved_by=comment.resolved_by,
        resolved_at=comment.resolved_at,
        replies=replies,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _format_suggestion_response(
    suggestion: QASuggestion,
) -> QASuggestionResponse:
    return QASuggestionResponse(
        id=suggestion.id,
        task_id=suggestion.task_id,
        annotation_id=suggestion.annotation_id,
        annotation_table=suggestion.annotation_table,
        frame_id=suggestion.frame_id,
        suggestion_type=suggestion.suggestion_type,
        severity=suggestion.severity,
        message=suggestion.message,
        details=suggestion.details,
        is_dismissed=suggestion.is_dismissed,
        dismissed_by=suggestion.dismissed_by,
        dismissed_at=suggestion.dismissed_at,
        created_at=suggestion.created_at,
    )


# ---------------------------------------------------------------------------
# QA review sessions
# ---------------------------------------------------------------------------


async def start_review(
    db: AsyncSession, review_data: QAReviewCreate, reviewer: User
) -> QAReviewResponse:
    result = await db.execute(select(Task).where(Task.id == review_data.task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise QANotFoundError("Task")

    active_review_query = select(QAReview).where(
        QAReview.task_id == review_data.task_id,
        QAReview.status == QAReviewStatus.IN_PROGRESS.value,
    )
    if review_data.review_stage:
        active_review_query = active_review_query.where(
            QAReview.review_stage == review_data.review_stage
        )
    result = await db.execute(active_review_query)
    active_review = result.scalar_one_or_none()

    if active_review:
        raise QAValidationError(
            "There is already an active QA review for this task"
        )

    review_stage = review_data.review_stage or task.stage

    mode_value = (
        review_data.mode
        if isinstance(review_data.mode, str)
        else review_data.mode.value
    )
    review = QAReview(
        id=uuid.uuid4(),
        task_id=review_data.task_id,
        reviewer_id=reviewer.id,
        mode=mode_value,
        review_stage=review_stage,
        status=QAReviewStatus.IN_PROGRESS.value,
        started_at=datetime.utcnow(),
    )

    db.add(review)
    await db.flush()
    await db.refresh(review)

    previous_review_query = (
        select(QAReview)
        .where(
            QAReview.task_id == review_data.task_id,
            QAReview.status == QAReviewStatus.COMPLETED.value,
            QAReview.id != review.id,
        )
        .order_by(QAReview.completed_at.desc())
        .limit(1)
    )
    if review_stage:
        previous_review_query = previous_review_query.where(
            QAReview.review_stage == review_stage
        )
    result = await db.execute(previous_review_query)
    previous_review = result.scalar_one_or_none()

    if previous_review:
        result = await db.execute(
            select(AnnotationReview).where(
                AnnotationReview.qa_review_id == previous_review.id,
                AnnotationReview.verdict == ReviewVerdict.APPROVED.value,
            )
        )
        approved_reviews = result.scalars().all()

        for old_review in approved_reviews:
            new_annotation_review = AnnotationReview(
                id=uuid.uuid4(),
                qa_review_id=review.id,
                annotation_id=old_review.annotation_id,
                annotation_table=old_review.annotation_table,
                verdict=old_review.verdict,
                issue_types=None,
                notes="Carried over from previous QA review",
                reviewed_at=old_review.reviewed_at,
            )
            db.add(new_annotation_review)

        await db.flush()

    return await _format_review_response(review, db)


async def _get_review_or_404(db: AsyncSession, review_id: uuid.UUID) -> QAReview:
    result = await db.execute(select(QAReview).where(QAReview.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise QANotFoundError("QA review", review_id)
    return review


async def get_review(
    db: AsyncSession, review_id: uuid.UUID
) -> QAReviewResponse:
    review = await _get_review_or_404(db, review_id)
    return await _format_review_response(review, db)


async def list_task_reviews(
    db: AsyncSession, task_id: uuid.UUID, status_filter: Optional[str] = None
) -> list[QAReviewResponse]:
    query = select(QAReview).where(QAReview.task_id == task_id)
    if status_filter:
        query = query.where(QAReview.status == status_filter)
    query = query.order_by(QAReview.created_at.desc())
    result = await db.execute(query)
    reviews = result.scalars().all()
    return [await _format_review_response(r, db) for r in reviews]


async def get_active_review(
    db: AsyncSession, task_id: uuid.UUID, review_stage: Optional[str] = None
) -> Optional[QAReviewResponse]:
    query = select(QAReview).where(
        QAReview.task_id == task_id,
        QAReview.status == QAReviewStatus.IN_PROGRESS.value,
    )
    if review_stage:
        query = query.where(QAReview.review_stage == review_stage)
    result = await db.execute(query)
    review = result.scalar_one_or_none()
    if not review:
        return None
    return await _format_review_response(review, db)


async def update_review(
    db: AsyncSession, review_id: uuid.UUID, update_data: QAReviewUpdate
) -> QAReviewResponse:
    review = await _get_review_or_404(db, review_id)

    if update_data.status:
        review.status = (
            update_data.status
            if isinstance(update_data.status, str)
            else update_data.status.value
        )
    if update_data.mode:
        review.mode = (
            update_data.mode
            if isinstance(update_data.mode, str)
            else update_data.mode.value
        )

    await db.flush()
    await db.refresh(review)
    return await _format_review_response(review, db)


async def complete_review(
    db: AsyncSession,
    review_id: uuid.UUID,
    complete_data: QAReviewComplete,  # noqa: ARG001 - request body kept for API contract
) -> QAReviewResponse:
    review = await _get_review_or_404(db, review_id)

    task_result = await db.execute(select(Task).where(Task.id == review.task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise QANotFoundError("Task")

    result = await db.execute(
        select(AnnotationReview).where(AnnotationReview.qa_review_id == review_id)
    )
    annotation_reviews = result.scalars().all()

    approved_count = sum(
        1 for ar in annotation_reviews if ar.verdict == ReviewVerdict.APPROVED.value
    )
    rejected_count = sum(
        1 for ar in annotation_reviews if ar.verdict == ReviewVerdict.REJECTED.value
    )
    flagged_count = sum(
        1 for ar in annotation_reviews if ar.verdict == ReviewVerdict.FLAGGED.value
    )
    pending_count = sum(
        1
        for ar in annotation_reviews
        if ar.verdict is None or ar.verdict == ReviewVerdict.PENDING.value
    )

    summary: dict[str, Any] = {
        "approved": approved_count,
        "rejected": rejected_count,
        "flagged": flagged_count,
        "pending": pending_count,
        "total_annotations": len(annotation_reviews),
    }

    review.status = QAReviewStatus.COMPLETED.value
    review.completed_at = datetime.utcnow()
    review.summary = summary

    next_stage, next_status = next_stage_after_qa(
        task.stage, task.skip_customer_qa
    )
    if next_stage is not None:
        task.stage = next_stage
        task.status = next_status
        summary["next_stage"] = next_stage
    else:
        summary["next_stage"] = task.stage
    summary["outcome"] = "accepted"

    summary["approved"] = approved_count
    summary["rejected"] = rejected_count
    summary["flagged"] = flagged_count
    summary["pending"] = pending_count

    review.summary = summary

    await db.flush()
    await db.refresh(review)
    await db.refresh(task)

    return await _format_review_response(review, db)


async def pause_review(
    db: AsyncSession, review_id: uuid.UUID
) -> QAReviewResponse:
    review = await _get_review_or_404(db, review_id)
    review.status = QAReviewStatus.PAUSED.value
    await db.flush()
    await db.refresh(review)
    return await _format_review_response(review, db)


async def resume_review(
    db: AsyncSession, review_id: uuid.UUID
) -> QAReviewResponse:
    review = await _get_review_or_404(db, review_id)
    if review.status != QAReviewStatus.PAUSED.value:
        raise QAValidationError("Review is not paused")
    review.status = QAReviewStatus.IN_PROGRESS.value
    await db.flush()
    await db.refresh(review)
    return await _format_review_response(review, db)


# ---------------------------------------------------------------------------
# Annotation-level reviews
# ---------------------------------------------------------------------------


async def review_annotation(
    db: AsyncSession,
    review_id: uuid.UUID,
    review_data: AnnotationReviewCreate,
) -> AnnotationReviewResponse:
    result = await db.execute(select(QAReview).where(QAReview.id == review_id))
    qa_review = result.scalar_one_or_none()
    if not qa_review:
        raise QANotFoundError("QA review", review_id)

    result = await db.execute(
        select(AnnotationReview).where(
            AnnotationReview.qa_review_id == review_id,
            AnnotationReview.annotation_id == review_data.annotation_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        verdict_value = (
            review_data.verdict
            if isinstance(review_data.verdict, str)
            else review_data.verdict.value
        )
        existing.verdict = verdict_value
        existing.issue_types = review_data.issue_types
        existing.notes = review_data.notes
        existing.reviewed_at = datetime.utcnow()
        if review_data.frame_id:
            existing.frame_id = review_data.frame_id
        if review_data.class_id:
            existing.class_id = review_data.class_id
        if review_data.location_x is not None:
            existing.location_x = review_data.location_x
        if review_data.location_y is not None:
            existing.location_y = review_data.location_y
        if review_data.location_z is not None:
            existing.location_z = review_data.location_z
        await db.flush()
        await db.refresh(existing)
        return await _format_annotation_review_response(existing, db)

    verdict_value = (
        review_data.verdict
        if isinstance(review_data.verdict, str)
        else review_data.verdict.value
    )
    annotation_review = AnnotationReview(
        id=uuid.uuid4(),
        qa_review_id=review_id,
        annotation_id=review_data.annotation_id,
        annotation_table=review_data.annotation_table,
        frame_id=review_data.frame_id,
        class_id=review_data.class_id,
        verdict=verdict_value,
        issue_types=review_data.issue_types,
        notes=review_data.notes,
        reviewed_at=datetime.utcnow(),
        location_x=review_data.location_x,
        location_y=review_data.location_y,
        location_z=review_data.location_z,
    )

    db.add(annotation_review)
    await db.flush()
    await db.refresh(annotation_review)

    return await _format_annotation_review_response(annotation_review, db)


async def bulk_review_annotations(
    db: AsyncSession,
    review_id: uuid.UUID,
    bulk_data: BulkAnnotationReviewCreate,
) -> BulkAnnotationReviewResponse:
    result = await db.execute(select(QAReview).where(QAReview.id == review_id))
    qa_review = result.scalar_one_or_none()
    if not qa_review:
        raise QANotFoundError("QA review", review_id)

    success_count = 0
    errors = []

    for i, review_data in enumerate(bulk_data.reviews):
        try:
            result = await db.execute(
                select(AnnotationReview).where(
                    AnnotationReview.qa_review_id == review_id,
                    AnnotationReview.annotation_id == review_data.annotation_id,
                )
            )
            existing = result.scalar_one_or_none()

            verdict_value = (
                review_data.verdict
                if isinstance(review_data.verdict, str)
                else review_data.verdict.value
            )

            if existing:
                existing.verdict = verdict_value
                existing.issue_types = review_data.issue_types
                existing.notes = review_data.notes
                existing.reviewed_at = datetime.utcnow()
            else:
                annotation_review = AnnotationReview(
                    id=uuid.uuid4(),
                    qa_review_id=review_id,
                    annotation_id=review_data.annotation_id,
                    annotation_table=review_data.annotation_table,
                    verdict=verdict_value,
                    issue_types=review_data.issue_types,
                    notes=review_data.notes,
                    reviewed_at=datetime.utcnow(),
                )
                db.add(annotation_review)

            success_count += 1
        except Exception as e:  # noqa: BLE001 - per-item errors are reported, not raised
            errors.append({"index": i, "error": str(e)})

    await db.flush()

    return BulkAnnotationReviewResponse(
        success_count=success_count,
        error_count=len(errors),
        errors=errors,
    )


async def list_annotation_reviews(
    db: AsyncSession, review_id: uuid.UUID, verdict: Optional[str] = None
) -> list[AnnotationReviewResponse]:
    query = select(AnnotationReview).where(
        AnnotationReview.qa_review_id == review_id
    )
    if verdict:
        query = query.where(AnnotationReview.verdict == verdict)
    result = await db.execute(query)
    reviews = result.scalars().all()
    return [await _format_annotation_review_response(r, db) for r in reviews]


async def get_annotation_review_status(
    db: AsyncSession, annotation_id: str, qa_review_id: uuid.UUID
) -> Optional[AnnotationReviewResponse]:
    result = await db.execute(
        select(AnnotationReview).where(
            AnnotationReview.qa_review_id == qa_review_id,
            AnnotationReview.annotation_id == annotation_id,
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        return None
    return await _format_annotation_review_response(review, db)


async def resolve_annotation_review(
    db: AsyncSession, review_id: uuid.UUID
) -> AnnotationReviewResponse:
    review = await db.get(AnnotationReview, review_id)
    if not review:
        raise QANotFoundError("Annotation review", review_id)

    if not review.annotator_resolved:
        review.annotator_resolved = True
        await db.flush()
        await db.refresh(review)

    return await _format_annotation_review_response(review, db)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def create_comment(
    db: AsyncSession, comment_data: AnnotationCommentCreate
) -> AnnotationCommentResponse:
    comment = AnnotationComment(
        id=uuid.uuid4(),
        annotation_id=comment_data.annotation_id,
        annotation_table=comment_data.annotation_table,
        parent_id=comment_data.parent_id,
        content=comment_data.content,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return await _format_comment_response(comment, db)


async def list_annotation_comments(
    db: AsyncSession, annotation_id: str, include_resolved: bool = False
) -> list[AnnotationCommentResponse]:
    query = select(AnnotationComment).where(
        AnnotationComment.annotation_id == annotation_id,
        AnnotationComment.parent_id.is_(None),
    )
    if not include_resolved:
        query = query.where(AnnotationComment.is_resolved == False)  # noqa: E712
    query = query.order_by(AnnotationComment.created_at.asc())
    result = await db.execute(query)
    comments = result.scalars().all()
    return [
        await _format_comment_response(c, db, include_replies=True) for c in comments
    ]


async def update_comment(
    db: AsyncSession, comment_id: uuid.UUID, update_data: AnnotationCommentUpdate
) -> AnnotationCommentResponse:
    result = await db.execute(
        select(AnnotationComment).where(AnnotationComment.id == comment_id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise QANotFoundError("Comment", comment_id)

    if update_data.content:
        comment.content = update_data.content

    await db.flush()
    await db.refresh(comment)
    return await _format_comment_response(comment, db)


async def delete_comment(db: AsyncSession, comment_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(AnnotationComment).where(AnnotationComment.id == comment_id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise QANotFoundError("Comment", comment_id)
    await db.delete(comment)
    await db.flush()
    return {"message": "Comment deleted"}


async def resolve_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    resolve_data: ResolveCommentRequest,
) -> AnnotationCommentResponse:
    result = await db.execute(
        select(AnnotationComment).where(AnnotationComment.id == comment_id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise QANotFoundError("Comment", comment_id)

    comment.is_resolved = resolve_data.is_resolved
    if resolve_data.is_resolved:
        comment.resolved_at = datetime.utcnow()
    else:
        comment.resolved_at = None
        comment.resolved_by = None

    await db.flush()
    await db.refresh(comment)
    return await _format_comment_response(comment, db)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


async def list_task_suggestions(
    db: AsyncSession,
    task_id: uuid.UUID,
    include_dismissed: bool = False,
    severity: Optional[str] = None,
    suggestion_type: Optional[str] = None,
) -> list[QASuggestionResponse]:
    query = select(QASuggestion).where(QASuggestion.task_id == task_id)
    if not include_dismissed:
        query = query.where(QASuggestion.is_dismissed == False)  # noqa: E712
    if severity:
        query = query.where(QASuggestion.severity == severity)
    if suggestion_type:
        query = query.where(QASuggestion.suggestion_type == suggestion_type)
    result = await db.execute(query)
    suggestions = list(result.scalars().all())
    return [_format_suggestion_response(s) for s in sort_suggestions(suggestions)]


async def create_manual_suggestion(
    db: AsyncSession, request: CreateManualSuggestionRequest, current_user: User
) -> QASuggestionResponse:
    result = await db.execute(select(Task).where(Task.id == request.task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise QANotFoundError("Task")

    details = request.details or {}
    if request.location:
        details["location"] = request.location
    if request.suggested_class:
        details["suggested_class"] = request.suggested_class
    details["created_by"] = str(current_user.id)
    details["created_by_username"] = current_user.username

    suggestion = QASuggestion(
        id=uuid.uuid4(),
        task_id=request.task_id,
        frame_id=str(request.frame_id),
        suggestion_type=(
            request.suggestion_type.value
            if hasattr(request.suggestion_type, "value")
            else request.suggestion_type
        ),
        severity=request.severity or "high",
        message=request.message,
        details=details,
        is_dismissed=False,
    )

    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)

    return _format_suggestion_response(suggestion)


async def dismiss_suggestion(
    db: AsyncSession,
    suggestion_id: uuid.UUID,
    dismiss_data: DismissSuggestionRequest,
) -> QASuggestionResponse:
    result = await db.execute(
        select(QASuggestion).where(QASuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise QANotFoundError("Suggestion", suggestion_id)

    suggestion.is_dismissed = True
    suggestion.dismissed_at = datetime.utcnow()

    if dismiss_data.reason:
        details = suggestion.details or {}
        details["dismiss_reason"] = dismiss_data.reason
        suggestion.details = details

    await db.flush()
    await db.refresh(suggestion)
    return _format_suggestion_response(suggestion)


async def delete_suggestion(
    db: AsyncSession, suggestion_id: uuid.UUID
) -> dict:
    result = await db.execute(
        select(QASuggestion).where(QASuggestion.id == suggestion_id)
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise QANotFoundError("Suggestion", suggestion_id)
    await db.delete(suggestion)
    await db.flush()
    return {"message": "Suggestion deleted"}


# ---------------------------------------------------------------------------
# Task QA stats
# ---------------------------------------------------------------------------


async def get_task_stats(
    db: AsyncSession, task_id: uuid.UUID
) -> QATaskStats:
    result = await db.execute(
        select(QAReview).where(
            QAReview.task_id == task_id,
            QAReview.status == QAReviewStatus.IN_PROGRESS.value,
        )
    )
    active_review = result.scalar_one_or_none()

    result = await db.execute(
        select(func.count(Annotation.id)).where(Annotation.task_id == task_id)
    )
    total_annotations = result.scalar() or 0

    reviewed_count = 0
    approved_count = 0
    rejected_count = 0
    flagged_count = 0

    if active_review:
        result = await db.execute(
            select(AnnotationReview).where(
                AnnotationReview.qa_review_id == active_review.id
            )
        )
        reviews = result.scalars().all()

        reviewed_count = len([r for r in reviews if r.verdict])
        approved_count = len(
            [r for r in reviews if r.verdict == ReviewVerdict.APPROVED.value]
        )
        rejected_count = len(
            [r for r in reviews if r.verdict == ReviewVerdict.REJECTED.value]
        )
        flagged_count = len(
            [r for r in reviews if r.verdict == ReviewVerdict.FLAGGED.value]
        )

    result = await db.execute(
        select(func.count(QASuggestion.id)).where(
            QASuggestion.task_id == task_id,
            QASuggestion.is_dismissed == False,  # noqa: E712
        )
    )
    suggestions_count = result.scalar() or 0

    result = await db.execute(
        select(func.count(QASuggestion.id)).where(
            QASuggestion.task_id == task_id,
            QASuggestion.is_dismissed == True,  # noqa: E712
        )
    )
    suggestions_dismissed = result.scalar() or 0

    comment_count = 0
    unresolved_comments = 0

    pending_count = total_annotations - reviewed_count
    review_progress = (
        (reviewed_count / total_annotations * 100) if total_annotations > 0 else 0
    )

    return QATaskStats(
        task_id=task_id,
        total_annotations=total_annotations,
        reviewed_count=reviewed_count,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        flagged_count=flagged_count,
        suggestions_count=suggestions_count,
        suggestions_dismissed=suggestions_dismissed,
        comment_count=comment_count,
        unresolved_comments=unresolved_comments,
        review_progress_percent=round(review_progress, 1),
        has_active_review=active_review is not None,
        active_review_id=active_review.id if active_review else None,
    )
