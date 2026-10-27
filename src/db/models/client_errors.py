"""Errors the browser reports: one row per user and fingerprint, counted up.

Recording also prunes, so the table stays small without a scheduled job:
rows unseen for CLIENT_ERROR_RETENTION_DAYS go, and a user keeps at most
CLIENT_ERROR_MAX_ROWS_PER_USER (the most recently seen).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict

from src.config import Config
from src.db.models.timestamps import from_db, to_db
from src.utils.clock import to_api, utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


def _api_time(stored: str) -> str:
    """A stored last_seen as the API sends instants."""
    return to_api(from_db(stored, "local"))


class LayoutCheckRow(TypedDict):
    """One failed layout check in one build (see top_layout_checks)."""

    app_version: str | None
    build_marker: str | None
    invariant: str
    shape: str
    count: int
    users: int
    standalone_count: int
    last_seen: str
    detail: str  # the latest report's JSON


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
        detail: str | None = None,
    ) -> None:
        """Count one occurrence; the latest details replace the stored ones.

        `detail` is a layout check's measurements as JSON (kind "layout").
        """
        now = now or utc_now()
        with self._pool.get_connection() as conn:
            seen = to_db(now, "local", conn)
            self._execute_with_timing(
                conn,
                """INSERT INTO client_errors
                   (id, user_id, fingerprint, kind, message, stack, path, app_version,
                    user_agent, detail, count, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                       count = count + 1,
                       message = excluded.message,
                       stack = excluded.stack,
                       path = excluded.path,
                       app_version = excluded.app_version,
                       user_agent = excluded.user_agent,
                       detail = excluded.detail,
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
                    detail,
                    seen,
                    seen,
                ),
            )
            self._prune_client_errors(conn, user_id, now)
            conn.commit()

    def _prune_client_errors(self, conn: sqlite3.Connection, user_id: str, now: datetime) -> None:
        cutoff = to_db(now - timedelta(days=Config.CLIENT_ERROR_RETENTION_DAYS), "local", conn)
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
        Layout reports are not errors: see top_layout_checks.
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT fingerprint, kind, message, stack, path, app_version,
                          SUM(count) AS count, COUNT(DISTINCT user_id) AS users,
                          MAX(last_seen) AS last_seen
                   FROM client_errors WHERE last_seen >= ? AND kind != 'layout'
                   GROUP BY fingerprint
                   ORDER BY count DESC, last_seen DESC
                   LIMIT ?""",
                (to_db(since, "local", conn), limit),
            ).fetchall()
        return [{**dict(row), "last_seen": _api_time(row["last_seen"])} for row in rows]

    def top_layout_checks(self, since: datetime, limit: int) -> list[LayoutCheckRow]:
        """Failed layout checks seen since `since`, one row per build and check.

        A build is the app version plus the [kbN] marker; the newest-seen
        rows come first, so the latest build leads. `detail` is the latest
        report's JSON (SQLite takes bare columns from the MAX(last_seen) row).
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT app_version,
                          json_extract(detail, '$.build_marker') AS build_marker,
                          json_extract(detail, '$.invariant') AS invariant,
                          json_extract(detail, '$.shape') AS shape,
                          SUM(count) AS count, COUNT(DISTINCT user_id) AS users,
                          SUM(CASE WHEN json_extract(detail, '$.standalone')
                              THEN count ELSE 0 END) AS standalone_count,
                          MAX(last_seen) AS last_seen, detail
                   FROM client_errors
                   WHERE kind = 'layout' AND detail IS NOT NULL AND last_seen >= ?
                   GROUP BY app_version, build_marker, invariant, shape
                   ORDER BY last_seen DESC
                   LIMIT ?""",
                (to_db(since, "local", conn), limit),
            ).fetchall()
        return [
            LayoutCheckRow(
                app_version=row["app_version"],
                build_marker=row["build_marker"],
                invariant=row["invariant"],
                shape=row["shape"],
                count=row["count"],
                users=row["users"],
                standalone_count=row["standalone_count"],
                last_seen=_api_time(row["last_seen"]),
                detail=row["detail"],
            )
            for row in rows
        ]
