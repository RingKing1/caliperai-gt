"""User account and SSO identity ORM models."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
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
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(
        String(50),
        default=UserRole.ANNOTATOR.value,
        nullable=False,
    )

    assigned_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
    )
    reviewed_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="reviewer",
        foreign_keys="Task.reviewer_id",
    )
    organization_memberships: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="user",
        foreign_keys="OrganizationMember.user_id",
        cascade="all, delete-orphan",
    )

    time_sessions: Mapped[List["TimeSession"]] = relationship(
        "TimeSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    login_sessions: Mapped[List["UserLoginSession"]] = relationship(
        "UserLoginSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[List["ActivityEvent"]] = relationship(
        "ActivityEvent",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    goals: Mapped[List["UserGoal"]] = relationship(
        "UserGoal",
        back_populates="user",
        foreign_keys="UserGoal.user_id",
        cascade="all, delete-orphan",
    )
    achievements: Mapped[List["Achievement"]] = relationship(
        "Achievement",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_stats: Mapped[List["DailyUserStats"]] = relationship(
        "DailyUserStats",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    performance_alerts: Mapped[List["PerformanceAlert"]] = relationship(
        "PerformanceAlert",
        back_populates="user",
        foreign_keys="PerformanceAlert.user_id",
        cascade="all, delete-orphan",
    )
    challenge_participations: Mapped[List["ChallengeParticipant"]] = relationship(
        "ChallengeParticipant",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sso_identities: Mapped[List["UserSSOIdentity"]] = relationship(
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
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_claims: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
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
