"""Organization and membership ORM models."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import OrganizationRole

if TYPE_CHECKING:
    # Cross-domain classes are referenced only by string in relationship().
    from app.models.efficiency import TeamChallenge
    from app.models.models import Campaign, Taxonomy
    from app.models.user import User


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    """
    Organization (tenant) for multi-tenancy support.
    All resources (campaigns, taxonomies, etc.) belong to an organization.
    Users can be members of multiple organizations.
    """
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    settings: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    """
    Settings schema:
    {
        "is_system_default": false,
        "max_users": 100,
        "max_storage_gb": 500,
        "features": ["sam2", "3d_annotation"],
        "branding": {
            "primary_color": "#0066cc",
            "logo_url": "https://..."
        }
    }
    """

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign",
        back_populates="organization",
    )
    taxonomies: Mapped[list["Taxonomy"]] = relationship(
        "Taxonomy",
        back_populates="organization",
    )
    challenges: Mapped[list["TeamChallenge"]] = relationship(
        "TeamChallenge",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_organizations_name", "name"),
        Index("ix_organizations_slug", "slug", unique=True),
        Index("ix_organizations_is_active", "is_active"),
    )


class OrganizationMember(Base, TimestampMixin):
    """
    Membership linking users to organizations with specific roles.
    Users can have different roles in different organizations.
    """
    __tablename__ = "organization_members"

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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String(50),
        default=OrganizationRole.MEMBER.value,
        nullable=False,
    )

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="members",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="organization_memberships",
        foreign_keys=[user_id],
    )
    inviter: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[invited_by],
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_organization_members_org_id", "organization_id"),
        Index("ix_organization_members_user_id", "user_id"),
        Index("ix_organization_members_role", "role"),
        Index("ix_organization_members_is_default", "user_id", "is_default"),
    )

    def is_owner(self) -> bool:
        """Check if member is an owner."""
        return self.role == OrganizationRole.OWNER.value

    def is_admin(self) -> bool:
        """Check if member is an admin or owner."""
        return self.role in (OrganizationRole.OWNER.value, OrganizationRole.ADMIN.value)
