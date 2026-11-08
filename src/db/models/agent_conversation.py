"""Agent dedicated-conversation database operations mixin.

Unread state, the agent's conversation lookup and history compaction.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentConversationMixin:
    """Mixin providing operations on an agent's dedicated conversation."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_agent_unread_count(self, agent_id: str) -> int:
        """Get the number of unread messages for an agent.

        Unread messages are assistant messages created after last_viewed_at.
        Only counts assistant messages (excludes trigger messages which are user role).
        If last_viewed_at is NULL, all assistant messages are considered unread.
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   JOIN autonomous_agents a ON c.agent_id = a.id
                   WHERE a.id = ?
                   AND m.role = 'assistant'
                   AND (a.last_viewed_at IS NULL OR m.created_at > a.last_viewed_at)""",
                (agent_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def update_agent_last_viewed(self, agent_id: str, user_id: str) -> bool:
        """Update the last_viewed_at timestamp for an agent.

        Called when user opens the agent's conversation to mark messages as read.

        Returns:
            True if updated, False if agent not found
        """
        with self._pool.get_connection() as conn:
            # messages.created_at's format: the unread-count subqueries
            # compare the two as strings
            now = to_db(utc_now())
            cursor = self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET last_viewed_at = ?
                   WHERE id = ? AND user_id = ?""",
                (now, agent_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ============ Conversation Compaction ============
