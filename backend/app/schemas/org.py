"""Organization and membership API schemas."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import EmailStr, Field, model_validator

from app.schemas.common import BaseSchema, TimestampSchema
from app.schemas.user import UserResponse


class OrganizationRole(str, Enum):
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
    description: Optional[str] = None
    logo_url: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    """Schema for creating an organization."""
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict)


class OrganizationUpdate(BaseSchema):
    """Schema for updating an organization."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    logo_url: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class OrganizationResponse(OrganizationBase, TimestampSchema):
    """Response schema for organization."""
    id: UUID
    settings: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class OrganizationListResponse(BaseSchema):
    """List response for organizations."""
    organizations: List[OrganizationResponse]
    total: int



class OrganizationMemberBase(BaseSchema):
    """Base schema for organization membership."""
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER)


class OrganizationMemberCreate(BaseSchema):
    """Schema for adding a member to an organization."""
    user_id: Optional[UUID] = None
    email: Optional[EmailStr] = None
    role: OrganizationRole = Field(default=OrganizationRole.MEMBER)

    @model_validator(mode='after')
    def check_user_or_email(self):
        if not self.user_id and not self.email:
            raise ValueError('Either user_id or email must be provided')
        return self


class OrganizationMemberUpdate(BaseSchema):
    """Schema for updating organization membership."""
    role: Optional[OrganizationRole] = None
    is_default: Optional[bool] = None


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
    members: List[OrganizationMemberResponse]
    total: int


class OrganizationWithMembershipResponse(OrganizationResponse):
    """Organization response with the current user's membership info."""
    membership: Optional[OrganizationMemberResponse] = None


class UserOrganizationsResponse(BaseSchema):
    """Response with all organizations a user belongs to."""
    organizations: List[OrganizationWithMembershipResponse]
    default_organization: Optional[OrganizationResponse] = None
