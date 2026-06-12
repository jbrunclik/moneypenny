"""Web Push send pipeline.

send_push_to_user() delivers a notification to every subscription a user
has (iPhone PWA, desktop Chrome, ...). Sends run on a daemon thread so
callers (agent executor, request handlers) never block on push-service
round trips. Subscriptions rejected with 404/410 are deleted.

Stateless across gunicorn workers: any worker can send; subscriptions
live in SQLite.
"""

from __future__ import annotations

import json
import threading

from pywebpush import WebPushException, webpush

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Push service status codes meaning the subscription is gone for good
_SUBSCRIPTION_GONE_CODES = {404, 410}


def _vapid_claims() -> dict[str, str]:
    email = Config.VAPID_CLAIMS_EMAIL or Config.CONTACT_EMAIL
    return {"sub": f"mailto:{email}"}


def send_to_subscription(
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, object],
) -> bool:
    """Send one push message synchronously.

    Returns True on success. Raises WebPushException on failure so the
    caller can decide whether the subscription should be pruned.
    """
    webpush(
        subscription_info={
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        },
        data=json.dumps(payload),
        vapid_private_key=Config.VAPID_PRIVATE_KEY,
        vapid_claims=_vapid_claims(),
        timeout=Config.PUSH_SEND_TIMEOUT,
    )
    return True


def send_push_to_user_sync(
    user_id: str,
    title: str,
    body: str,
    url: str | None,
    tag: str | None,
) -> int:
    """Send to all of a user's subscriptions; returns delivered count."""
    # Imported here so tests can patch src.db.models.db and to avoid
    # import cycles at module load
    from src.db.models import db

    subscriptions = db.get_push_subscriptions(user_id)
    if not subscriptions:
        logger.debug("No push subscriptions for user", extra={"user_id": user_id})
        return 0

    payload: dict[str, object] = {"title": title, "body": body}
    if url:
        payload["url"] = url
    if tag:
        payload["tag"] = tag

    delivered = 0
    for sub in subscriptions:
        try:
            send_to_subscription(sub.endpoint, sub.p256dh, sub.auth, payload)
            db.touch_push_subscription(sub.id)
            delivered += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in _SUBSCRIPTION_GONE_CODES:
                db.delete_push_subscription(sub.endpoint)
                logger.info(
                    "Pruned expired push subscription",
                    extra={"user_id": user_id, "status": status},
                )
            else:
                logger.warning(
                    "Push send failed",
                    extra={"user_id": user_id, "status": status, "error": str(e)},
                )
        except Exception:
            logger.warning("Push send failed unexpectedly", exc_info=True)

    logger.info(
        "Push notifications sent",
        extra={"user_id": user_id, "delivered": delivered, "total": len(subscriptions)},
    )
    return delivered


def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    url: str | None = None,
    tag: str | None = None,
) -> None:
    """Fire-and-forget push to all of a user's devices.

    No-op when VAPID keys aren't configured. Runs on a daemon thread so
    the caller never waits on push-service round trips.

    Args:
        user_id: Recipient user
        title: Notification title
        body: Notification body (keep it to a line or two)
        url: In-app URL to open on tap (e.g. "/#/conversations/<id>")
        tag: Coalescing key - a new notification with the same tag
            replaces the previous one instead of stacking
    """
    if not Config.push_enabled():
        return

    # NOT a daemon thread: the agent scheduler is a run-and-exit systemd
    # process, and daemon threads are killed at interpreter exit - the
    # 07:20 briefing saved its message but its push died here. A
    # non-daemon thread blocks exit for at most PUSH_SEND_TIMEOUT per
    # subscription, which is fine for both the scheduler and gunicorn.
    thread = threading.Thread(
        target=send_push_to_user_sync,
        args=(user_id, title, body, url, tag),
        name=f"push-send-{user_id[:8]}",
        daemon=False,
    )
    thread.start()
