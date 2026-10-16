"""User account and SSO identity ORM models."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.enums import ROLE_PERMISSIONS, Permission, UserRole

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.models import (
        Achievement,
        ActivityEvent,
        ChallengeParticipant,
        ChatSession,
        DailyUserStats,
        OrganizationMember,
        PerformanceAlert,
        Task,
        TimeSession,
        UserGoal,
        UserLoginSession,
    )


class User(Base, TimestampMixin):
    """User accounts for annotation platform."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(
        String(50),
        default=UserRole.ANNOTATOR.value,
        nullable=False,
    )

    assigned_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
    )
    reviewed_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="reviewer",
        foreign_keys="Task.reviewer_id",
    )
    organization_memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="user",
        foreign_keys="OrganizationMember.user_id",
        cascade="all, delete-orphan",
    )

    time_sessions: Mapped[list["TimeSession"]] = relationship(
        "TimeSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    login_sessions: Mapped[list["UserLoginSession"]] = relationship(
        "UserLoginSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[list["ActivityEvent"]] = relationship(
        "ActivityEvent",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    goals: Mapped[list["UserGoal"]] = relationship(
        "UserGoal",
        back_populates="user",
        foreign_keys="UserGoal.user_id",
        cascade="all, delete-orphan",
    )
    achievements: Mapped[list["Achievement"]] = relationship(
        "Achievement",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_stats: Mapped[list["DailyUserStats"]] = relationship(
        "DailyUserStats",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    performance_alerts: Mapped[list["PerformanceAlert"]] = relationship(
        "PerformanceAlert",
        back_populates="user",
        foreign_keys="PerformanceAlert.user_id",
        cascade="all, delete-orphan",
    )
    challenge_participations: Mapped[list["ChallengeParticipant"]] = relationship(
        "ChallengeParticipant",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sso_identities: Mapped[list["UserSSOIdentity"]] = relationship(
        "UserSSOIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_role", "role"),
    )

    def has_permission(self, permission: Permission | str) -> bool:
        """Check if user has a specific permission."""
        if self.is_superuser:
            return True

        perm_value = (
            permission.value if isinstance(permission, Permission) else permission
        )
        role_perms = ROLE_PERMISSIONS.get(self.role, set())
        return perm_value in role_perms

    def has_any_permission(self, permissions: list[Permission | str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(p) for p in permissions)

    def has_all_permissions(self, permissions: list[Permission | str]) -> bool:
        """Check if user has all of the specified permissions."""
        return all(self.has_permission(p) for p in permissions)

    @property
    def permissions(self) -> set[str]:
        """Get all permissions for this user."""
        if self.is_superuser:
            return {p.value for p in Permission}
        return ROLE_PERMISSIONS.get(self.role, set()).copy()


class UserSSOIdentity(Base, TimestampMixin):
    """
    Stores the link between a local User account and an SSO identity.
    One user may have multiple SSO identities (one per provider).
    """
    __tablename__ = "user_sso_identities"

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
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_claims: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="sso_identities")

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subject", name="uq_sso_provider_subject"
        ),
        Index("ix_user_sso_identities_user_id", "user_id"),
        Index("ix_user_sso_identities_provider", "provider"),
    )


class AuditLog(Base):
    """
    Tracks all changes for compliance and debugging.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)

    old_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_user_id", "user_id"),
    )
