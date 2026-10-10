"""Conversation listing database operations mixin (sidebar pages, sync)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import (
    page_rows,
    row_to_conversation,
    row_to_conversation_summary,
)
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import parse_cursor

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


class ConversationListingMixin:
    """Mixin providing paginated conversation listings and sync queries."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def list_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[Conversation], str | None, bool, int]:
        """List conversations for a user with cursor-based pagination.

        Returns conversations ordered by updated_at DESC (most recent first).
        Uses cursor-based pagination with (updated_at, id) as the cursor key.
        Excludes planning conversations (they are fetched separately).

        Args:
            user_id: The user ID
            limit: Maximum number of conversations to return
            cursor: Optional cursor from previous page (format: '{updated_at}:{id}')

        Returns:
            Tuple of:
            - List of Conversation objects
            - Next cursor (None if no more pages)
            - has_more: True if there are more pages
            - total_count: Total number of conversations for this user (excluding planner)
        """
        with self._pool.get_connection() as conn:
            # Get total count for this user (excluding planning, agent, and archived conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ?
                     AND (is_planning = 0 OR is_planning IS NULL)
                     AND (is_agent = 0 OR is_agent IS NULL)
                     AND (archived = 0 OR archived IS NULL)
                     AND deleted_at IS NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query based on cursor (excluding planning, agent, and archived conversations)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                # Use tuple comparison for stable pagination:
                # (updated_at, id) < (cursor_updated_at, cursor_id)
                # This handles tie-breaking when multiple conversations have the same updated_at
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations
                       WHERE user_id = ?
                         AND (is_planning = 0 OR is_planning IS NULL)
                         AND (is_agent = 0 OR is_agent IS NULL)
                         AND (archived = 0 OR archived IS NULL)
                         AND deleted_at IS NULL
                         AND (updated_at < ? OR (updated_at = ? AND id < ?))
                       ORDER BY updated_at DESC, id DESC
                       LIMIT ?""",
                    (user_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations
                       WHERE user_id = ?
                         AND (is_planning = 0 OR is_planning IS NULL)
                         AND (is_agent = 0 OR is_agent IS NULL)
                         AND (archived = 0 OR archived IS NULL)
                         AND deleted_at IS NULL
                       ORDER BY updated_at DESC, id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            rows, next_cursor, has_more = page_rows(rows, limit)

            conversations = [row_to_conversation(row) for row in rows]

            return conversations, next_cursor, has_more, total_count

    def list_conversations_paginated_with_counts(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]:
        """List conversations for a user with cursor-based pagination and message counts.

        Combines pagination with message counting in a single query for efficiency.
        Returns conversations ordered by updated_at DESC (most recent first).
        Excludes planning conversations (they are fetched separately).

        Args:
            user_id: The user ID
            limit: Maximum number of conversations to return
            cursor: Optional cursor from previous page (format: '{updated_at}:{id}')

        Returns:
            Tuple of:
            - List of (Conversation, message_count) tuples
            - Next cursor (None if no more pages)
            - has_more: True if there are more pages
            - total_count: Total number of conversations for this user (excluding planner)
        """
        with self._pool.get_connection() as conn:
            # Get total count for this user (excluding planning, agent, and archived conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ?
                     AND (is_planning = 0 OR is_planning IS NULL)
                     AND (is_agent = 0 OR is_agent IS NULL)
                     AND (archived = 0 OR archived IS NULL)
                     AND deleted_at IS NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query with JOIN for message counts (excluding planning, agent, and archived)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                         AND (c.is_agent = 0 OR c.is_agent IS NULL)
                         AND (c.archived = 0 OR c.archived IS NULL)
                         AND c.deleted_at IS NULL
                         AND (c.is_sports = 0 OR c.is_sports IS NULL)
                         AND (c.is_language = 0 OR c.is_language IS NULL)
                         AND (c.pinned = 0 OR c.pinned IS NULL)
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
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                         AND (c.is_agent = 0 OR c.is_agent IS NULL)
                         AND (c.archived = 0 OR c.archived IS NULL)
                         AND c.deleted_at IS NULL
                         AND (c.is_sports = 0 OR c.is_sports IS NULL)
                         AND (c.is_language = 0 OR c.is_language IS NULL)
                         AND (c.pinned = 0 OR c.pinned IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            rows, next_cursor, has_more = page_rows(rows, limit)

            conversations_with_counts = [row_to_conversation_summary(row) for row in rows]

            return conversations_with_counts, next_cursor, has_more, total_count

    def list_conversations_with_message_count(
        self, user_id: str, include_planning: bool = False
    ) -> list[tuple[Conversation, int, str | None]]:
        """List all conversations for a user with message counts.

        This method is used for sync operations to detect unread messages.
        Returns conversations with their message counts for comparison.
        Excludes planning conversations by default (they are fetched separately).

        Args:
            user_id: The user ID
            include_planning: If True, includes planning conversations.
                             Default False since planner is handled separately.

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                         AND (c.is_agent = 0 OR c.is_agent IS NULL)
                         AND (c.archived = 0 OR c.archived IS NULL)
                         AND c.deleted_at IS NULL
                         AND (c.is_sports = 0 OR c.is_sports IS NULL)
                         AND (c.is_language = 0 OR c.is_language IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [row_to_conversation_summary(row) for row in rows]

    def get_conversations_updated_since(
        self, user_id: str, since: datetime, include_planning: bool = False
    ) -> list[tuple[Conversation, int, str | None]]:
        """Get conversations updated since a given timestamp with message counts.

        This method is used for incremental sync operations to fetch only
        conversations that have changed since the last sync.
        Excludes planning conversations by default (they are handled separately).

        Args:
            user_id: The user ID
            since: The timestamp to check against (conversations updated after this)
            include_planning: If True, includes planning conversations.
                             Default False since planner is handled separately.

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.updated_at > ?
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id, since.isoformat()),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, c.read_message_count, COUNT(m.id) as message_count,
                              (SELECT m2.content FROM messages m2
                               WHERE m2.conversation_id = c.id
                               ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.updated_at > ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                         AND (c.is_agent = 0 OR c.is_agent IS NULL)
                         AND (c.archived = 0 OR c.archived IS NULL)
                         AND c.deleted_at IS NULL
                         AND (c.is_sports = 0 OR c.is_sports IS NULL)
                         AND (c.is_language = 0 OR c.is_language IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id, since.isoformat()),
                ).fetchall()

            return [row_to_conversation_summary(row) for row in rows]
