"""Planner database operations mixin.

Contains all methods for Planner conversation management including:
- Get/create planner conversation
- Reset planner (daily 4am auto-reset)
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import Conversation, User
from src.db.models.helpers import delete_messages_blobs, should_reset_planner
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class PlannerMixin:
    """Mixin providing Planner-related database operations."""

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

    def update_planner_last_reset_at(self, user_id: str) -> bool:
        """Update planner last reset timestamp (defined in UserMixin)."""
        raise NotImplementedError

    def get_planner_conversation(self, user_id: str) -> Conversation | None:
        """Get the planner conversation for a user without creating it.

        Args:
            user_id: The user ID

        Returns:
            The planner Conversation or None if it doesn't exist
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            return self._row_to_conversation(row) if row else None

    def get_or_create_planner_conversation(
        self, user_id: str, model: str | None = None
    ) -> Conversation:
        """Get the planner conversation for a user, creating it if it doesn't exist.

        Each user has exactly one planner conversation (is_planning=1).
        The planner conversation is excluded from search and appears at the top
        of the conversation list.

        Args:
            user_id: The user ID
            model: Optional model to use when creating (defaults to Config.DEFAULT_MODEL)

        Returns:
            The planner Conversation
        """
        logger.debug("Getting or creating planner conversation", extra={"user_id": user_id})

        with self._pool.get_connection() as conn:
            # Try to find existing planner conversation
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            if row:
                logger.debug(
                    "Found existing planner conversation",
                    extra={"user_id": user_id, "conversation_id": row["id"]},
                )
                return self._row_to_conversation(row)

            # Create new planner conversation
            conv_id = str(uuid.uuid4())
            model = model or Config.DEFAULT_MODEL
            now = datetime.now()

            self._execute_with_timing(
                conn,
                """INSERT INTO conversations (id, user_id, title, model, is_planning, created_at, updated_at, last_reset)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    conv_id,
                    user_id,
                    "Planner",
                    model,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

            # Initialize planner_last_reset_at so auto-reset can work
            self.update_planner_last_reset_at(user_id)

            logger.info(
                "Planner conversation created",
                extra={"conversation_id": conv_id, "user_id": user_id},
            )
            return Conversation(
                id=conv_id,
                user_id=user_id,
                title="Planner",
                model=model,
                created_at=now,
                updated_at=now,
                is_planning=True,
            )

    def reset_planner_conversation(self, user_id: str) -> Conversation | None:
        """Reset the planner conversation by physically deleting all messages.

        This preserves the conversation itself but removes all messages and their
        associated blobs. Message costs are intentionally preserved for accurate
        cost tracking (following the same pattern as delete_conversation).

        Also updates the user's planner_last_reset_at timestamp.

        Args:
            user_id: The user ID

        Returns:
            The planner Conversation (empty), or None if no planner exists
        """
        logger.info("Resetting planner conversation", extra={"user_id": user_id})

        with self._pool.get_connection() as conn:
            # Get the planner conversation
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            if not row:
                logger.warning("No planner conversation found to reset", extra={"user_id": user_id})
                return None

            conv_id = row["id"]

            # Get message IDs to delete associated blobs
            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()

            # Delete all blobs for these messages
            message_ids = [r["id"] for r in message_rows]
            if message_ids:
                delete_messages_blobs(message_ids)

            # Delete messages (costs are preserved for accuracy)
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )

            # Update planner_last_reset_at on user
            now = datetime.now()
            self._execute_with_timing(
                conn,
                "UPDATE users SET planner_last_reset_at = ? WHERE id = ?",
                (now.isoformat(), user_id),
            )

            # Update conversation updated_at and last_reset
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ?, last_reset = ? WHERE id = ?",
                (now.isoformat(), now.isoformat(), conv_id),
            )

            conn.commit()

            logger.info(
                "Planner conversation reset",
                extra={
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "messages_deleted": len(message_ids),
                },
            )

            return self._row_to_conversation(row)

    def get_planner_conversation_with_auto_reset(
        self, user: User, model: str | None = None
    ) -> tuple[Conversation, bool]:
        """Get the planner conversation, automatically resetting if 4am passed.

        This is the main entry point for accessing the planner. It:
        1. Gets or creates the planner conversation
        2. Checks if auto-reset is needed (4am daily reset)
        3. Performs reset if needed

        Args:
            user: The User object (needed for reset check)
            model: Optional model to use when creating (defaults to Config.DEFAULT_MODEL)

        Returns:
            Tuple of (Conversation, was_reset: bool)
        """
        # Get or create the planner conversation
        conv = self.get_or_create_planner_conversation(user.id, model)

        # Check if auto-reset is needed
        if should_reset_planner(user):
            logger.info(
                "Auto-resetting planner (4am cutoff passed)",
                extra={"user_id": user.id, "conversation_id": conv.id},
            )
            reset_conv = self.reset_planner_conversation(user.id)
            if reset_conv:
                return reset_conv, True
            # Fallback to original if reset failed
            return conv, False

        return conv, False
