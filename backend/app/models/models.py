"""
SQLAlchemy models for the Sensor Fusion Annotation Platform.

Database Hierarchy:
Campaign → Dataset → Scene → Task → Annotation

Each level inherits context from its parent and provides specific functionality.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY as PGARRAY,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Re-exported for the module facade (zero import-path change for callers).
from app.models.annotation import Annotation as Annotation
from app.models.annotation import Annotation2D as Annotation2D
from app.models.annotation import Annotation3D as Annotation3D
from app.models.annotation import Annotation4D as Annotation4D
from app.models.annotation import AnnotationChangeType as AnnotationChangeType
from app.models.annotation import AnnotationFusion as AnnotationFusion
from app.models.annotation import AnnotationHistory as AnnotationHistory
from app.models.annotation import SegmentationBlob as SegmentationBlob
from app.models.annotation import Track2D as Track2D
from app.models.base import SoftDeleteMixin as SoftDeleteMixin
from app.models.base import TimestampMixin as TimestampMixin
from app.models.catalog import Campaign as Campaign
from app.models.catalog import Dataset as Dataset
from app.models.catalog import Taxonomy as Taxonomy
from app.models.catalog import (
    dataset_taxonomy_association as dataset_taxonomy_association,
)
from app.models.efficiency import Achievement as Achievement
from app.models.efficiency import ActivityEvent as ActivityEvent
from app.models.efficiency import ChallengeParticipant as ChallengeParticipant
from app.models.efficiency import DailyUserStats as DailyUserStats
from app.models.efficiency import PerformanceAlert as PerformanceAlert
from app.models.efficiency import TeamChallenge as TeamChallenge
from app.models.efficiency import TimeSession as TimeSession
from app.models.efficiency import UserGoal as UserGoal
from app.models.efficiency import UserLoginSession as UserLoginSession
from app.models.enums import (
    ROLE_PERMISSIONS as ROLE_PERMISSIONS,
)
from app.models.enums import AchievementType as AchievementType
from app.models.enums import ActivityEventType as ActivityEventType
from app.models.enums import AlertSeverity as AlertSeverity
from app.models.enums import AlertType as AlertType
from app.models.enums import (
    AnnotationSource as AnnotationSource,
)
from app.models.enums import (
    AnnotationType as AnnotationType,
)
from app.models.enums import GoalType as GoalType
from app.models.enums import (
    OrganizationRole as OrganizationRole,
)
from app.models.enums import (
    Permission as Permission,
)
from app.models.enums import (
    TaskStage as TaskStage,
)
from app.models.enums import (
    TaskStatus as TaskStatus,
)
from app.models.enums import (
    TaxonomyAnnotationMode as TaxonomyAnnotationMode,
)
from app.models.enums import (
    UserRole as UserRole,
)
from app.models.org import Organization as Organization
from app.models.org import OrganizationMember as OrganizationMember
from app.models.scene import Frame as Frame
from app.models.scene import Scene as Scene
from app.models.task import StageSnapshot as StageSnapshot
from app.models.task import Task as Task
from app.models.task import TaskAssignmentHistory as TaskAssignmentHistory
from app.models.task import TaskStageHistory as TaskStageHistory
from app.models.user import AuditLog as AuditLog
from app.models.user import User as User
from app.models.user import UserSSOIdentity as UserSSOIdentity


class QAReviewStatus(str, Enum):
    """QA review session status."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"


class QAReviewMode(str, Enum):
    """QA review mode."""
    VIEW_ONLY = "view_only"
    EDIT = "edit"
    SUGGEST = "suggest"


class ReviewVerdict(str, Enum):
    """Review verdict for an annotation."""
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    PENDING = "pending"


class SuggestionSeverity(str, Enum):
    """Severity level for QA suggestions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
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
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_stage: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    """The task stage this review was created for ('qa' or 'customer_qa').
    Used to separate QA reviews from Customer QA reviews."""
    summary: Mapped[Optional[dict]] = mapped_column(
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
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewer_id])
    annotation_reviews: Mapped[List["AnnotationReview"]] = relationship(
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
    frame_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    class_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    verdict: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    issue_types: Mapped[Optional[List[str]]] = mapped_column(
        PGARRAY(String(50)),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    location_x: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    location_y: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    location_z: Mapped[Optional[float]] = mapped_column(
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
        UniqueConstraint("qa_review_id", "annotation_id", name="uq_annotation_reviews_qa_annotation"),
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
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
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
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    resolver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[resolved_by])
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
    annotation_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    annotation_table: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    frame_id: Mapped[Optional[str]] = mapped_column(
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
    details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    """
    Details schema varies by type:
    - size_anomaly: { prev_dimensions: {...}, curr_dimensions: {...}, delta_percent: 38 }
    - position_jump: { prev_position: {...}, curr_position: {...}, distance: 5.2 }
    - etc.
    """
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    dismissed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    task: Mapped["Task"] = relationship("Task")
    dismisser: Mapped[Optional["User"]] = relationship("User", foreign_keys=[dismissed_by])
    
    __table_args__ = (
        Index("ix_qa_suggestions_task_id", "task_id"),
        Index("ix_qa_suggestions_annotation_id", "annotation_id"),
        Index("ix_qa_suggestions_severity", "severity"),
        Index("ix_qa_suggestions_is_dismissed", "is_dismissed"),
    )



class ChatSession(Base):
    """
    Chat session for AI assistant conversations.
    Each user can have multiple sessions over time.
    """
    __tablename__ = "chat_sessions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=True,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    
    __table_args__ = (
        Index("ix_chat_sessions_user_id", "user_id"),
        Index("ix_chat_sessions_created_at", "created_at"),
    )


class ChatMessageRole(str, Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessageFeedback(str, Enum):
    """User feedback on assistant responses."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class ChatMessage(Base):
    """
    Individual chat message within a session.
    Stores both user messages and assistant responses.
    """
    __tablename__ = "chat_messages"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    context: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        default=dict,
        nullable=True,
    )
    
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    session: Mapped["ChatSession"] = relationship(
        "ChatSession",
        back_populates="messages",
    )
    
    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id"),
        Index("ix_chat_messages_created_at", "created_at"),
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_chat_messages_valid_role",
        ),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('helpful', 'not_helpful')",
            name="ck_chat_messages_valid_feedback",
        ),
    )


class KnowledgeChunk(Base):
    """
    Knowledge base chunks for RAG (Retrieval Augmented Generation).
    Stores embedded document chunks for semantic search.
    """
    __tablename__ = "knowledge_chunks"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        PGARRAY(Float, dimensions=1),
        nullable=True,
    )
    
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=True,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    __table_args__ = (
        Index("ix_knowledge_chunks_source", "source"),
    )


class ImportJob(Base, TimestampMixin):
    """Background dataset import job (long ZIP/folder uploads).

    The receiving gunicorn worker stages the upload, inserts a pending row
    and runs the import in an ``asyncio`` task; any worker can serve polls
    because the state lives in the database.
    """

    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    phase: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenes_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    staged_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
