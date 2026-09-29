"""Agent scheduling database operations mixin (cron math, due agents)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.agent_rows import row_to_agent
from src.db.models.dataclasses import Agent
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentScheduleMixin:
    """Mixin providing agent scheduling operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def calculate_next_run(self, schedule: str, timezone: str) -> datetime | None:
        """Calculate the next run time based on a cron expression.

        Args:
            schedule: Cron expression (e.g., "0 9 * * *")
            timezone: Timezone for interpretation

        Returns:
            Next run datetime in UTC (naive), or None if invalid
        """
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
            cron = croniter(schedule, now)
            next_run: datetime = cron.get_next(datetime)
            # Convert to UTC for storage (naive datetime)
            return next_run.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"Failed to calculate next run: {e}")
            return None

    def get_due_agents(self, now: datetime | None = None) -> list[Agent]:
        """Get agents that are due for execution.

        Args:
            now: Current time in UTC (naive datetime). If None, uses current UTC time.

        Returns:
            Enabled agents where next_run_at <= now.
        """
        if now is None:
            # Use UTC to match how next_run_at is stored

            now = utcnow_naive()

        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM autonomous_agents
                   WHERE enabled = 1
                   AND next_run_at IS NOT NULL
                   AND next_run_at <= ?
                   ORDER BY next_run_at ASC""",
                (now.isoformat(),),
            ).fetchall()

            return [row_to_agent(row) for row in rows]

    def update_agent_last_run(self, agent_id: str) -> None:
        """Update an agent's last_run_at and recalculate next_run_at.

        Only schedules the next run if the agent is still enabled.
        """
        now = utcnow_naive()

        with self._pool.get_connection() as conn:
            # Get the agent's schedule, timezone, and enabled status
            row = self._execute_with_timing(
                conn,
                "SELECT schedule, timezone, enabled FROM autonomous_agents WHERE id = ?",
                (agent_id,),
            ).fetchone()

            if not row:
                return

            next_run_at = None
            # Only calculate next run if agent is enabled and has a schedule
            if row["enabled"] and row["schedule"]:
                next_run_at = self.calculate_next_run(row["schedule"], row["timezone"] or "UTC")

            self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET last_run_at = ?, next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    now.isoformat(),
                    next_run_at.isoformat() if next_run_at else None,
                    now.isoformat(),
                    agent_id,
                ),
            )
            conn.commit()

    def update_agent_next_run(self, agent_id: str, next_run_at: datetime) -> None:
        """Update an agent's next_run_at directly.

        Used by the scheduler when manually setting the next run time.
        """
        now = utcnow_naive()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    next_run_at.isoformat(),
                    now.isoformat(),
                    agent_id,
                ),
            )
            conn.commit()
