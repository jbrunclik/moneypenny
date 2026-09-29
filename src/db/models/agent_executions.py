"""Agent execution tracking database operations mixin."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.agent_rows import row_to_execution
from src.db.models.dataclasses import AgentExecution
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentExecutionMixin:
    """Mixin providing agent execution tracking operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_last_execution_status(self, agent_id: str) -> str | None:
        """Get the status of the most recent execution for an agent.

        Returns:
            Status string ('completed', 'failed', etc.) or None if no executions
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT status FROM agent_executions
                   WHERE agent_id = ?
                   ORDER BY started_at DESC
                   LIMIT 1""",
                (agent_id,),
            ).fetchone()
            return row["status"] if row else None

    def create_execution(
        self,
        agent_id: str,
        trigger_type: str,
        triggered_by_agent_id: str | None = None,
    ) -> AgentExecution:
        """Create a new execution record."""
        execution_id = str(uuid.uuid4())
        now = utcnow_naive()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO agent_executions
                   (id, agent_id, status, trigger_type, triggered_by_agent_id, started_at)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (execution_id, agent_id, trigger_type, triggered_by_agent_id, now.isoformat()),
            )
            conn.commit()

        return AgentExecution(
            id=execution_id,
            agent_id=agent_id,
            status="running",
            trigger_type=trigger_type,
            triggered_by_agent_id=triggered_by_agent_id,
            started_at=now,
            completed_at=None,
            error_message=None,
        )

    def update_execution(
        self,
        execution_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update an execution's status."""
        now = utcnow_naive()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = ?, completed_at = ?, error_message = ?
                   WHERE id = ?""",
                (status, now.isoformat(), error_message, execution_id),
            )
            conn.commit()

    def get_agent_executions(self, agent_id: str, limit: int = 20) -> list[AgentExecution]:
        """Get recent executions for an agent."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_executions
                   WHERE agent_id = ?
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (agent_id, limit),
            ).fetchall()

            return [row_to_execution(row) for row in rows]

    def has_running_execution(self, agent_id: str) -> bool:
        """Check if an agent has a currently running execution.

        Used to prevent overlapping executions of the same agent.
        Ignores executions older than AGENT_EXECUTION_TIMEOUT_MINUTES to prevent
        permanently locked agents due to stuck executions.
        """
        # Calculate the cutoff time (executions older than this are considered stuck)
        cutoff = utcnow_naive() - timedelta(minutes=Config.AGENT_EXECUTION_TIMEOUT_MINUTES)

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_executions
                   WHERE agent_id = ? AND status = 'running'
                   AND started_at > ?
                   LIMIT 1""",
                (agent_id, cutoff.isoformat()),
            ).fetchone()

            return row is not None

    def is_in_cooldown(self, agent_id: str) -> bool:
        """Check if an agent is within its execution cooldown period.

        Used to prevent spamming manual runs. Returns True if the agent
        completed an execution within AGENT_EXECUTION_COOLDOWN_SECONDS.
        """
        # Calculate the cooldown cutoff time
        now = utcnow_naive()
        cutoff = now - timedelta(seconds=Config.AGENT_EXECUTION_COOLDOWN_SECONDS)

        with self._pool.get_connection() as conn:
            # completed_at <= now clamps bogus future timestamps (e.g. rows
            # written under the pre-UTC local-naive convention on a UTC+N
            # host) so they can't pin the agent in cooldown
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_executions
                   WHERE agent_id = ? AND completed_at IS NOT NULL
                   AND completed_at > ? AND completed_at <= ?
                   LIMIT 1""",
                (agent_id, cutoff.isoformat(), now.isoformat()),
            ).fetchone()

            return row is not None

    def get_recent_executions(self, user_id: str, limit: int = 20) -> list[AgentExecution]:
        """Get recent executions across all agents for a user."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT e.* FROM agent_executions e
                   JOIN autonomous_agents a ON e.agent_id = a.id
                   WHERE a.user_id = ?
                   ORDER BY e.started_at DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()

            return [row_to_execution(row) for row in rows]

    def cleanup_zombie_executions(self) -> int:
        """Clean up executions stuck in 'running' or 'waiting_approval' status.

        Marks executions as 'failed' if they've been stuck for longer than
        AGENT_EXECUTION_TIMEOUT_MINUTES. This prevents permanently locked agents
        due to crashed executions.

        Returns:
            Number of zombie executions cleaned up.
        """
        cutoff = utcnow_naive() - timedelta(minutes=Config.AGENT_EXECUTION_TIMEOUT_MINUTES)

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = 'failed',
                       completed_at = ?,
                       error_message = 'Execution timed out (zombie cleanup)'
                   WHERE status IN ('running', 'waiting_approval')
                   AND started_at < ?""",
                (utcnow_naive().isoformat(), cutoff.isoformat()),
            )
            conn.commit()

            return cursor.rowcount
