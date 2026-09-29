"""Agent dedicated-conversation database operations mixin.

Unread state, the agent's conversation lookup and history compaction.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import Conversation
from src.db.models.helpers import delete_messages_blobs
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
            # LOCAL-naive on purpose: compared against messages.created_at
            # (local-naive) in the unread-count subqueries
            now = datetime.now().isoformat()
            cursor = self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET last_viewed_at = ?
                   WHERE id = ? AND user_id = ?""",
                (now, agent_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_agent_conversation(self, agent_id: str, user_id: str) -> Conversation | None:
        """Get the dedicated conversation for an agent."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT c.* FROM conversations c
                   JOIN autonomous_agents a ON c.id = a.conversation_id
                   WHERE a.id = ? AND a.user_id = ?""",
                (agent_id, user_id),
            ).fetchone()

            if not row:
                return None

            # Import here to avoid circular imports

            # Use the existing _row_to_conversation method pattern
            last_reset = None
            if "last_reset" in row.keys():
                last_reset = (
                    datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None
                )

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                model=row["model"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                is_planning=bool(row["is_planning"]) if row["is_planning"] else False,
                last_reset=last_reset,
                is_agent=bool(row["is_agent"]) if row["is_agent"] else False,
                agent_id=row["agent_id"],
            )

    # ============ Conversation Compaction ============

    def get_agent_message_count(self, agent_id: str) -> int:
        """Get the number of messages in an agent's conversation."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.agent_id = ?""",
                (agent_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def compact_agent_conversation(
        self,
        agent_id: str,
        summary: str,
        keep_recent: int = 10,
    ) -> int:
        """Compact an agent's conversation by replacing old messages with a summary.

        Keeps the most recent `keep_recent` messages and replaces all older messages
        with a single summary message.

        Args:
            agent_id: The agent ID
            summary: Summary text to replace old messages with
            keep_recent: Number of recent messages to keep

        Returns:
            Number of messages deleted.
        """
        with self._pool.get_connection() as conn:
            # Get the conversation ID
            conv_row = self._execute_with_timing(
                conn,
                "SELECT conversation_id FROM autonomous_agents WHERE id = ?",
                (agent_id,),
            ).fetchone()

            if not conv_row or not conv_row["conversation_id"]:
                return 0

            conv_id = conv_row["conversation_id"]

            # Get the IDs of messages to keep (most recent)
            keep_rows = self._execute_with_timing(
                conn,
                """SELECT id, created_at FROM messages
                   WHERE conversation_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (conv_id, keep_recent),
            ).fetchall()

            keep_ids = {row["id"] for row in keep_rows}

            # Get all message IDs to delete
            all_rows = self._execute_with_timing(
                conn,
                "SELECT id FROM messages WHERE conversation_id = ?",
                (conv_id,),
            ).fetchall()

            delete_ids = [row["id"] for row in all_rows if row["id"] not in keep_ids]

            if not delete_ids:
                return 0

            # Delete old messages (blob cleanup happens after the commit)
            placeholders = ",".join("?" * len(delete_ids))
            self._execute_with_timing(
                conn,
                f"DELETE FROM messages WHERE id IN ({placeholders})",
                tuple(delete_ids),
            )

            # Insert the summary message BEFORE the kept messages: history is
            # loaded with ORDER BY created_at, so it must be backdated to just
            # before the oldest kept message or it would land at the END of the
            # context window (after the most recent real messages)
            if keep_rows:
                earliest_kept = min(datetime.fromisoformat(row["created_at"]) for row in keep_rows)
                summary_ts = earliest_kept - timedelta(microseconds=1)
            else:
                # LOCAL-naive: messages.created_at uses the local convention
                summary_ts = datetime.now()
            summary_id = str(uuid.uuid4())
            self._execute_with_timing(
                conn,
                """INSERT INTO messages (id, conversation_id, role, content, created_at)
                   VALUES (?, ?, 'user', ?, ?)""",
                (
                    summary_id,
                    conv_id,
                    f"[Previous conversation summary]\n\n{summary}",
                    summary_ts.isoformat(),
                ),
            )

            conn.commit()

            # Blob cleanup after the commit: a crash here leaves only
            # harmless orphaned blobs, not live rows pointing at deleted data
            delete_messages_blobs(delete_ids)

            logger.info(
                "Agent conversation compacted",
                extra={
                    "agent_id": agent_id,
                    "messages_deleted": len(delete_ids),
                    "messages_kept": len(keep_ids),
                },
            )

            return len(delete_ids)
