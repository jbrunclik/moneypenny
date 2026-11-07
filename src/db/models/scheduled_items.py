"""Scheduled items set from chat: stored, listed, paused, deleted, and claimed when due.

Items follow their chat by query: only items whose conversation is live (not
in the trash, not archived) are listed, counted or claimed, so trashing or
archiving a chat suspends them and restoring it brings them back; a trigger
deletes them with the conversation row (migration 0076).

claim_due_items flips due active rows to "running" in one UPDATE ...
RETURNING, so two overlapping scheduler runs never handle one twice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import astuple, fields
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.db.models.dataclasses import ScheduledItem
from src.db.models.timestamps import from_db, from_db_or_none, to_db, to_db_or_none

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

_LIVE_CHAT = """conversation_id IN (SELECT id FROM conversations
    WHERE deleted_at IS NULL AND (archived = 0 OR archived IS NULL))"""
_COLUMNS = [f.name for f in fields(ScheduledItem)]
_TIMES = {"next_run_at", "expires_at", "created_at", "claimed_at"}


def _row_to_item(row: sqlite3.Row) -> ScheduledItem:
    return ScheduledItem(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        kind=row["kind"],
        text=row["text"],
        end_condition=row["end_condition"],
        schedule=row["schedule"],
        interval_hours=row["interval_hours"],
        next_run_at=from_db(row["next_run_at"]),
        expires_at=from_db_or_none(row["expires_at"]),
        status=row["status"],
        last_result=row["last_result"],
        quiet_runs=row["quiet_runs"],
        failures=row["failures"],
        created_at=from_db(row["created_at"]),
        claimed_at=from_db_or_none(row["claimed_at"]),
    )


def _stored(item: ScheduledItem) -> tuple[object, ...]:
    return tuple(
        to_db_or_none(value) if name in _TIMES else value
        for name, value in zip(_COLUMNS, astuple(item), strict=True)
    )


class ScheduledItemsMixin:
    """Scheduled item rows for the schedule tool, the API and the scheduler."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self, conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> sqlite3.Cursor:
        raise NotImplementedError

    def add_item(self, item: ScheduledItem) -> ScheduledItem:
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                f"INSERT INTO scheduled_items ({', '.join(_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                _stored(item),
            )
            conn.commit()
        return item

    def get_item(self, item_id: str, user_id: str) -> ScheduledItem | None:
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM scheduled_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            ).fetchone()
        return _row_to_item(row) if row else None

    def list_items(self, user_id: str, conversation_id: str | None = None) -> list[ScheduledItem]:
        """The user's items in live chats (optionally one chat), soonest first."""
        query = f"SELECT * FROM scheduled_items WHERE user_id = ? AND {_LIVE_CHAT}"
        params: tuple[object, ...] = (user_id,)
        if conversation_id is not None:
            query += " AND conversation_id = ?"
            params = (user_id, conversation_id)
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(conn, query + " ORDER BY next_run_at", params)
            return [_row_to_item(row) for row in rows.fetchall()]

    def count_items(self, user_id: str) -> int:
        """All the user's items in live chats, paused included (the cap counts them)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT COUNT(*) FROM scheduled_items WHERE user_id = ? AND {_LIVE_CHAT}",
                (user_id,),
            ).fetchone()
        return int(row[0])

    def set_item_paused(self, item_id: str, user_id: str, paused: bool) -> bool:
        """Pause or resume one of the user's items; False if none matched."""
        source, target = ("active", "paused") if paused else ("paused", "active")
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE scheduled_items SET status = ? WHERE id = ? AND user_id = ? AND status = ?",
                (target, item_id, user_id, source),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_item(self, item_id: str, user_id: str | None = None) -> bool:
        """Delete an item (the user's own, or any for the scheduler); False if none."""
        query = "DELETE FROM scheduled_items WHERE id = ?"
        params: tuple[object, ...] = (item_id,)
        if user_id is not None:
            query, params = query + " AND user_id = ?", (item_id, user_id)
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(conn, query, params)
            conn.commit()
            return cursor.rowcount > 0

    def claim_due_items(self, now: datetime) -> list[ScheduledItem]:
        """Mark every active item due by `now` in a live chat as running; return them."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""UPDATE scheduled_items SET status = 'running', claimed_at = ?
                    WHERE status = 'active' AND next_run_at <= ? AND {_LIVE_CHAT}
                    RETURNING *""",
                (to_db(now), to_db(now)),
            ).fetchall()
            conn.commit()
        return sorted((_row_to_item(row) for row in rows), key=lambda i: i.next_run_at)

    def finish_item_run(
        self,
        item_id: str,
        next_run_at: datetime,
        last_result: str | None,
        quiet_runs: int,
        failures: int,
    ) -> None:
        """Hand a run item back to the scheduler for its next run."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE scheduled_items SET status = 'active', claimed_at = NULL,
                       next_run_at = ?, last_result = ?, quiet_runs = ?, failures = ?
                   WHERE id = ?""",
                (to_db(next_run_at), last_result, quiet_runs, failures, item_id),
            )
            conn.commit()

    def reset_stale_runs(self, now: datetime, stale_minutes: int) -> int:
        """Give back items whose run never finished (a crashed or killed scheduler),
        counting it as a failure - a run that always dies must not re-run forever."""
        cutoff = to_db(now - timedelta(minutes=stale_minutes))
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE scheduled_items
                   SET status = 'active', claimed_at = NULL, failures = failures + 1
                   WHERE status = 'running' AND claimed_at <= ?""",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
