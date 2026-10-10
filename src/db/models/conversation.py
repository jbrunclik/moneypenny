"""Conversation database operations mixin.

Conversation CRUD and counts. Paginated listings and sync queries live in
conversation_listing.py, archive/pin in conversation_archive.py, trash in
conversation_trash.py.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.conversation_rows import row_to_conversation
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import delete_messages_blobs
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
        return row_to_conversation(row)

    def create_conversation(
        self,
        user_id: str,
        title: str = Config.DEFAULT_CONVERSATION_TITLE,
        model: str | None = None,
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
                "SELECT * FROM conversations WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
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
                       AND deleted_at IS NULL
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations WHERE user_id = ?
                       AND (is_planning = 0 OR is_planning IS NULL)
                       AND (is_agent = 0 OR is_agent IS NULL)
                       AND (archived = 0 OR archived IS NULL)
                       AND deleted_at IS NULL
                       AND (is_sports = 0 OR is_sports IS NULL)
                       AND (is_language = 0 OR is_language IS NULL)
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [self._row_to_conversation(row) for row in rows]

    def set_conversation_anonymous_mode(
        self, conv_id: str, user_id: str, anonymous_mode: bool
    ) -> bool:
        """Persist the anonymous-mode flag for a conversation.

        Deliberately does not touch updated_at: toggling privacy is not activity
        and should not reorder the conversation list.

        Args:
            conv_id: The conversation ID
            user_id: The user ID (for ownership verification)
            anonymous_mode: Whether the conversation is anonymous

        Returns:
            True if the conversation was updated, False if not found
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE conversations SET anonymous_mode = ? WHERE id = ? AND user_id = ?",
                (int(anonymous_mode), conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

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
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
                " AND deleted_at IS NULL",
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Delete a conversation and all its messages."""
        with self._pool.get_connection() as conn:
            # Note: We intentionally keep message_costs even after conversation deletion
            # to preserve accurate cost reporting (the money was already spent)

            # Verify ownership BEFORE touching messages (routes also check, but
            # this method must not delete another user's messages on its own)
            owned = self._execute_with_timing(
                conn,
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()
            if not owned:
                return False

            # Get message IDs for blob cleanup after the commit
            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()
            message_ids = [row["id"] for row in message_rows]

            # Delete rows FIRST and commit: a crash before blob cleanup then
            # leaves only harmless orphaned blobs, not live rows pointing at
            # deleted file data
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            )
            conn.commit()

            delete_messages_blobs(message_ids)
            return cursor.rowcount > 0

    def mark_conversation_read(self, conv_id: str, user_id: str, message_count: int) -> bool:
        """Record that a device has shown the conversation up to message_count.

        Clamped to the real count. Only an actual change writes (each write
        is a change-log entry other devices fetch); updated_at is untouched,
        so reading never reorders the sidebar. Returns whether the
        conversation exists for the user.
        """
        with self._pool.get_connection() as conn:
            owned = self._execute_with_timing(
                conn,
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()
            if not owned:
                return False
            self._execute_with_timing(
                conn,
                # Only ever forward (MAX): a device that switched away during
                # its own turn reports count - 1 after the device with the chat
                # open reported count - that reply was read. Deletes clamp it
                # down (trigger, migration 0063).
                """UPDATE conversations
                   SET read_message_count = MIN(
                       ?, (SELECT COUNT(*) FROM messages WHERE conversation_id = ?))
                   WHERE id = ? AND read_message_count < MIN(
                       ?, (SELECT COUNT(*) FROM messages WHERE conversation_id = ?))""",
                (message_count, conv_id, conv_id, message_count, conv_id),
            )
            conn.commit()
            return True

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

    def get_conversation_with_message_count(
        self, conversation_id: str
    ) -> tuple[Conversation, int] | None:
        """Get a conversation with its message count.

        Used for sync operations on specific conversations (e.g., agent conversations).

        Args:
            conversation_id: The conversation ID

        Returns:
            Tuple of (Conversation, message_count) or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                          c.is_planning, COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.id = ? AND c.deleted_at IS NULL
                   GROUP BY c.id""",
                (conversation_id,),
            ).fetchone()

            if not row:
                return None

            return (self._row_to_conversation(row), int(row["message_count"]))
