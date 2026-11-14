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
conversation, so the key is unambiguous; steering sent before a round reads
it accumulates there (appended, popped in one statement). Entries are popped on consumption,
cleared when a turn starts (a missed one cannot bleed into the next turn)
and when it ends (the stream producer's / batch route's finally): steering
that arrived after the last tool round used to sit in the store until the
conversation's next turn - forever for a deleted conversation.
"""

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "interject"
# Between steering messages that arrived before one tool round read them
_SEPARATOR = "\n\n"
# The newest this much of the steering waiting for a round is kept - a burst
# of sends cannot grow the stored value or the injected guidance unbounded
INTERJECTION_MAX_CHARS = 8000


def save_interjection(user_id: str, conv_id: str, text: str) -> None:
    """Add steering text for the conversation's in-flight turn.

    Appended, not replaced: two quick messages before the next tool round
    used to keep only the second, and the turn never read the first.
    """
    db.kv_append(user_id, KV_NAMESPACE, conv_id, text, _SEPARATOR, INTERJECTION_MAX_CHARS)
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
        return db.kv_pop(user_id, KV_NAMESPACE, conv_id) or None
    except Exception:
        logger.warning("Interjection pop failed", exc_info=True)
        return None


def clear_interjection(user_id: str, conv_id: str) -> None:
    """Discard any unconsumed interjection (called at turn end)."""
    try:
        db.kv_delete(user_id, KV_NAMESPACE, conv_id)
    except Exception:
        logger.debug("Interjection clear failed", exc_info=True)
