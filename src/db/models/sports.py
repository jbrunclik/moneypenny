"""Sports tracking database operations mixin.

Contains all methods for sports program conversation management including:
- Get/create sports conversation per program
- Reset sports conversation (clear messages + checkpoint)
- List sports conversations
- Delete sports conversation
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import delete_messages_blobs
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class SportsTrackingMixin:
    """Mixin providing sports tracking database operations."""

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
        """Convert row to Conversation (defined in ConversationMixin)."""
        raise NotImplementedError

    def get_sports_conversation(self, user_id: str, program: str) -> Conversation | None:
        """Get the sports conversation for a user and program.

        Args:
            user_id: The user ID
            program: The program ID (e.g., "pushups")

        Returns:
            The sports Conversation or None if it doesn't exist
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_sports = 1 AND sports_program = ?",
                (user_id, program),
            ).fetchone()

            return self._row_to_conversation(row) if row else None

    def get_or_create_sports_conversation(
        self, user_id: str, program: str, model: str | None = None
    ) -> Conversation:
        """Get or create a sports conversation for a user and program.

        Each user has one conversation per sports program.

        Args:
            user_id: The user ID
            program: The program ID (e.g., "pushups")
            model: Optional model to use when creating

        Returns:
            The sports Conversation
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_sports = 1 AND sports_program = ?",
                (user_id, program),
            ).fetchone()

            if row:
                return self._row_to_conversation(row)

            conv_id = str(uuid.uuid4())
            model = model or Config.DEFAULT_MODEL
            now = datetime.now()

            self._execute_with_timing(
                conn,
                """INSERT INTO conversations
                   (id, user_id, title, model, is_sports, sports_program, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    conv_id,
                    user_id,
                    f"Sports: {program}",
                    model,
                    program,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

            logger.info(
                "Sports conversation created",
                extra={
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                },
            )
            return Conversation(
                id=conv_id,
                user_id=user_id,
                title=f"Sports: {program}",
                model=model,
                created_at=now,
                updated_at=now,
                is_sports=True,
                sports_program=program,
            )

    def reset_sports_conversation(self, user_id: str, program: str) -> Conversation | None:
        """Reset a sports conversation by deleting all messages.

        Preserves the conversation itself and cost data.

        Args:
            user_id: The user ID
            program: The program ID

        Returns:
            The sports Conversation (empty), or None if not found
        """
        logger.info(
            "Resetting sports conversation",
            extra={"user_id": user_id, "program": program},
        )

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_sports = 1 AND sports_program = ?",
                (user_id, program),
            ).fetchone()

            if not row:
                return None

            conv_id = row["id"]

            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()

            message_ids = [r["id"] for r in message_rows]
            if message_ids:
                delete_messages_blobs(message_ids)

            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )

            now = datetime.now()
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now.isoformat(), conv_id),
            )

            conn.commit()

            # Clear LangGraph checkpoint
            self._clear_sports_checkpoint(conv_id)

            logger.info(
                "Sports conversation reset",
                extra={
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                    "messages_deleted": len(message_ids),
                },
            )

            # Re-fetch to get updated timestamp
            updated_row = self._execute_with_timing(
                conn, "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            return self._row_to_conversation(updated_row) if updated_row else None

    @staticmethod
    def _clear_sports_checkpoint(conversation_id: str) -> None:
        """Clear LangGraph checkpoint state for a sports conversation."""
        if not Config.AGENT_CHECKPOINTING_ENABLED:
            return
        try:
            from src.agent.graph import _get_checkpointer

            checkpointer = _get_checkpointer()
            checkpointer.delete_thread(conversation_id)
        except Exception as e:
            logger.warning(
                "Failed to clear sports checkpoint",
                extra={"conversation_id": conversation_id, "error": str(e)},
            )

    def list_sports_conversations(self, user_id: str) -> list[Conversation]:
        """List all sports conversations for a user.

        Args:
            user_id: The user ID

        Returns:
            List of sports Conversation objects
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_sports = 1 ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()

            return [self._row_to_conversation(row) for row in rows]

    def delete_sports_conversation(self, user_id: str, program: str) -> bool:
        """Delete a sports conversation and all its messages.

        Args:
            user_id: The user ID
            program: The program ID

        Returns:
            True if deleted, False if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT id FROM conversations WHERE user_id = ? AND is_sports = 1 AND sports_program = ?",
                (user_id, program),
            ).fetchone()

            if not row:
                return False

            conv_id = row["id"]

            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()
            message_ids = [r["id"] for r in message_rows]
            if message_ids:
                delete_messages_blobs(message_ids)

            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            self._execute_with_timing(
                conn,
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            )
            conn.commit()

            # Clear checkpoint
            self._clear_sports_checkpoint(conv_id)

            logger.info(
                "Sports conversation deleted",
                extra={
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                },
            )
            return True
