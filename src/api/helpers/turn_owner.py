"""Which worker process runs a turn, so a turn whose worker died is known dead at once.

Nov 14 2026: a worker died mid-turn (SIGABRT) and the user's next message was
accepted as steering for the dead turn ~100 s later - nobody ever answered
it. The journal stall rule (STREAM_RESUME_STALL_SECONDS, 180 s) is the only
other proof of death. A turn records its worker's pid when it saves its
reply placeholder; every gunicorn worker runs on this one host, so a pid
that no longer exists means the turn is dead.
"""

import os

from src.db.models import db
from src.services.gemini_file_cache import SYSTEM_KV_USER_ID
from src.utils.logging import get_logger

logger = get_logger(__name__)

NAMESPACE = "turn_owner"


def record_turn_owner(message_id: str) -> None:
    """This process runs the turn whose reply is `message_id` (best effort)."""
    try:
        db.kv_set(SYSTEM_KV_USER_ID, NAMESPACE, message_id, str(os.getpid()))
    except Exception:
        logger.warning(
            "Failed to record the turn's worker", extra={"message_id": message_id}, exc_info=True
        )


def turn_owner_gone(message_id: str) -> bool:
    """Whether the turn's worker process no longer exists (False when unknown)."""
    try:
        raw = db.kv_get(SYSTEM_KV_USER_ID, NAMESPACE, message_id)
    except Exception:
        logger.warning("Failed to read the turn's worker", exc_info=True)
        return False
    if not raw or not raw.isdigit():
        return False
    pid = int(raw)
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:  # exists, another user's process
        return False
    return False


def sweep_turn_owners(max_age_seconds: int) -> None:
    """Forget owners older than any turn can run."""
    try:
        db.kv_delete_older_than(SYSTEM_KV_USER_ID, NAMESPACE, max_age_seconds)
    except Exception:
        logger.warning("Turn owner sweep failed", exc_info=True)
