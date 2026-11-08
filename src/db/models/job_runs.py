"""Job runs: each run of a job, its trigger and outcome (job_runs)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import JobRun
from src.db.models.job_rows import row_to_job_run
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class JobRunMixin:
    """Mixin providing job run tracking."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_last_execution_status(self, item_id: str) -> str | None:
        """Get the status of the most recent run of a job.

        Returns:
            Status string ('completed', 'failed', etc.) or None if no executions
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT status FROM job_runs
                   WHERE item_id = ?
                   ORDER BY started_at DESC
                   LIMIT 1""",
                (item_id,),
            ).fetchone()
            return row["status"] if row else None

    def create_execution(
        self,
        item_id: str,
        trigger_type: str,
        triggered_by_job_id: str | None = None,
    ) -> JobRun:
        """Create a new execution record."""
        execution_id = str(uuid.uuid4())
        now = utc_now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO job_runs
                   (id, item_id, status, trigger_type, triggered_by_job_id, started_at)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (
                    execution_id,
                    item_id,
                    trigger_type,
                    triggered_by_job_id,
                    to_db(now),
                ),
            )
            conn.commit()

        return JobRun(
            id=execution_id,
            item_id=item_id,
            status="running",
            trigger_type=trigger_type,
            triggered_by_job_id=triggered_by_job_id,
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
                """UPDATE job_runs
                   SET status = ?, completed_at = ?, error_message = ?
                   WHERE id = ?""",
                (status, to_db(now), error_message, execution_id),
            )
            conn.commit()

    def recent_runs(self, job_ids: list[str], per_job: int = 3) -> dict[str, list[JobRun]]:
        """Each job's newest runs (one query), newest first."""
        if not job_ids:
            return {}
        marks = ", ".join("?" for _ in job_ids)
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY item_id ORDER BY started_at DESC, rowid DESC
                        ) AS rank
                        FROM job_runs WHERE item_id IN ({marks})
                    ) WHERE rank <= ? ORDER BY item_id, rank""",
                (*job_ids, per_job),
            ).fetchall()
        runs: dict[str, list[JobRun]] = {}
        for row in rows:
            runs.setdefault(row["item_id"], []).append(row_to_job_run(row))
        return runs

    def get_job_runs(self, item_id: str, limit: int = 20) -> list[JobRun]:
        """Get recent runs of a job."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM job_runs
                   WHERE item_id = ?
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (item_id, limit),
            ).fetchall()

            return [row_to_job_run(row) for row in rows]

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
                """UPDATE job_runs
                   SET status = 'failed',
                       completed_at = ?,
                       error_message = 'Execution timed out (zombie cleanup)'
                   WHERE status IN ('running', 'waiting_approval')
                   AND started_at < ?""",
                (to_db(utc_now()), to_db(cutoff)),
            )
            conn.commit()

            return cursor.rowcount
