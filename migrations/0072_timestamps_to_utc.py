"""Rewrite every stored timestamp as fixed-width UTC with an offset.

Step 3 of the timezone-aware datetimes design
(docs/superpowers/specs/2026-10-26-timezone-aware-datetimes-design.md).
Columns held one of two naive legacy formats: host wall-clock time
("local" - conversation data, costs, memories) or UTC-naive ("utc" - agents,
kv_store, settings, artifacts). The UTC-naive convention began with ce810114,
deployed Jun 10 2026 ~22:00 local: rows of those tables written before it are
local ("utc_since"). The Nov 1 2026 dry run on a production backup found no
row near that cutoff and none in the repeated hour of Oct 25 2026.

Every value becomes ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00`` (the string the API
sends; it sorts chronologically) and the app_settings flag
``timestamp_storage`` reads ``utc`` in the same transaction, so the app's
``to_db`` writes the new format from then on.

- Per-row idempotent: a value that already carries an offset is only
  normalized, so a re-run (yoyo records the migration in a separate
  transaction) converts nothing twice. The rollback writes the legacy
  formats back (each column's kind says which zone).
- Cache tables are emptied, not converted (they refill within the hour).
- ``sync_change_message_update`` is dropped around the messages UPDATE and
  recreated from its own stored SQL: one sync bump per message would make
  every device re-fetch every conversation message by message. The
  conversations UPDATE bumps each conversation once (accepted in the design).
- Not touched: epoch-float columns (stream_journal, context_cache),
  timestamps inside JSON values (read with ``from_db``, which accepts both),
  and files.db (write-only ``blobs.created_at``).
"""

import sqlite3
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

from yoyo import step

__depends__ = {"0071_add_device_check_runs"}

# The zone "local" values were written in: the production host's, on
# Europe/Prague since at least Dec 14 2025 (checked from paired UTC/local rows)
_LEGACY_ZONE = ZoneInfo("Europe/Prague")

# ce810114's deploy, local wall-clock time: "utc_since" values before it are
# local. Compared as an instant against the value read both ways (below)
_UTC_NAIVE_SINCE = datetime(2026, 6, 10, 22, 0)  # noqa: DTZ001 - a naive stored value's wall time
_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"

# table -> {column: kind}; kind "local", "utc" or "utc_since"
COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "created_at": "local",
        "todoist_connected_at": "local",
        "google_calendar_token_expires_at": "local",
        "google_calendar_connected_at": "local",
        "planner_last_reset_at": "local",
        "garmin_connected_at": "local",
        "rouvy_connected_at": "local",
    },
    # created_at of agent conversations is utc_since (create_agent wrote it
    # UTC-naive); see _CONVERSATION_CREATED
    "conversations": {
        "updated_at": "local",
        "last_reset": "local",
        "deleted_at": "local",
        "trashed_updated_at": "local",
    },
    "messages": {"created_at": "local"},
    "message_costs": {"created_at": "local"},
    "user_memories": {"created_at": "local", "updated_at": "local", "deleted_at": "local"},
    "push_subscriptions": {"created_at": "local", "last_used_at": "local"},
    "embeddings": {"created_at": "local"},
    "client_errors": {"first_seen": "local", "last_seen": "local"},
    "autonomous_agents": {
        "created_at": "utc_since",
        "updated_at": "utc_since",
        "last_run_at": "utc_since",
        "next_run_at": "utc_since",
        "last_viewed_at": "local",
    },
    "agent_executions": {"started_at": "utc_since", "completed_at": "utc_since"},
    "agent_approval_requests": {
        "created_at": "utc_since",
        "resolved_at": "utc_since",
        "expires_at": "utc_since",
    },
    "kv_store": {"created_at": "utc_since", "updated_at": "utc_since"},
    "app_settings": {"updated_at": "utc_since"},
    "artifacts": {"created_at": "utc", "updated_at": "utc"},
    "artifact_versions": {"created_at": "utc"},
    "device_check_runs": {"started_at": "utc", "finished_at": "utc", "created_at": "utc"},
    "device_check_fixtures": {"created_at": "utc"},
}
_CONVERSATION_CREATED = (
    "CASE WHEN is_agent = 1 THEN {function}(created_at, 'utc_since') "
    "ELSE {function}(created_at, 'local') END"
)
CACHE_TABLES = ("dashboard_cache", "weather_cache", "calendar_cache")
_MESSAGE_TRIGGER = "sync_change_message_update"
_FLAG = "timestamp_storage"


