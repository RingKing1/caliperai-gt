"""Organization and membership API schemas."""
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional
from uuid import UUID

from pydantic import EmailStr, Field, model_validator

from app.schemas.common import BaseSchema, TimestampSchema
from app.schemas.user import UserResponse


class OrganizationRole(StrEnum):
    """Roles within an organization."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationBase(BaseSchema):
    """Base schema for organization."""
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(
        ...,
        min_length=2,
        max_length=100,
        pattern=r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$',
    )
    description: str | None = None
    logo_url: str | None = None


class OrganizationCreate(OrganizationBase):
    """Schema for creating an organization."""
    settings: dict[str, Any] | None = Field(default_factory=dict)


class OrganizationUpdate(BaseSchema):
    """Schema for updating an organization."""
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    logo_url: str | None = None
    settings: dict[str, Any] | None = None
    is_active: bool | None = None


class OrganizationResponse(OrganizationBase, TimestampSchema):
    """Response schema for organization."""
    id: UUID
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class OrganizationListResponse(BaseSchema):
    """List response for organizations."""
    organizations: list[OrganizationResponse]
    total: int



class OrganizationMemberBase(BaseSchema):
    """Base schema for organization membership."""
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER)


class OrganizationMemberCreate(BaseSchema):
    """Schema for adding a member to an organization."""
    user_id: UUID | None = None
    email: EmailStr | None = None
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER)

    @model_validator(mode='after')
    def check_user_or_email(self):
        if not self.user_id and not self.email:
            raise ValueError('Either user_id or email must be provided')
        return self


class OrganizationMemberUpdate(BaseSchema):
    """Schema for updating organization membership."""
    role: OrganizationRole | None = None
    is_default: bool | None = None


class OrganizationMemberResponse(OrganizationMemberBase, TimestampSchema):
    """Response schema for organization membership."""
    id: UUID
    organization_id: UUID
    user_id: UUID
    is_default: bool
    joined_at: datetime
    user: Optional["UserResponse"] = None


class OrganizationMemberListResponse(BaseSchema):
    """List response for organization members."""
    members: list[OrganizationMemberResponse]
    total: int


class OrganizationWithMembershipResponse(OrganizationResponse):
    """Organization response with the current user's membership info."""
    membership: OrganizationMemberResponse | None = None


class UserOrganizationsResponse(BaseSchema):
    """Response with all organizations a user belongs to."""
    organizations: list[OrganizationWithMembershipResponse]
    default_organization: OrganizationResponse | None = None
