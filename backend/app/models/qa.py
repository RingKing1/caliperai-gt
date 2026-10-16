"""Quality assurance: review sessions, per-annotation reviews, comments, suggestions."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import (
    QAReviewMode,
    QAReviewStatus,
    SuggestionSeverity,
)

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.task import Task
    from app.models.user import User


class QAReview(Base, TimestampMixin):
    """
    QA review session for a task.
    Tracks the overall QA review process.
    """
    __tablename__ = "qa_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=QAReviewStatus.IN_PROGRESS.value,
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(20),
        default=QAReviewMode.VIEW_ONLY.value,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_stage: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    """The task stage this review was created for ('qa' or 'customer_qa').
    Used to separate QA reviews from Customer QA reviews."""
    summary: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Summary schema:
    {
        "approved": 45,
        "rejected": 3,
        "flagged": 2,
        "pending": 10,
        "total_annotations": 60,
        "suggestions_addressed": 15,
        "suggestions_dismissed": 5
    }
    """

    task: Mapped["Task"] = relationship("Task", backref="qa_reviews")
    reviewer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[reviewer_id]
    )
    annotation_reviews: Mapped[list["AnnotationReview"]] = relationship(
        "AnnotationReview",
        back_populates="qa_review",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_qa_reviews_task_id", "task_id"),
        Index("ix_qa_reviews_reviewer_id", "reviewer_id"),
        Index("ix_qa_reviews_status", "status"),
    )


class AnnotationReview(Base, TimestampMixin):
    """
    Review verdict for a specific annotation.
    Links to QA review session.
    """
    __tablename__ = "annotation_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    qa_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("qa_reviews.id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    annotation_table: Mapped[str] = mapped_column(
        String(50),
        default="annotations",
        nullable=False,
    )
    frame_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    class_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    verdict: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    issue_types: Mapped[list[str] | None] = mapped_column(
        PGARRAY(String(50)),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    location_x: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    location_y: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    location_z: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    annotator_resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    qa_review: Mapped["QAReview"] = relationship(
        "QAReview",
        back_populates="annotation_reviews",
    )

    __table_args__ = (
        Index("ix_annotation_reviews_qa_review_id", "qa_review_id"),
        Index("ix_annotation_reviews_annotation_id", "annotation_id"),
        UniqueConstraint(
            "qa_review_id", "annotation_id", name="uq_annotation_reviews_qa_annotation"
        ),
    )


class AnnotationComment(Base, TimestampMixin):
    """
    Threaded comments on annotations.
    Supports nested replies.
    """
    __tablename__ = "annotation_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    annotation_table: Mapped[str] = mapped_column(
        String(50),
        default="annotations",
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("annotation_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    resolver: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[resolved_by]
    )
    parent: Mapped[Optional["AnnotationComment"]] = relationship(
        "AnnotationComment",
        remote_side=[id],
        backref="replies",
    )

    __table_args__ = (
        Index("ix_annotation_comments_annotation_id", "annotation_id"),
        Index("ix_annotation_comments_user_id", "user_id"),
        Index("ix_annotation_comments_parent_id", "parent_id"),
    )


class QASuggestion(Base):
    """
    AI-generated suggestions for QA review.
    Detects anomalies and potential issues.
    """
    __tablename__ = "qa_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    annotation_table: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    frame_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    suggestion_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    """
    Suggestion types:
    - size_anomaly: Dimensions change >30% between frames
    - position_jump: Object moves >3m between consecutive frames
    - orientation_flip: Yaw changes >90° suddenly
    - track_discontinuity: Same object, different track IDs
    - low_confidence: Confidence score <0.6
    - class_mismatch: Track has multiple classes
    - missing_attributes: Required attributes not set
    - auto_interpolated: Review suggested for auto-generated frames
    - imported_unchecked: Imported annotation never reviewed
    """
    severity: Mapped[str] = mapped_column(
        String(20),
        default=SuggestionSeverity.MEDIUM.value,
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Details schema varies by type:
    - size_anomaly: { prev_dimensions: {...}, curr_dimensions: {...},
      delta_percent: 38 }
    - position_jump: { prev_position: {...}, curr_position: {...}, distance: 5.2 }
    - etc.
    """
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task")
    dismisser: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[dismissed_by]
    )

    __table_args__ = (
        Index("ix_qa_suggestions_task_id", "task_id"),
        Index("ix_qa_suggestions_annotation_id", "annotation_id"),
        Index("ix_qa_suggestions_severity", "severity"),
        Index("ix_qa_suggestions_is_dismissed", "is_dismissed"),
    )