def to_utc(value: str | None, kind: str, zone: tzinfo | None = None) -> str | None:
    """A stored value as fixed-width UTC (NULL and '' unchanged)."""
    if not value:
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        local = zone or _LEGACY_ZONE
        if kind == "utc_since":
            # Before the cutoff the row was written local
            kind = "local" if parsed < _UTC_NAIVE_SINCE else "utc"
        # fold=0: a value in a repeated fall-back hour reads as its first
        # occurrence (the dry run found none)
        parsed = parsed.replace(tzinfo=local if kind == "local" else UTC)
    return parsed.astimezone(UTC).strftime(_FORMAT)


def to_legacy(value: str | None, kind: str, zone: tzinfo | None = None) -> str | None:
    """A fixed-width UTC value back in its column's legacy naive format (rollback)."""
    if not value:
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return value
    local = zone or _LEGACY_ZONE
    if kind == "utc_since":
        cutoff = _UTC_NAIVE_SINCE.replace(tzinfo=local)
        kind = "local" if parsed < cutoff else "utc"
    return parsed.astimezone(local if kind == "local" else UTC).replace(tzinfo=None).isoformat()


def _existing(conn: sqlite3.Connection) -> dict[str, set[str]]:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}


def _update(conn: sqlite3.Connection, table: str, sets: list[str]) -> None:
    if sets:
        conn.execute(f'UPDATE "{table}" SET {", ".join(sets)}')  # noqa: S608 - names from COLUMNS


def _rewrite(conn: sqlite3.Connection, function: str) -> None:
    """Apply a to_utc/to_legacy SQL function to every listed column present."""
    existing = _existing(conn)
    for table, columns in COLUMNS.items():
        present = existing.get(table, set())
        sets = [f'"{c}" = {function}("{c}", \'{k}\')' for c, k in columns.items() if c in present]
        if table == "conversations" and "created_at" in present:
            sets.append(f"created_at = {_CONVERSATION_CREATED.format(function=function)}")
        if table != "messages":
            _update(conn, table, sets)
            continue
        trigger = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (_MESSAGE_TRIGGER,),
        ).fetchone()
        if trigger:
            conn.execute(f"DROP TRIGGER {_MESSAGE_TRIGGER}")
        _update(conn, table, sets)
        if trigger:
            conn.execute(trigger[0])


def convert(conn: sqlite3.Connection) -> None:
    """Rewrite every listed column as UTC, empty the caches, set the flag."""
    conn.create_function("to_utc", 2, to_utc, deterministic=True)
    _rewrite(conn, "to_utc")
    existing = _existing(conn)
    for table in CACHE_TABLES:
        if table in existing:
            conn.execute(f'DELETE FROM "{table}"')  # noqa: S608 - names from CACHE_TABLES
    if "app_settings" in existing:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, 'utc', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = 'utc', updated_at = excluded.updated_at",
            (_FLAG, datetime.now(UTC).strftime(_FORMAT)),
        )


def revert(conn: sqlite3.Connection) -> None:
    """Back to the legacy formats. Only for code from before Nov 7 2026: the
    app since then reads offset-carrying values only (timestamps.from_db)."""
    conn.execute("DELETE FROM app_settings WHERE key = ?", (_FLAG,))
    conn.create_function("to_legacy", 2, to_legacy, deterministic=True)
    _rewrite(conn, "to_legacy")


steps = [step(convert, revert)]
