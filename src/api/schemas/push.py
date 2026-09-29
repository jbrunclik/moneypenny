"""Web push subscription schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PushKeysResponse(BaseModel):
    """VAPID public key for client-side subscription."""

    enabled: bool
    public_key: str | None = None


class PushSubscriptionKeys(BaseModel):
    """Encryption keys from PushSubscription.toJSON()."""

    p256dh: str = Field(..., min_length=1, max_length=512)
    auth: str = Field(..., min_length=1, max_length=512)


class PushSubscribeRequest(BaseModel):
    """Browser PushSubscription payload."""

    endpoint: str = Field(..., min_length=1, max_length=2048)
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    """Remove a subscription by its endpoint."""

    endpoint: str = Field(..., min_length=1, max_length=2048)


class PushSubscribeResponse(BaseModel):
    """Result of storing a subscription."""

    success: bool
    subscription_id: str
