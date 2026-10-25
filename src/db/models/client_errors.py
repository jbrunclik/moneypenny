"""Errors the browser reports: one row per user and fingerprint, counted up.

Recording also prunes, so the table stays small without a scheduled job:
rows unseen for CLIENT_ERROR_RETENTION_DAYS go, and a user keeps at most
CLIENT_ERROR_MAX_ROWS_PER_USER (the most recently seen).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


class ClientErrorsMixin:
    """Mixin providing browser error reports."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def record_client_error(
        self,
        user_id: str,
        fingerprint: str,
        kind: str,
        message: str,
        stack: str | None,
        path: str | None,
        app_version: str | None,
        user_agent: str | None,
        now: datetime | None = None,
    ) -> None:
        """Count one occurrence; the latest details replace the stored ones."""
        seen = (now or datetime.now()).isoformat()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO client_errors
                   (id, user_id, fingerprint, kind, message, stack, path, app_version,
                    user_agent, count, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                       count = count + 1,
                       message = excluded.message,
                       stack = excluded.stack,
                       path = excluded.path,
                       app_version = excluded.app_version,
                       user_agent = excluded.user_agent,
                       last_seen = excluded.last_seen""",
                (
                    str(uuid.uuid4()),
                    user_id,
                    fingerprint,
                    kind,
                    message,
                    stack,
                    path,
                    app_version,
                    user_agent,
                    seen,
                    seen,
                ),
            )
            self._prune_client_errors(conn, user_id, now or datetime.now())

    def _prune_client_errors(self, conn: sqlite3.Connection, user_id: str, now: datetime) -> None:
        cutoff = (now - timedelta(days=Config.CLIENT_ERROR_RETENTION_DAYS)).isoformat()
        self._execute_with_timing(conn, "DELETE FROM client_errors WHERE last_seen < ?", (cutoff,))
        self._execute_with_timing(
            conn,
            """DELETE FROM client_errors WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM client_errors WHERE user_id = ?
                   ORDER BY last_seen DESC LIMIT ?)""",
            (user_id, user_id, Config.CLIENT_ERROR_MAX_ROWS_PER_USER),
        )

    def top_client_errors(self, since: datetime, limit: int) -> list[dict[str, Any]]:
        """Errors seen since `since` across users, most frequent first.

        Counts are lifetime totals of errors that recurred in the window.
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT fingerprint, kind, message, stack, path, app_version,
                          SUM(count) AS count, COUNT(DISTINCT user_id) AS users,
                          MAX(last_seen) AS last_seen
                   FROM client_errors WHERE last_seen >= ?
                   GROUP BY fingerprint
                   ORDER BY count DESC, last_seen DESC
                   LIMIT ?""",
                (since.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]
