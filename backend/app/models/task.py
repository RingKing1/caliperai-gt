"""Task lifecycle models: tasks, assignment/stage history and snapshots."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import TaskStage, TaskStatus

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.catalog import Taxonomy
    from app.models.efficiency import ActivityEvent, PerformanceAlert, TimeSession
    from app.models.models import Annotation, AnnotationHistory
    from app.models.scene import Scene
    from app.models.user import User


class Task(Base, TimestampMixin, SoftDeleteMixin):
    """
    Atomic unit of work assigned to annotators.
    Supports frame ranges with context buffers.
    """
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(50),
        default=TaskStatus.PENDING.value,
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(
        String(50),
        default=TaskStage.ANNOTATION.value,
        nullable=False,
    )

    frame_range: Mapped[Any] = mapped_column(INT4RANGE, nullable=False)

    context_buffer_before: Mapped[int] = mapped_column(Integer, default=5)
    context_buffer_after: Mapped[int] = mapped_column(Integer, default=5)

    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    customer_reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    customer_review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    skip_customer_qa: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    priority: Mapped[int] = mapped_column(Integer, default=5)
    deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Config schema:
    {
        "required_annotation_types": ["cuboid", "box2d"],
        "required_classes": ["car", "pedestrian", "cyclist"],
        "auto_annotation_enabled": true,
        "quality_checks": ["no_overlapping", "complete_tracking"]
    }
    """

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_time_seconds: Mapped[int] = mapped_column(Integer, default=0)

    scene: Mapped["Scene"] = relationship("Scene", back_populates="tasks")
    assignee: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="assigned_tasks",
        foreign_keys=[assignee_id],
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="reviewed_tasks",
        foreign_keys=[reviewer_id],
    )
    customer_reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[customer_reviewer_id],
    )
    annotations: Mapped[List["Annotation"]] = relationship(
        "Annotation",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    stage_history: Mapped[List["TaskStageHistory"]] = relationship(
        "TaskStageHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStageHistory.created_at",
    )
    stage_snapshots: Mapped[List["StageSnapshot"]] = relationship(
        "StageSnapshot",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="StageSnapshot.created_at.desc()",
    )
    annotation_history: Mapped[List["AnnotationHistory"]] = relationship(
        "AnnotationHistory",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    assignment_history: Mapped[List["TaskAssignmentHistory"]] = relationship(
        "TaskAssignmentHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskAssignmentHistory.created_at",
    )

    time_sessions: Mapped[List["TimeSession"]] = relationship(
        "TimeSession",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[List["ActivityEvent"]] = relationship(
        "ActivityEvent",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    performance_alerts: Mapped[List["PerformanceAlert"]] = relationship(
        "PerformanceAlert",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    taxonomy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("taxonomies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    taxonomy: Mapped[Optional["Taxonomy"]] = relationship(
        "Taxonomy", foreign_keys=[taxonomy_id]
    )

    __table_args__ = (
        Index("ix_tasks_scene_id", "scene_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_stage", "stage"),
        Index("ix_tasks_assignee_id", "assignee_id"),
        Index("ix_tasks_priority", "priority"),
        CheckConstraint(
            "status IN ('pending', 'assigned', 'in_progress', "
            "'submitted', 'accepted', 'rejected')",
            name="ck_task_status",
        ),
    )


class TaskAssignmentHistory(Base):
    """
    Audit trail for task assignment changes.
    Tracks every assign, unassign, and stage-change clearing.
    """
    __tablename__ = "task_assignment_history"

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

    action: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    role: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )

    stage: Mapped[str] = mapped_column(String(50), nullable=False)

    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="assignment_history")
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    changed_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[changed_by_id]
    )

    __table_args__ = (
        Index("ix_task_assignment_history_task_id", "task_id"),
        Index("ix_task_assignment_history_created_at", "created_at"),
    )


class TaskStageHistory(Base):
    """
    Audit trail for task stage and status transitions.
    Tracks all changes with who made them and why.
    """
    __tablename__ = "task_stage_history"

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

    from_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)

    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)

    changed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="stage_history")
    changed_by: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_task_stage_history_task_id", "task_id"),
        Index("ix_task_stage_history_created_at", "created_at"),
    )


class StageSnapshot(Base):
    """
    Snapshot of all annotations at a stage transition.
    Captures the complete annotation state when a task moves between stages.
    """
    __tablename__ = "stage_snapshots"

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

    from_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)

    snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False)

    total_annotations: Mapped[int] = mapped_column(Integer, default=0)
    annotations_by_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    annotations_by_type: Mapped[dict] = mapped_column(JSONB, default=dict)
    annotations_by_frame: Mapped[dict] = mapped_column(JSONB, default=dict)

    annotations_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    triggered_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="stage_snapshots")
    triggered_by: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_stage_snapshots_task_id", "task_id"),
        Index("ix_stage_snapshots_created_at", "created_at"),
        Index("ix_stage_snapshots_to_stage", "to_stage"),
    )
