"""Server-side OAuth state storage and validation (S7).

The OAuth `state` parameter is the CSRF defense for the authorization-code
flow. Previously the server generated it, handed it to the client and never
saw it again - validation was left entirely to the frontend, so a forged
callback could connect an attacker-chosen provider account to the victim's
profile. States are now stored server-side (kv_store survives the multi-
worker gunicorn setup), are single-use, and expire after a short TTL.
"""

import time
import uuid
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Generous window to click through the provider's consent screens
OAUTH_STATE_TTL_SECONDS = 600

_NAMESPACE = "oauth_state"


def _db() -> Any:
    # Resolved at call time so test fixtures patching src.db.models.db apply
    from src.db.models import db

    return db


def issue_state(user_id: str, provider: str) -> str:
    """Create and persist a fresh state token for the user/provider."""
    _prune_expired(user_id, provider)
    state = str(uuid.uuid4())
    _db().kv_set(user_id, _NAMESPACE, f"{provider}:{state}", str(time.time()))
    return state


def consume_state(user_id: str, provider: str, state: str) -> bool:
    """Validate a callback state and invalidate it (single-use).

    Returns False for unknown, already-used or expired states.
    """
    key = f"{provider}:{state}"
    raw = _db().kv_get(user_id, _NAMESPACE, key)
    if raw is None:
        logger.warning(
            "OAuth state rejected (unknown or already used)",
            extra={"user_id": user_id, "provider": provider},
        )
        return False

    # Single-use: delete before checking expiry so a replay always fails
    _db().kv_delete(user_id, _NAMESPACE, key)

    try:
        issued_at = float(raw)
    except ValueError:
        return False
    if time.time() - issued_at > OAUTH_STATE_TTL_SECONDS:
        logger.warning(
            "OAuth state rejected (expired)",
            extra={"user_id": user_id, "provider": provider},
        )
        return False
    return True


def _prune_expired(user_id: str, provider: str) -> None:
    """Drop expired states so abandoned auth-url clicks don't accumulate."""
    try:
        now = time.time()
        for key, value in _db().kv_list(user_id, _NAMESPACE, prefix=f"{provider}:"):
            try:
                expired = now - float(value) > OAUTH_STATE_TTL_SECONDS
            except ValueError:
                expired = True
            if expired:
                _db().kv_delete(user_id, _NAMESPACE, key)
    except Exception:
        logger.debug("OAuth state prune failed", exc_info=True)
