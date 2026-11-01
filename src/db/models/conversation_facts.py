"""Conversation facts: the settled facts of one conversation.

The agent records them with record_conversation_facts (applied when its reply
is saved); every turn of the conversation gets them verbatim, outside
compaction. A fact belongs to the reply that last set it - the
conversation_facts_message_delete trigger drops it with that reply
(docs/features/conversation-facts.md).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.config import Config
from src.db.models.dataclasses import ConversationFact
from src.db.models.timestamps import from_db, to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

_KEY_MAX_CHARS = 40
_NOT_KEY = re.compile(r"[^a-z0-9-]+")


def normalize_fact_key(key: str) -> str:
    """'Partition Walls ' -> 'partition-walls' (lowercase slug, max 40 chars)."""
    slug = _NOT_KEY.sub("-", key.strip().lower()).strip("-")
    return slug[:_KEY_MAX_CHARS]


def _clip_fact(text: str) -> str:
    """One line, clipped at a word to the length cap: a dropped fact would
    leave the agent believing it was recorded (the tool returns nothing)."""
    text = " ".join(text.split())
    cap = Config.CONVERSATION_FACTS_MAX_FACT_CHARS
    if len(text) <= cap:
        return text
    return text[: cap - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


@dataclass
class FactsApplyResult:
    """How many edits of one call were applied and how many hit the caps."""

    applied: int
    rejected: int


class ConversationFactsMixin:
    """Mixin providing conversation facts operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_conversation_facts(self, conv_id: str) -> list[ConversationFact]:
        """The conversation's facts, oldest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT fact_key, text, message_id, updated_at FROM conversation_facts
                   WHERE conversation_id = ? ORDER BY updated_at, fact_key""",
                (conv_id,),
            ).fetchall()
        return [
            ConversationFact(
                key=row["fact_key"],
                text=row["text"],
                message_id=row["message_id"],
                updated_at=from_db(row["updated_at"], "utc"),
            )
            for row in rows
        ]

    def apply_conversation_facts(
        self,
        conv_id: str,
        user_id: str,
        message_id: str,
        set_facts: list[tuple[str, str]],
        remove_keys: list[str],
    ) -> FactsApplyResult:
        """Apply one reply's edits: removals first, then sets (a set replaces
        the key's fact and moves it to this reply). Past the caps an edit is
        dropped and counted as rejected."""
        applied = rejected = 0
        with self._pool.get_connection() as conn:
            now = to_db(utc_now(), "utc", conn)
            for key in {normalize_fact_key(k) for k in remove_keys}:
                cursor = self._execute_with_timing(
                    conn,
                    "DELETE FROM conversation_facts WHERE conversation_id = ? AND fact_key = ?",
                    (conv_id, key),
                )
                applied += cursor.rowcount
            for raw_key, raw_text in set_facts:
                key, text = normalize_fact_key(raw_key), _clip_fact(raw_text)
                if not key or not text:
                    rejected += 1
                    continue
                if not self._fact_fits(conn, conv_id, key):
                    rejected += 1
                    continue
                self._execute_with_timing(
                    conn,
                    """INSERT INTO conversation_facts
                       (conversation_id, user_id, fact_key, text, message_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(conversation_id, fact_key) DO UPDATE SET
                           text = excluded.text, message_id = excluded.message_id,
                           updated_at = excluded.updated_at""",
                    (conv_id, user_id, key, text, message_id, now, now),
                )
                applied += 1
            conn.commit()
        if rejected:
            logger.info(
                "Conversation facts rejected at the caps",
                extra={"conversation_id": conv_id, "rejected": rejected},
            )
        return FactsApplyResult(applied=applied, rejected=rejected)

    def _fact_fits(self, conn: sqlite3.Connection, conv_id: str, key: str) -> bool:
        """A replacement always fits; a new key only below the count cap."""
        row = self._execute_with_timing(
            conn,
            """SELECT count(*) AS n, sum(fact_key = ?) AS existing
               FROM conversation_facts WHERE conversation_id = ?""",
            (key, conv_id),
        ).fetchone()
        return bool(row["existing"]) or row["n"] < Config.CONVERSATION_FACTS_MAX_COUNT
