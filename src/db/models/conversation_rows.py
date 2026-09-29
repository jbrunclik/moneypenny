"""Row -> dataclass converters and helpers shared by the conversation mixins."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from src.db.models.dataclasses import Conversation
from src.db.models.helpers import build_cursor

_PREVIEW_MAX_CHARS = 120

_MD_PATTERNS = (
    (re.compile(r"```[a-zA-Z0-9_-]*"), " "),  # code fence openers (incl. language)
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links/images -> their text
    (re.compile(r"(\*\*|__|\*|_|`|~~)"), ""),  # emphasis / code markers
    (re.compile(r"^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+", re.MULTILINE), " "),  # block prefixes
)


def build_message_preview(content: str | None) -> str | None:
    """One-line sidebar snippet: markdown stripped to plain text, whitespace
    collapsed, truncated with an ellipsis. Rendering markdown in a one-line
    preview is pointless - raw markers ("**Vezmi...") just read as noise."""
    if not content:
        return None
    text = content
    for pattern, replacement in _MD_PATTERNS:
        text = pattern.sub(replacement, text)
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= _PREVIEW_MAX_CHARS:
        return collapsed
    return collapsed[:_PREVIEW_MAX_CHARS] + "\u2026"


def row_to_conversation(row: sqlite3.Row) -> Conversation:
    """Convert a database row to a Conversation object."""
    # Check if optional columns exist (added in migrations)
    last_reset = None
    if "last_reset" in row.keys():
        last_reset = datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None

    is_agent = False
    agent_id = None
    if "is_agent" in row.keys():
        is_agent = bool(row["is_agent"]) if row["is_agent"] else False
        agent_id = row["agent_id"]

    archived = False
    if "archived" in row.keys():
        archived = bool(row["archived"]) if row["archived"] else False

    pinned = False
    if "pinned" in row.keys():
        pinned = bool(row["pinned"]) if row["pinned"] else False

    is_sports = False
    sports_program = None
    if "is_sports" in row.keys():
        is_sports = bool(row["is_sports"]) if row["is_sports"] else False
        sports_program = row["sports_program"]

    is_language = False
    language_program = None
    if "is_language" in row.keys():
        is_language = bool(row["is_language"]) if row["is_language"] else False
        language_program = row["language_program"]

    anonymous_mode = False
    if "anonymous_mode" in row.keys():
        anonymous_mode = bool(row["anonymous_mode"]) if row["anonymous_mode"] else False

    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        model=row["model"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        is_planning=bool(row["is_planning"]) if row["is_planning"] else False,
        last_reset=last_reset,
        is_agent=is_agent,
        agent_id=agent_id,
        archived=archived,
        pinned=pinned,
        is_sports=is_sports,
        sports_program=sports_program,
        is_language=is_language,
        language_program=language_program,
        anonymous_mode=anonymous_mode,
    )


def row_to_conversation_summary(row: sqlite3.Row) -> tuple[Conversation, int, str | None]:
    """(Conversation, message_count, last-message preview) for sidebar listings."""
    return (
        row_to_conversation(row),
        int(row["message_count"]),
        build_message_preview(row["last_message"]),
    )


def page_rows(rows: list[sqlite3.Row], limit: int) -> tuple[list[sqlite3.Row], str | None, bool]:
    """Trim a limit + 1 fetch to one page; returns (rows, next_cursor, has_more)."""
    # Check if there are more pages
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # Build cursor for next page from last item
    next_cursor = None
    if has_more and rows:
        last_row = rows[-1]
        next_cursor = build_cursor(last_row["updated_at"], last_row["id"])
    return rows, next_cursor, has_more
