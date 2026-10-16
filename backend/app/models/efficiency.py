"""ORM models for the efficiency/gamification sub-domain."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AlertSeverity

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship();
    # imported here for type checkers without creating an import cycle.
    from app.models.models import Organization, Task, User


class TimeSession(Base):
    """
    Tracks actual working sessions on tasks.
    Created when user opens a task, updated via heartbeats,
    closed when user leaves or goes idle.
    """
    __tablename__ = "time_sessions"

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

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    session_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    session_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    active_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    idle_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    heartbeat_count: Mapped[int] = mapped_column(Integer, default=0)
    action_count: Mapped[int] = mapped_column(Integer, default=0)
    annotations_created: Mapped[int] = mapped_column(Integer, default=0)
    annotations_updated: Mapped[int] = mapped_column(Integer, default=0)
    annotations_deleted: Mapped[int] = mapped_column(Integer, default=0)
    frames_visited: Mapped[int] = mapped_column(Integer, default=0)

    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False)

    client_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    """
    {
        "browser": "Chrome",
        "os": "Windows",
        "screen_resolution": "1920x1080",
        "timezone": "UTC+5:30"
    }
    """

    user: Mapped["User"] = relationship("User", back_populates="time_sessions")
    task: Mapped["Task"] = relationship("Task", back_populates="time_sessions")
    activity_events: Mapped[list["ActivityEvent"]] = relationship(
        "ActivityEvent",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_time_sessions_user_id", "user_id"),
        Index("ix_time_sessions_task_id", "task_id"),
        Index("ix_time_sessions_session_start", "session_start"),
        Index("ix_time_sessions_is_active", "is_active"),
        Index("ix_time_sessions_user_task_active", "user_id", "task_id", "is_active"),
    )


class UserLoginSession(Base):
    """
    Tracks global login sessions - time spent in the application.
    Independent of tasks. Active when user is logged in and window is focused.

    Activity is determined by:
    - Window has focus (not minimized/hidden tab)
    - Mouse is inside the browser window
    - Recent interaction (mouse/keyboard within threshold)
    """
    __tablename__ = "user_login_sessions"

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

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )

    session_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    session_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    active_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    idle_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    heartbeat_count: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_window_focused: Mapped[bool] = mapped_column(Boolean, default=True)
    is_mouse_in_window: Mapped[bool] = mapped_column(Boolean, default=True)

    client_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    """
    {
        "browser": "Chrome",
        "os": "Windows",
        "screen_resolution": "1920x1080",
        "timezone": "UTC+5:30",
        "user_agent": "..."
    }
    """

    user: Mapped["User"] = relationship("User", back_populates="login_sessions")

    __table_args__ = (
        Index("ix_user_login_sessions_user_id", "user_id"),
        Index("ix_user_login_sessions_is_active", "is_active"),
        Index("ix_user_login_sessions_session_start", "session_start"),
        Index("ix_user_login_sessions_user_active", "user_id", "is_active"),
    )


class ActivityEvent(Base):
    """
    Granular activity events for engagement tracking.
    Used to calculate productivity metrics and detect patterns.
    """
    __tablename__ = "activity_events"

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

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("time_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    """
    Examples:
    - annotation_create: {"annotation_id": "...", "class": "car", "type": "cuboid"}
    - frame_change: {"from_frame": 10, "to_frame": 15}
    - tool_change: {"from_tool": "select", "to_tool": "cuboid"}
    """

    user: Mapped["User"] = relationship("User", back_populates="activity_events")
    task: Mapped[Optional["Task"]] = relationship(
        "Task", back_populates="activity_events"
    )
    session: Mapped[Optional["TimeSession"]] = relationship(
        "TimeSession",
        back_populates="activity_events",
    )

    __table_args__ = (
        Index("ix_activity_events_user_id", "user_id"),
        Index("ix_activity_events_task_id", "task_id"),
        Index("ix_activity_events_session_id", "session_id"),
        Index("ix_activity_events_timestamp", "timestamp"),
        Index("ix_activity_events_event_type", "event_type"),
        Index("ix_activity_events_user_timestamp", "user_id", "timestamp"),
    )


class UserGoal(Base):
    """
    Personal and assigned goals for annotators.
    Tracks progress toward daily/weekly targets.
    """
    __tablename__ = "user_goals"

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

    goal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0)

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    is_achieved: Mapped[bool] = mapped_column(Boolean, default=False)
    achieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_self_assigned: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
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

    user: Mapped["User"] = relationship(
        "User",
        back_populates="goals",
        foreign_keys=[user_id],
    )
    assigned_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assigned_by_id],
    )

    __table_args__ = (
        Index("ix_user_goals_user_id", "user_id"),
        Index("ix_user_goals_period", "period_start", "period_end"),
        Index("ix_user_goals_user_period", "user_id", "period_start", "period_end"),
    )


class Achievement(Base):
    """
    Achievements/badges earned by users.
    Part of the gamification system.
    """
    __tablename__ = "achievements"

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

    achievement_type: Mapped[str] = mapped_column(String(50), nullable=False)

    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    achievement_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    """
    {
        "trigger_task_id": "...",
        "trigger_value": 100,
        "description": "Completed 100 labels in one day"
    }
    """

    is_seen: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="achievements")

    __table_args__ = (
        Index("ix_achievements_user_id", "user_id"),
        Index("ix_achievements_type", "achievement_type"),
        Index("ix_achievements_earned_at", "earned_at"),
        UniqueConstraint("user_id", "achievement_type", name="uq_user_achievement"),
    )


class PerformanceAlert(Base):
    """
    Alerts generated when performance metrics fall below thresholds.
    For manager visibility into team issues.
    """
    __tablename__ = "performance_alerts"

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

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )

    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20),
        default=AlertSeverity.WARNING.value,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    """
    {
        "current_velocity": 5,
        "average_velocity": 12,
        "drop_percentage": 58,
        "period_days": 7
    }
    """

    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="performance_alerts",
        foreign_keys=[user_id],
    )
    task: Mapped[Optional["Task"]] = relationship(
        "Task", back_populates="performance_alerts"
    )
    acknowledged_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[acknowledged_by_id],
    )

    __table_args__ = (
        Index("ix_performance_alerts_user_id", "user_id"),
        Index("ix_performance_alerts_task_id", "task_id"),
        Index("ix_performance_alerts_severity", "severity"),
        Index("ix_performance_alerts_created_at", "created_at"),
        Index("ix_performance_alerts_is_acknowledged", "is_acknowledged"),
    )


class DailyUserStats(Base):
    """
    Pre-aggregated daily statistics per user.
    Updated periodically for efficient dashboard queries.
    """
    __tablename__ = "daily_user_stats"

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

    stats_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    labels_created: Mapped[int] = mapped_column(Integer, default=0)
    labels_updated: Mapped[int] = mapped_column(Integer, default=0)
    labels_deleted: Mapped[int] = mapped_column(Integer, default=0)

    tasks_started: Mapped[int] = mapped_column(Integer, default=0)
    tasks_submitted: Mapped[int] = mapped_column(Integer, default=0)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_rejected: Mapped[int] = mapped_column(Integer, default=0)

    total_active_time: Mapped[int] = mapped_column(Integer, default=0)
    total_idle_time: Mapped[int] = mapped_column(Integer, default=0)
    total_session_count: Mapped[int] = mapped_column(Integer, default=0)

    labels_per_hour: Mapped[float] = mapped_column(Float, default=0)
    first_time_accept_rate: Mapped[float] = mapped_column(Float, default=0)

    frames_annotated: Mapped[int] = mapped_column(Integer, default=0)

    current_streak_days: Mapped[int] = mapped_column(Integer, default=0)

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

    user: Mapped["User"] = relationship("User", back_populates="daily_stats")

    __table_args__ = (
        Index("ix_daily_user_stats_user_id", "user_id"),
        Index("ix_daily_user_stats_date", "stats_date"),
        UniqueConstraint("user_id", "stats_date", name="uq_user_daily_stats"),
    )


class TeamChallenge(Base):
    """
    Team-wide challenges for gamification.
    Creates collective goals and friendly competition.
    """
    __tablename__ = "team_challenges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    goal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0)

    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
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

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="challenges"
    )
    created_by: Mapped[Optional["User"]] = relationship("User")
    participants: Mapped[list["ChallengeParticipant"]] = relationship(
        "ChallengeParticipant",
        back_populates="challenge",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_team_challenges_org_id", "organization_id"),
        Index("ix_team_challenges_active", "is_active"),
        Index("ix_team_challenges_dates", "start_date", "end_date"),
    )


class ChallengeParticipant(Base):
    """
    Individual participation in team challenges.
    Tracks each user's contribution.
    """
    __tablename__ = "challenge_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("team_challenges.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    contribution_value: Mapped[float] = mapped_column(Float, default=0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_contribution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    challenge: Mapped["TeamChallenge"] = relationship(
        "TeamChallenge",
        back_populates="participants",
    )
    user: Mapped["User"] = relationship(
        "User", back_populates="challenge_participations"
    )

    __table_args__ = (
        Index("ix_challenge_participants_challenge_id", "challenge_id"),
        Index("ix_challenge_participants_user_id", "user_id"),
        UniqueConstraint("challenge_id", "user_id", name="uq_challenge_participant"),
    )
