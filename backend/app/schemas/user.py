"""User account API schemas."""
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.common import BaseSchema, TimestampSchema, UserRole


class UserBase(BaseSchema):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: str | None = None
    role: UserRole = Field(default=UserRole.ANNOTATOR)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseSchema):
    email: EmailStr | None = None
    username: str | None = Field(None, min_length=3, max_length=100)
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(UserBase, TimestampSchema):
    id: UUID
    is_active: bool
    is_superuser: bool


class UserWithPermissionsResponse(UserResponse):
    """User response including computed permissions."""
    permissions: list[str] = Field(default_factory=list)
