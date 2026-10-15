"""User account API schemas."""
from typing import List, Optional
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.common import BaseSchema, TimestampSchema, UserRole


class UserBase(BaseSchema):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: Optional[str] = None
    role: UserRole = Field(default=UserRole.ANNOTATOR)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseSchema):
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase, TimestampSchema):
    id: UUID
    is_active: bool
    is_superuser: bool


class UserWithPermissionsResponse(UserResponse):
    """User response including computed permissions."""
    permissions: List[str] = Field(default_factory=list)
