"""Agent scheduling database operations mixin (cron math, due agents)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from croniter import croniter

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
