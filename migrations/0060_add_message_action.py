"""Add action to messages and convert old look-up messages.

Action messages (docs/superpowers/specs/2026-10-03-deep-research-design.md):
a user message the app sent on the user's behalf records what it was -
{"type": "verify_claim", source_message_id, claim_index, quote} for Look it
up on a claim card, {"type": "deep_research", offer_message_id, items,
minutes} for starting a run. The content stays the instruction the model saw.

Look-up messages sent before this ("Dohledej a ověř: …" / "Look up and
verify: …") become verify_claim actions, linked to the nearest earlier
answer in the conversation that has the quoted claim. Self-contained on
purpose: later code changes must not change what this migration does.
"""

import json
import re
from typing import Any

from yoyo import step

__depends__ = {"0059_add_message_research"}

_PREFIXES = ("Dohledej a ověř: ", "Look up and verify: ")
# The client sent the claim's quote without markdown (ClaimCard.plainQuote)
_MARKDOWN = re.compile(r"\*\*|__|[*_`]|\]\([^)]*\)|[\[\]]")


def _plain(quote: str) -> str:
    return _MARKDOWN.sub("", quote).strip()


def _source(conn: Any, conv_id: str, before: str, quote: str) -> tuple[str | None, int | None]:
    """The nearest earlier answer with this claim, and the claim's index."""
    rows = conn.execute(
        "SELECT id, annotations FROM messages WHERE conversation_id = ? AND role = 'assistant' "
        "AND created_at < ? AND annotations IS NOT NULL ORDER BY created_at DESC",
        (conv_id, before),
    ).fetchall()
    for msg_id, raw in rows:
        for index, ann in enumerate(json.loads(raw)):
            if _plain(str(ann.get("quote", ""))) == quote:
                return msg_id, index
    return None, None


def convert(conn: Any) -> None:
    rows = conn.execute(
        "SELECT id, conversation_id, created_at, content FROM messages WHERE role = 'user' "
        "AND (content LIKE 'Dohledej a ověř: %' OR content LIKE 'Look up and verify: %')"
    ).fetchall()
    for msg_id, conv_id, created_at, content in rows:
        prefix = next((p for p in _PREFIXES if content.startswith(p)), None)
        if prefix is None:  # LIKE is case-insensitive for ASCII
            continue
        quote = content[len(prefix) :].strip()
        source_id, index = _source(conn, conv_id, created_at, quote)
        action = {
            "type": "verify_claim",
            "source_message_id": source_id,
            "claim_index": index,
            "quote": quote,
        }
        conn.execute(
            "UPDATE messages SET action = ? WHERE id = ?",
            (json.dumps(action, ensure_ascii=False), msg_id),
        )
    conn.commit()


def forget(conn: Any) -> None:
    """Rollback of the conversion (the column itself is dropped next)."""
    conn.execute("UPDATE messages SET action = NULL")
    conn.commit()


steps = [
    step(
        "ALTER TABLE messages ADD COLUMN action TEXT",
        "ALTER TABLE messages DROP COLUMN action",
    ),
    step(convert, forget),
]
