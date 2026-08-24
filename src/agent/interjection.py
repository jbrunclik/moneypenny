"""Mid-run steering: user guidance injected between tool rounds.

While a multi-round turn is streaming, the user can send a follow-up that
should redirect the work in flight ("stop, wrong ticker") instead of
queueing a whole new turn. The interject route stores the text here; the
graph's check_tool_results node pops it between rounds and injects it as
guidance, so the model course-corrects before its next tool round.

kv_store is the carrier because the interject POST may land on a different
gunicorn worker than the one running the stream - the DB is the only
bridge (module-level state does not cross workers). Keyed by conversation
id: the frontend's double-send guard allows exactly one active request per
conversation, so the key is unambiguous. Entries are popped on consumption
and cleared at turn end, so a missed interjection cannot bleed into a
later turn.
"""

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "interject"


def save_interjection(user_id: str, conv_id: str, text: str) -> None:
    """Store steering text for the conversation's in-flight turn."""
    db.kv_set(user_id, KV_NAMESPACE, conv_id, text)
    logger.info(
        "Interjection saved",
        extra={"user_id": user_id, "conversation_id": conv_id, "length": len(text)},
    )


def pop_interjection(user_id: str, conv_id: str) -> str | None:
    """Read and clear the pending interjection, if any.

    Failures degrade to None - steering is best-effort and must never
    break the running turn.
    """
    try:
        text = db.kv_get(user_id, KV_NAMESPACE, conv_id)
        if text:
            db.kv_delete(user_id, KV_NAMESPACE, conv_id)
            return text
        return None
    except Exception:
        logger.warning("Interjection pop failed", exc_info=True)
        return None


def clear_interjection(user_id: str, conv_id: str) -> None:
    """Discard any unconsumed interjection (called at turn end)."""
    try:
        db.kv_delete(user_id, KV_NAMESPACE, conv_id)
    except Exception:
        logger.debug("Interjection clear failed", exc_info=True)
