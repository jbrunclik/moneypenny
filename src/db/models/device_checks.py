"""Device check runs and the runner's fixture conversations.

Runs: one row per finished run, scenarios and environment as JSON; the
newest DEVICE_CHECK_RUNS_KEPT are kept (pruned on insert).

Fixtures: a throwaway archived conversation written straight to the
database - no model call, no embedding, nothing pushed - and listed in
device_check_fixtures, which is the only way a purge finds a conversation:
a real one never matches.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypedDict

from src.config import Config
from src.db.models.timestamps import from_db, to_db
from src.utils.clock import to_api, utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

DEVICE_CHECK_RUNS_KEPT = 200

type Measurements = dict[str, float | bool | str | None]


class DeviceCheckScenarioRow(TypedDict):
    id: str
    title: str
    status: str
    duration_ms: int
    measurements: Measurements
    notes: list[str]


class NewDeviceCheckRun(TypedDict):
    """A finished run as the runner reported it (aware datetimes)."""

    build_marker: str | None
    app_version: str | None
    standalone: bool
    ua_summary: str
    environment: Measurements
    scenarios: list[DeviceCheckScenarioRow]
    started_at: datetime
    finished_at: datetime


class DeviceCheckRunRow(TypedDict):
    """A stored run, timestamps in the API format."""

    id: str
    build_marker: str | None
    app_version: str | None
    standalone: bool
    ua_summary: str
    environment: Measurements
    scenarios: list[DeviceCheckScenarioRow]
    passed: int
    failed: int
    skipped: int
    started_at: str
    finished_at: str
    created_at: str


# Fixture messages get distinct, ascending times so the list orders them
_FIXTURE_MESSAGE_SPACING = timedelta(seconds=1)

_RUN_COLUMNS = """id, build_marker, app_version, standalone, ua_summary, environment, scenarios,
                  passed, failed, skipped, started_at, finished_at, created_at"""


def _api_time(value: str) -> str:
    return to_api(from_db(value, "utc"))


def _row_to_run(row: sqlite3.Row) -> DeviceCheckRunRow:
    return {
        "id": row["id"],
        "build_marker": row["build_marker"],
        "app_version": row["app_version"],
        "standalone": bool(row["standalone"]),
        "ua_summary": row["ua_summary"],
        "environment": json.loads(row["environment"]),
        "scenarios": json.loads(row["scenarios"]),
        "passed": row["passed"],
        "failed": row["failed"],
        "skipped": row["skipped"],
        "started_at": _api_time(row["started_at"]),
        "finished_at": _api_time(row["finished_at"]),
        "created_at": _api_time(row["created_at"]),
    }


class DeviceChecksMixin:
    """Mixin providing device check runs and fixture conversations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Hard delete (defined in ConversationMixin)."""
        raise NotImplementedError

    def add_device_check_run(
        self,
        user_id: str,
        run: NewDeviceCheckRun,
        counts: tuple[int, int, int],
    ) -> DeviceCheckRunRow:
        """Store a finished run (``run``: the request's fields, datetimes aware)."""
        run_id = str(uuid.uuid4())
        passed, failed, skipped = counts
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                f"""INSERT INTO device_check_runs (user_id, {_RUN_COLUMNS})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    run_id,
                    run["build_marker"],
                    run["app_version"],
                    int(run["standalone"]),
                    run["ua_summary"],
                    json.dumps(run["environment"]),
                    json.dumps(run["scenarios"]),
                    passed,
                    failed,
                    skipped,
                    to_db(run["started_at"], "utc", conn),
                    to_db(run["finished_at"], "utc", conn),
                    to_db(utc_now(), "utc", conn),
                ),
            )
            # rowid, not created_at: two runs stored within a clock tick
            # still keep their order
            self._execute_with_timing(
                conn,
                """DELETE FROM device_check_runs WHERE rowid NOT IN (
                       SELECT rowid FROM device_check_runs ORDER BY rowid DESC LIMIT ?)""",
                (DEVICE_CHECK_RUNS_KEPT,),
            )
            row = self._execute_with_timing(
                conn, f"SELECT {_RUN_COLUMNS} FROM device_check_runs WHERE id = ?", (run_id,)
            ).fetchone()
            conn.commit()
        return _row_to_run(row)

    def list_device_check_runs(self, limit: int) -> list[DeviceCheckRunRow]:
        """The newest runs (every admin's), newest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"SELECT {_RUN_COLUMNS} FROM device_check_runs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def create_device_check_fixture(
        self, user_id: str, title: str, messages: list[tuple[str, str]]
    ) -> str:
        """Write an archived conversation with ``messages`` (role, content) and
        record it as a fixture. No embeddings: this bypasses add_message."""
        conv_id = str(uuid.uuid4())
        start = utc_now() - _FIXTURE_MESSAGE_SPACING * len(messages)
        with self._pool.get_connection() as conn:
            now = to_db(utc_now(), "local", conn)
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations (id, user_id, title, model, archived, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (conv_id, user_id, title, Config.DEFAULT_MODEL, now, now),
            )
            for index, (role, content) in enumerate(messages):
                created = to_db(start + _FIXTURE_MESSAGE_SPACING * index, "local", conn)
                self._execute_with_timing(
                    conn,
                    """INSERT INTO messages (id, conversation_id, role, content, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), conv_id, role, content, created),
                )
            self._execute_with_timing(
                conn,
                """INSERT INTO device_check_fixtures (conversation_id, user_id, created_at)
                   VALUES (?, ?, ?)""",
                (conv_id, user_id, to_db(utc_now(), "utc", conn)),
            )
            conn.commit()
        return conv_id

    def purge_device_check_fixtures(self, user_id: str) -> int:
        """Permanently delete the user's fixture conversations (not via the trash)."""
        with self._pool.get_connection() as conn:
            ids = [
                row["conversation_id"]
                for row in self._execute_with_timing(
                    conn,
                    "SELECT conversation_id FROM device_check_fixtures WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
            ]
        purged = 0
        for conv_id in ids:
            purged += self.delete_conversation(conv_id, user_id)
            with self._pool.get_connection() as conn:
                self._execute_with_timing(
                    conn,
                    "DELETE FROM device_check_fixtures WHERE conversation_id = ? AND user_id = ?",
                    (conv_id, user_id),
                )
                conn.commit()
        return purged
