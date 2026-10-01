"""Conversation trash database operations mixin.

Deleting a chat from the UI moves it to the trash (deleted_at set) instead
of destroying it. It stays restorable until the daily cleanup sweep purges
it after TRASH_RETENTION_DAYS. The real deletion (rows, then blobs) is
ConversationMixin.delete_conversation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import page_rows, row_to_conversation_summary
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import parse_cursor
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

_TRASH_LIST_SELECT = """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                          c.is_planning, c.archived, c.pinned, c.deleted_at,
                          COUNT(m.id) as message_count,
                          (SELECT m2.content FROM messages m2
                           WHERE m2.conversation_id = c.id
                           ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.deleted_at IS NOT NULL"""


class ConversationTrashMixin:
    """Mixin providing conversation trash, restore and purge operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Hard delete (defined in ConversationMixin)."""
        raise NotImplementedError

    def trash_conversation(self, conv_id: str, user_id: str) -> bool:
        """Move a conversation to the trash.

        Idempotent: trashing an already-trashed conversation succeeds and
        keeps the original deleted_at, so a retried DELETE neither 404s nor
        extends the retention window. updated_at is bumped so incremental
        sync on other devices sees the change.
        """
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE conversations
                   SET deleted_at = COALESCE(deleted_at, ?), updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (now, now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def restore_conversation(self, conv_id: str, user_id: str) -> bool:
        """Take a conversation out of the trash, back where it was.

        archived/pinned are untouched, so an archived chat returns to the
        archive. Idempotent for live conversations (True, no change).
        """
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE conversations
                   SET updated_at = CASE WHEN deleted_at IS NULL THEN updated_at ELSE ? END,
                       deleted_at = NULL
                   WHERE id = ? AND user_id = ?""",
                (now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_trashed_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]:
        """Trashed conversations, most recently trashed first.

        Same shape as list_archived_conversations_paginated. Trashing bumps
        updated_at, so the shared (updated_at, id) cursor orders by trash time.
        """
        with self._pool.get_connection() as conn:
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND deleted_at IS NOT NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            query = _TRASH_LIST_SELECT
            params: tuple[Any, ...] = (user_id,)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                query += " AND (c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))"
                params += (cursor_timestamp, cursor_timestamp, cursor_id)
            rows = self._execute_with_timing(
                conn,
                query + " GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()

        rows, next_cursor, has_more = page_rows(rows, limit)
        summaries = [row_to_conversation_summary(row) for row in rows]
        return summaries, next_cursor, has_more, total_count

    def delete_trashed_conversation(self, conv_id: str, user_id: str) -> bool:
        """Permanently delete one conversation, only if it is in the trash."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM conversations
                   WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL""",
                (conv_id, user_id),
            ).fetchone()
        if not row:
            return False
        return self.delete_conversation(conv_id, user_id)

    def empty_trash(self, user_id: str) -> int:
        """Permanently delete all of a user's trashed conversations."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT id FROM conversations WHERE user_id = ? AND deleted_at IS NOT NULL",
                (user_id,),
            ).fetchall()
        return sum(1 for row in rows if self.delete_conversation(row["id"], user_id))

    def purge_trashed_conversations(self, retention_days: int) -> int:
        """Permanently delete conversations trashed over retention_days ago (all users)."""
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT id, user_id FROM conversations
                   WHERE deleted_at IS NOT NULL AND deleted_at < ?""",
                (cutoff,),
            ).fetchall()
        purged = sum(1 for row in rows if self.delete_conversation(row["id"], row["user_id"]))
        if purged:
            logger.info("Purged trashed conversations", extra={"purged": purged})
        return purged
