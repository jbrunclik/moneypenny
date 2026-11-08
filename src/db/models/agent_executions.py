"""Agent execution tracking database operations mixin."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.agent_rows import row_to_execution
from src.db.models.dataclasses import AgentExecution
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
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
        now = utc_now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO agent_executions
                   (id, agent_id, status, trigger_type, triggered_by_agent_id, started_at)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (
                    execution_id,
                    agent_id,
                    trigger_type,
                    triggered_by_agent_id,
                    to_db(now),
                ),
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
        now = utc_now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = ?, completed_at = ?, error_message = ?
                   WHERE id = ?""",
                (status, to_db(now), error_message, execution_id),
            )
            conn.commit()

    def recent_runs(self, job_ids: list[str], per_job: int = 3) -> dict[str, list[AgentExecution]]:
        """Each job's newest runs (one query), newest first."""
        if not job_ids:
            return {}
        marks = ", ".join("?" for _ in job_ids)
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY agent_id ORDER BY started_at DESC, rowid DESC
                        ) AS rank
                        FROM agent_executions WHERE agent_id IN ({marks})
                    ) WHERE rank <= ? ORDER BY agent_id, rank""",
                (*job_ids, per_job),
            ).fetchall()
        runs: dict[str, list[AgentExecution]] = {}
        for row in rows:
            runs.setdefault(row["agent_id"], []).append(row_to_execution(row))
        return runs

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

    def cleanup_zombie_executions(self) -> int:
        """Clean up executions stuck in 'running' or 'waiting_approval' status.

        Marks executions as 'failed' if they've been stuck for longer than
        AGENT_EXECUTION_TIMEOUT_MINUTES. This prevents permanently locked agents
        due to crashed executions.

        Returns:
            Number of zombie executions cleaned up.
        """
        cutoff = utc_now() - timedelta(minutes=Config.AGENT_EXECUTION_TIMEOUT_MINUTES)

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = 'failed',
                       completed_at = ?,
                       error_message = 'Execution timed out (zombie cleanup)'
                   WHERE status IN ('running', 'waiting_approval')
                   AND started_at < ?""",
                (to_db(utc_now()), to_db(cutoff)),
            )
            conn.commit()

            return cursor.rowcount
