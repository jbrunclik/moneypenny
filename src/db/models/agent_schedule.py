"""Agent scheduling database operations mixin (cron math, due agents)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from croniter import croniter

from src.db.models.agent_rows import row_to_agent
from src.db.models.dataclasses import Agent
from src.db.models.timestamps import to_db, to_db_or_none
from src.utils.clock import utc_now
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
            Next run as an aware UTC datetime, or None if invalid
        """
        try:
            tz = ZoneInfo(timezone)
            cron = croniter(schedule, utc_now().astimezone(tz))
            next_run: datetime = cron.get_next(datetime)
            return next_run.astimezone(UTC)
        except Exception as e:  # a bad stored schedule must not break the scheduler
            logger.warning(
                "Failed to calculate next run",
                extra={"schedule": schedule, "timezone": timezone, "error": str(e)},
                exc_info=True,
            )
            return None

    def get_due_agents(self, now: datetime | None = None) -> list[Agent]:
        """Get agents that are due for execution.

        Args:
            now: The current instant (aware). If None, uses the current time.

        Returns:
            Enabled agents where next_run_at <= now.
        """
        if now is None:
            now = utc_now()

        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM autonomous_agents
                   WHERE enabled = 1
                   AND next_run_at IS NOT NULL
                   AND next_run_at <= ?
                   ORDER BY next_run_at ASC""",
                (to_db(now, "utc", conn),),
            ).fetchall()

            return [row_to_agent(row) for row in rows]

    def update_agent_last_run(self, agent_id: str) -> None:
        """Update an agent's last_run_at and recalculate next_run_at.

        Only schedules the next run if the agent is still enabled.
        """
        now = utc_now()

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
                    to_db(now, "utc", conn),
                    to_db_or_none(next_run_at, "utc", conn),
                    to_db(now, "utc", conn),
                    agent_id,
                ),
            )
            conn.commit()

    def update_agent_next_run(self, agent_id: str, next_run_at: datetime) -> None:
        """Update an agent's next_run_at directly.

        Used by the scheduler when manually setting the next run time.
        """
        now = utc_now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    to_db(next_run_at, "utc", conn),
                    to_db(now, "utc", conn),
                    agent_id,
                ),
            )
            conn.commit()
