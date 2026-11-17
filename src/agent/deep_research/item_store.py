"""Finished sub-question results, kept so a retried run re-runs only what is missing.

A deploy or a crash kills a running deep research; the user's Retry reopens
the same offer and starts a new run (plan.reopen_offer). Each sub-question
that finished is saved here as it finishes, keyed by the offer message and
the sub-question text, so the retry reuses it instead of paying a subagent
again; an edited or new sub-question runs. Entries older than
DEEP_RESEARCH_ITEM_KEEP_SECONDS are dropped on every save.
"""

import hashlib
import json

from src.agent.deep_research.subagent import ItemResult
from src.agent.source_pages import SourcePage
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "deep_research_items"


def _key(offer_message_id: str, question: str) -> str:
    digest = hashlib.sha256(question.strip().encode()).hexdigest()[:16]
    return f"{offer_message_id}:{digest}"


def save_item(user_id: str, offer_message_id: str, question: str, result: ItemResult) -> None:
    """Keep a finished item (status done); never raises into the run."""
    if result.status != "done":
        return
    limit = Config.DEEP_RESEARCH_PAGE_MAX_CHARS  # the writer never sees more of a page
    value = {
        "digest": result.digest,
        "pages": [{"title": p.title, "url": p.url, "text": p.text[:limit]} for p in result.pages],
    }
    try:
        db.kv_delete_older_than(user_id, KV_NAMESPACE, Config.DEEP_RESEARCH_ITEM_KEEP_SECONDS)
        db.kv_set(user_id, KV_NAMESPACE, _key(offer_message_id, question), json.dumps(value))
    except Exception:
        logger.warning("Deep research item not saved", exc_info=True)


def load_item(user_id: str, offer_message_id: str, question: str, index: int) -> ItemResult | None:
    """A saved result for this sub-question of this offer, as item ``index``."""
    try:
        raw = db.kv_get(user_id, KV_NAMESPACE, _key(offer_message_id, question))
        if not raw:
            return None
        value = json.loads(raw)
        pages = [SourcePage(p["title"], p["url"], p["text"]) for p in value["pages"]]
        return ItemResult(index, "done", str(value["digest"]), pages, {})
    except Exception:
        logger.warning("Deep research item not loaded", exc_info=True)
        return None
