"""Web Push routes: VAPID key discovery and subscription management.

The client (core/push.ts) fetches the VAPID public key, subscribes via
the browser PushManager, and stores the resulting subscription here.
Sends happen server-side via src/utils/push.py.
"""

from typing import Any

from apiflask import APIBlueprint
from flask import request

from src.api.schemas import (
    PushKeysResponse,
    PushSubscribeRequest,
    PushSubscribeResponse,
    PushUnsubscribeRequest,
    StatusResponse,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger
from src.utils.push import send_push_to_user_sync

logger = get_logger(__name__)

api = APIBlueprint("push", __name__, url_prefix="/api/push", tag="Push")


@api.route("/vapid-public-key", methods=["GET"])
@api.output(PushKeysResponse)
@require_auth
def get_vapid_public_key(user: User) -> dict[str, Any]:
    """VAPID public key the client needs for PushManager.subscribe()."""
    return {
        "enabled": Config.push_enabled(),
        "public_key": Config.VAPID_PUBLIC_KEY or None,
    }


@api.route("/subscriptions", methods=["POST"])
@api.output(PushSubscribeResponse)
@require_auth
@validate_request(PushSubscribeRequest)
def subscribe(user: User, data: PushSubscribeRequest) -> dict[str, Any]:
    """Store (or refresh) a device's push subscription."""
    subscription = db.save_push_subscription(
        user_id=user.id,
        endpoint=data.endpoint,
        p256dh=data.keys.p256dh,
        auth=data.keys.auth,
        user_agent=request.headers.get("User-Agent"),
    )
    return {"success": True, "subscription_id": subscription.id}


@api.route("/subscriptions", methods=["DELETE"])
@api.output(StatusResponse)
@require_auth
@validate_request(PushUnsubscribeRequest)
def unsubscribe(user: User, data: PushUnsubscribeRequest) -> dict[str, str]:
    """Remove a device's push subscription (settings toggle off)."""
    db.delete_push_subscription(data.endpoint, user_id=user.id)
    return {"status": "ok"}


@api.route("/test", methods=["POST"])
@api.output(StatusResponse)
@require_auth
def send_test(user: User) -> dict[str, str]:
    """Send a test notification to the caller's devices.

    Synchronous on purpose - the user is waiting to see whether the
    pipeline works end to end (essential for debugging iOS).
    """
    delivered = send_push_to_user_sync(
        user.id,
        "Test notification",
        "Web push is working on this device.",
        url="/",
        tag="push-test",
    )
    if delivered == 0:
        return {"status": "no_subscriptions"}
    return {"status": "ok"}
