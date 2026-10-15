"""Authentication and SSO API schemas: login, tokens, roles, current user."""

from pydantic import BaseModel, Field


class TokenUser(BaseModel):
    """User info included in token response."""
    id: str
    email: str
    username: str
    full_name: str | None
    role: str
    is_superuser: bool
    permissions: list[str]
    must_change_password: bool = False


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    user: TokenUser


class LoginRequest(BaseModel):
    """Login request body."""
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    """Password change request."""
    current_password: str
    new_password: str = Field(..., min_length=8)


class RoleInfo(BaseModel):
    """Role information."""
    name: str
    value: str
    description: str
    permissions: list[str]


class CurrentUserResponse(BaseModel):
    """Current user response with permissions."""
    id: str
    email: str
    username: str
    full_name: str | None
    role: str
    is_active: bool
    is_superuser: bool
    permissions: list[str]
    must_change_password: bool = False


class ProviderInfo(BaseModel):
    """Public information about a configured SSO provider."""

    provider: str
    name: str
    login_url: str


class SSOTokenResponse(BaseModel):
    """JWT response after a successful SSO callback (mirrors Token schema)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: TokenUser
