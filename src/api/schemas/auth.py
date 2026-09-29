"""Google sign-in, token and current-user schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GoogleAuthRequest(BaseModel):
    """Schema for POST /auth/google."""

    credential: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """User information."""

    id: str
    email: str
    name: str
    picture: str | None = None


class UserContainerResponse(BaseModel):
    """Response containing user info (used by /auth/me)."""

    user: UserResponse


class AuthResponse(BaseModel):
    """Response from successful authentication."""

    token: str = Field(..., description="JWT token for subsequent requests")
    user: UserResponse


class TokenRefreshResponse(BaseModel):
    """Response from token refresh."""

    token: str = Field(..., description="New JWT token")


class ClientIdResponse(BaseModel):
    """Response containing Google Client ID."""

    client_id: str
