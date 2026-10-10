"""Cross-device sync change log reads (written by migration 0061's triggers)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import build_message_preview, row_to_conversation
from src.db.models.dataclasses import Conversation

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


@dataclass
class ConversationChange:
    """A conversation's latest change after a sync cursor.

    `conversation` is None when it was permanently deleted (the change row
    outlives it).
    """

    conversation_id: str
    seq: int
    conversation: Conversation | None
    message_count: int
    last_message_preview: str | None
    last_message_id: str | None


class SyncChangesMixin:
    """Mixin providing the sync cursor and the changes after it."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_sync_cursor(self) -> int:
        """The latest change seq (global; a client starts from it after a full sync)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT value FROM sync_counter WHERE id = 1"
            ).fetchone()
            return int(row[0]) if row else 0

    def get_conversation_changes(
        self, user_id: str, after_seq: int, limit: int
    ) -> list[ConversationChange]:
        """The user's conversations changed after `after_seq`, oldest change first.

        Returns at most `limit` rows; the caller pages on by the last seq.
        Every conversation kind is included - the caller filters.
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT ch.conversation_id AS change_id, ch.seq,
                          c.*,
                          (SELECT COUNT(*) FROM messages m
                           WHERE m.conversation_id = ch.conversation_id) AS message_count,
                          (SELECT m2.content FROM messages m2
                           WHERE m2.conversation_id = ch.conversation_id
                           ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) AS last_message,
                          (SELECT m3.id FROM messages m3
                           WHERE m3.conversation_id = ch.conversation_id
                           ORDER BY m3.created_at DESC, m3.id DESC LIMIT 1) AS last_message_id
                   FROM conversation_changes ch
                   LEFT JOIN conversations c ON c.id = ch.conversation_id
                   WHERE ch.user_id = ? AND ch.seq > ?
                   ORDER BY ch.seq
                   LIMIT ?""",
                (user_id, after_seq, limit),
            ).fetchall()

        return [
            ConversationChange(
                conversation_id=row["change_id"],
                seq=int(row["seq"]),
                conversation=row_to_conversation(row) if row["id"] is not None else None,
                message_count=int(row["message_count"]),
                last_message_preview=build_message_preview(row["last_message"]),
                last_message_id=row["last_message_id"],
            )
            for row in rows
        ]
