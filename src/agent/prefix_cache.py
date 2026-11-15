"""Which fixed prefix a model call sent, and how long since anyone sent it.

Gemini 4 has implicit caching only: a call's prefix (model, system prompt,
tool declarations) is cheap when the same prefix was sent minutes before, by
any user. Per-user tool sets would split the one prefix the users share; this
records the data that decides whether that pays
(docs/superpowers/specs/2026-11-15-cost-telemetry-design.md).

The "last sent" record is one kv row per prefix, shared by all workers. Two
workers writing at once can lose an update: it skews one gap, never errors.
"""

from __future__ import annotations

import hashlib

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_USER_ID = "__system__"
_NAMESPACE = "prefix-cache"


def prefix_key(model_name: str, system_text: str, tools: str) -> str:
    """8 hex characters naming the prefix: the model, the system prompt and
    the bound tool declarations as sent."""
    digest = hashlib.sha256("\x00".join((model_name, system_text, tools)).encode())
    return digest.hexdigest()[:8]


def note_prefix_sent(key: str, user_id: str | None, now: float) -> tuple[float | None, bool | None]:
    """Record that ``user_id`` sent prefix ``key`` at ``now`` (epoch seconds);
    return (seconds since it was last sent, whether by the same user), or
    (None, None) the first time or when the store fails."""
    try:
        previous = db.kv_get(_SYSTEM_USER_ID, _NAMESPACE, key)
        db.kv_set(_SYSTEM_USER_ID, _NAMESPACE, key, f"{now}|{user_id or ''}")
    except Exception:  # telemetry must not break the call it measures
        logger.warning("Prefix record failed", exc_info=True)
        return None, None
    if not previous:
        return None, None
    sent_at, _, sender = previous.partition("|")
    try:
        return round(now - float(sent_at), 1), sender == (user_id or "")
    except ValueError:
        return None, None


# Gemini's implicit cache lasts minutes: a prefix not sent for a day counts as
# never sent. Delegate subagents send per-task prompts (a new key each), so the
# records are purged by the scheduler pass instead of growing forever.
PREFIX_RECORD_MAX_AGE_SECONDS = 86_400


def purge_old_prefix_records() -> int:
    """Delete prefix records not sent for a day; how many."""
    return db.kv_delete_older_than(_SYSTEM_USER_ID, _NAMESPACE, PREFIX_RECORD_MAX_AGE_SECONDS)
