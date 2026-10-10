"""Conversation archive and pin database operations mixin."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import page_rows, row_to_conversation_summary
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import parse_cursor

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


class ConversationArchiveMixin:
    """Mixin providing conversation archive/unarchive and pin operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def archive_conversation(self, conv_id: str, user_id: str) -> bool:
        """Archive a conversation (hide from main list)."""
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE conversations SET archived = 1, updated_at = ? WHERE id = ? AND user_id = ?"
                " AND deleted_at IS NULL",
                (now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_conversation_pinned(self, conv_id: str, user_id: str, pinned: bool) -> bool:
        """Pin/unpin a conversation (pinned rows show atop the sidebar).

        Deliberately does NOT touch updated_at - pinning is organization,
        not activity.
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE conversations SET pinned = ? WHERE id = ? AND user_id = ?"
                " AND deleted_at IS NULL",
                (1 if pinned else 0, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_pinned_conversations(self, user_id: str) -> list[tuple[Conversation, int, str | None]]:
        """Pinned, non-archived conversations with counts and previews,
        most recently updated first. Small by nature - not paginated."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT c.*, COUNT(m.id) as message_count,
                          (SELECT m2.content FROM messages m2
                           WHERE m2.conversation_id = c.id
                           ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.pinned = 1
                     AND (c.archived = 0 OR c.archived IS NULL)
                     AND c.deleted_at IS NULL
                     AND (c.is_agent = 0 OR c.is_agent IS NULL)
                     AND (c.is_planning = 0 OR c.is_planning IS NULL)
                   GROUP BY c.id
                   ORDER BY c.updated_at DESC, c.id DESC""",
                (user_id,),
            ).fetchall()
            return [row_to_conversation_summary(row) for row in rows]

    def unarchive_conversation(self, conv_id: str, user_id: str) -> bool:
        """Unarchive a conversation (restore to main list)."""
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE conversations SET archived = 0, updated_at = ? WHERE id = ? AND user_id = ?"
                " AND deleted_at IS NULL",
                (now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_archived_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]:
        """List archived conversations with message counts and pagination.

        Same structure as list_conversations_paginated_with_counts but filtering archived = 1.
        """
        with self._pool.get_connection() as conn:
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND archived = 1 AND deleted_at IS NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, c.pinned, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.archived = 1 AND c.deleted_at IS NULL
                         AND (c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, c.pinned, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.archived = 1 AND c.deleted_at IS NULL
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            rows, next_cursor, has_more = page_rows(rows, limit)

            conversations_with_counts = [row_to_conversation_summary(row) for row in rows]

            return conversations_with_counts, next_cursor, has_more, total_count
