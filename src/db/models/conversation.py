"""Conversation database operations mixin.

Contains all methods for Conversation entity management including:
- CRUD operations
- Pagination (cursor-based)
- Sync support (updated_since queries)
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import (
    build_cursor,
    delete_messages_blobs,
    parse_cursor,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class ConversationMixin:
    """Mixin providing Conversation-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        """Convert a database row to a Conversation object."""
        # Check if last_reset column exists (added in migration 0021)
        last_reset = None
        if "last_reset" in row.keys():
            last_reset = datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None

        return Conversation(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            model=row["model"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            is_planning=bool(row["is_planning"]) if row["is_planning"] else False,
            last_reset=last_reset,
        )

    def create_conversation(
        self, user_id: str, title: str = "New Conversation", model: str | None = None
    ) -> Conversation:
        """Create a new conversation for a user."""
        conv_id = str(uuid.uuid4())
        model = model or Config.DEFAULT_MODEL
        now = datetime.now()
        logger.debug(
            "Creating conversation",
            extra={"user_id": user_id, "conversation_id": conv_id, "model": model},
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conv_id, user_id, title, model, now.isoformat(), now.isoformat()),
            )
            conn.commit()

        logger.info("Conversation created", extra={"conversation_id": conv_id, "user_id": user_id})
        return Conversation(
            id=conv_id,
            user_id=user_id,
            title=title,
            model=model,
            created_at=now,
            updated_at=now,
        )

    def get_conversation(self, conv_id: str, user_id: str) -> Conversation | None:
        """Get a conversation by ID and user ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()

            if not row:
                return None

            return self._row_to_conversation(row)

    def list_conversations(
        self, user_id: str, include_planning: bool = False
    ) -> list[Conversation]:
        """List conversations for a user.

        Args:
            user_id: The user ID
            include_planning: If True, includes planning conversations.
                             Default False since planner is fetched separately.

        Returns:
            List of Conversation objects ordered by updated_at DESC
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations WHERE user_id = ?
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations WHERE user_id = ?
                       AND (is_planning = 0 OR is_planning IS NULL)
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [self._row_to_conversation(row) for row in rows]

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
            # Get total count for this user (excluding planning conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND (is_planning = 0 OR is_planning IS NULL)""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query based on cursor (excluding planning conversations)
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
                       ORDER BY updated_at DESC, id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            # Check if there are more pages
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            # Build cursor for next page from last item
            next_cursor = None
            if has_more and rows:
                last_row = rows[-1]
                next_cursor = build_cursor(last_row["updated_at"], last_row["id"])

            conversations = [self._row_to_conversation(row) for row in rows]

            return conversations, next_cursor, has_more, total_count

    def list_conversations_paginated_with_counts(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int]], str | None, bool, int]:
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
            # Get total count for this user (excluding planning conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND (is_planning = 0 OR is_planning IS NULL)""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query with JOIN for message counts (excluding planning conversations)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
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
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            # Check if there are more pages
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            # Build cursor for next page from last item
            next_cursor = None
            if has_more and rows:
                last_row = rows[-1]
                next_cursor = build_cursor(last_row["updated_at"], last_row["id"])

            conversations_with_counts = [
                (self._row_to_conversation(row), int(row["message_count"])) for row in rows
            ]

            return conversations_with_counts, next_cursor, has_more, total_count

    def list_conversations_with_message_count(
        self, user_id: str, include_planning: bool = False
    ) -> list[tuple[Conversation, int]]:
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
                              c.is_planning, COUNT(m.id) as message_count
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
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [(self._row_to_conversation(row), int(row["message_count"])) for row in rows]

    def get_conversations_updated_since(
        self, user_id: str, since: datetime, include_planning: bool = False
    ) -> list[tuple[Conversation, int]]:
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
                              c.is_planning, COUNT(m.id) as message_count
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
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.updated_at > ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id, since.isoformat()),
                ).fetchall()

            return [(self._row_to_conversation(row), int(row["message_count"])) for row in rows]

    # Whitelist of allowed columns for update_conversation to prevent SQL injection
    _CONVERSATION_UPDATE_COLUMNS = frozenset({"title", "model"})

    def update_conversation(
        self, conv_id: str, user_id: str, title: str | None = None, model: str | None = None
    ) -> bool:
        """Update a conversation's title or model."""
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [datetime.now().isoformat()]

        # Map parameter names to their values (only include non-None values)
        column_values = {"title": title, "model": model}

        for column, value in column_values.items():
            if value is not None:
                if column not in self._CONVERSATION_UPDATE_COLUMNS:
                    raise ValueError(f"Invalid column for update: {column}")
                updates.append(f"{column} = ?")
                params.append(value)

        params.extend([conv_id, user_id])

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Delete a conversation and all its messages."""
        with self._pool.get_connection() as conn:
            # Note: We intentionally keep message_costs even after conversation deletion
            # to preserve accurate cost reporting (the money was already spent)

            # Get message IDs to delete associated blobs
            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()

            # Delete all blobs for these messages in a single query
            message_ids = [row["id"] for row in message_rows]
            delete_messages_blobs(message_ids)

            # Delete messages
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            # Delete conversation
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def count_messages(self, conversation_id: str) -> int:
        """Count messages in a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of messages in the conversation
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            return row[0] if row else 0
