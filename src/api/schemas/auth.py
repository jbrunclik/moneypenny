"""Google sign-in, token and current-user schemas."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel


class GoogleAuthRequest(RequestModel):
    """Schema for POST /auth/google."""

    credential: str = Field(..., min_length=1)


class UserResponse(ResponseModel):
    """User information."""

    id: str
    email: str
    name: str
    picture: str | None = None
    is_admin: bool = False


class UserContainerResponse(ResponseModel):
    """Response containing user info (used by /auth/me)."""

    user: UserResponse


class AuthResponse(ResponseModel):
    """Response from successful authentication."""

    token: str = Field(..., description="JWT token for subsequent requests")
    user: UserResponse


class TokenRefreshResponse(ResponseModel):
    """Response from token refresh."""

    token: str = Field(..., description="New JWT token")


class ClientIdResponse(ResponseModel):
    """Response containing Google Client ID."""

    client_id: str
