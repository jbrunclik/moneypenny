"""Startup timing reports from the browser: one row per page load.

Recording also prunes rows older than CLIENT_BOOT_TIMINGS_RETENTION_DAYS, so
the table stays small without a scheduled job (as client_errors does).
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict

from src.config import Config
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

# The stage marks, in milliseconds since navigation start (None: not reached)
BOOT_MARKS = (
    "response_end_ms",
    "dom_content_loaded_ms",
    "script_ms",
    "auth_ms",
    "data_ms",
    "route_ms",
    "ready_ms",
)


class BootTiming(TypedDict):
    """One page load's report, as validated by the API schema."""

    marks: dict[str, int | None]
    standalone: bool
    viewport: str
    connection: str | None
    app_version: str | None
    route: str


class ClientBootTimingsMixin:
    """Mixin storing startup timing reports."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self, conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Cursor:
        raise NotImplementedError

    def add_client_boot_timing(self, user_id: str, timing: BootTiming) -> None:
        """Store one report and prune the old ones."""
        now = utc_now()
        cutoff = to_db(now - timedelta(days=Config.CLIENT_BOOT_TIMINGS_RETENTION_DAYS))
        marks = [timing["marks"].get(name) for name in BOOT_MARKS]
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                f"""INSERT INTO client_boot_timings
                    (user_id, created_at, {", ".join(BOOT_MARKS)},
                     standalone, viewport, connection, app_version, route)
                    VALUES ({", ".join("?" * (len(BOOT_MARKS) + 7))})""",  # noqa: S608 - fixed column names
                (
                    user_id,
                    to_db(now),
                    *marks,
                    int(timing["standalone"]),
                    timing["viewport"],
                    timing["connection"],
                    timing["app_version"],
                    timing["route"],
                ),
            )
            self._execute_with_timing(
                conn, "DELETE FROM client_boot_timings WHERE created_at < ?", (cutoff,)
            )
            conn.commit()
