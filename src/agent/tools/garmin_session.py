"""Cached Garmin Connect client sessions.

Building a Garmin client is far from free: `Garmin.login(tokenstore=...)`
always calls `_load_profile_and_settings()`, which makes TWO extra HTTP round
trips to Garmin (social profile + user settings, each with a 3-attempt retry
loop) before a single byte of the data we actually asked for is fetched. Doing
that per tool call meant a Sep 2026 audit's 93 `garmin_connect` calls paid
~186 pointless round trips.

The client is therefore cached per user for a short TTL. Correctness across
gunicorn workers is preserved by fingerprinting the stored token on every
lookup: the DB read is local and cheap, and a reconnect (which rewrites the
token) invalidates every worker's cached client immediately rather than after
the TTL. The TTL only bounds how long a session may live before we rebuild it.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# user_id -> (client, token_fingerprint, expires_at_monotonic, last_persisted_token)
_sessions: OrderedDict[str, list[Any]] = OrderedDict()
_lock = threading.Lock()

# Distinct users whose sessions are held per worker. Family-sized deployment;
# the cap only guards against unbounded growth.
_MAX_SESSIONS = 16


def _fingerprint(token: str) -> str:
    """Stable short digest of a serialized token blob."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def get_client(user_id: str) -> Any | None:
    """An authenticated Garmin client for `user_id`, reusing a live session.

    Returns None when the user has no Garmin token or the session cannot be
    restored - callers surface that as "Garmin not connected".
    """
    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user or not user.garmin_token:
        return None

    fingerprint = _fingerprint(user.garmin_token)
    now = time.monotonic()

    with _lock:
        entry = _sessions.get(user_id)
        if entry and entry[1] == fingerprint and entry[2] > now:
            _sessions.move_to_end(user_id)
            logger.debug("Reusing cached Garmin session", extra={"user_id": user_id})
            return entry[0]

    # Build outside the lock: login() is a network call and must not block
    # another user's cache lookup.
    try:
        from src.auth.garmin_auth import create_client_from_tokens

        client = create_client_from_tokens(user.garmin_token)
    except Exception as e:
        logger.warning("Failed to create Garmin client", extra={"error": str(e)})
        return None

    with _lock:
        _sessions[user_id] = [
            client,
            fingerprint,
            now + Config.GARMIN_SESSION_TTL_SECONDS,
            user.garmin_token,
        ]
        _sessions.move_to_end(user_id)
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)

    logger.debug("Created Garmin session", extra={"user_id": user_id})
    return client


def persist_tokens_if_changed(user_id: str, client: Any) -> None:
    """Write back tokens only when garth actually rotated them.

    Previously every API call re-serialized and wrote the token row, so one
    `get_activity_details` (four Garmin endpoints) meant four identical DB
    writes. garth refreshes tokens rarely, so comparing against the last value
    we stored turns that into ~zero writes.
    """
    from src.db.models import db

    try:
        from src.auth.garmin_auth import refresh_and_serialize

        current = refresh_and_serialize(client)
    except Exception as e:
        logger.debug("Failed to serialize Garmin tokens", extra={"error": str(e)})
        return

    with _lock:
        entry = _sessions.get(user_id)
        if entry and entry[3] == current:
            return

    try:
        db.update_user_garmin_token(user_id, current)
    except Exception as e:
        logger.debug("Failed to persist refreshed Garmin tokens", extra={"error": str(e)})
        return

    with _lock:
        entry = _sessions.get(user_id)
        if entry:
            entry[1] = _fingerprint(current)
            entry[3] = current


def clear_sessions() -> None:
    """Drop all cached sessions (tests, and after a Garmin disconnect)."""
    with _lock:
        _sessions.clear()
