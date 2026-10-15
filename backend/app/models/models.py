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
from app.models.enums import QAReviewMode as QAReviewMode
from app.models.enums import QAReviewStatus as QAReviewStatus
from app.models.enums import ReviewVerdict as ReviewVerdict
from app.models.enums import SuggestionSeverity as SuggestionSeverity
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

# Re-exported for the module facade (zero import-path change for callers).
from app.models.qa import AnnotationComment as AnnotationComment
from app.models.qa import AnnotationReview as AnnotationReview
from app.models.qa import QAReview as QAReview
from app.models.qa import QASuggestion as QASuggestion
from app.models.scene import Frame as Frame
from app.models.scene import Scene as Scene
from app.models.task import StageSnapshot as StageSnapshot
from app.models.task import Task as Task
from app.models.task import TaskAssignmentHistory as TaskAssignmentHistory
from app.models.task import TaskStageHistory as TaskStageHistory
from app.models.user import AuditLog as AuditLog
from app.models.user import User as User
from app.models.user import UserSSOIdentity as UserSSOIdentity


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
