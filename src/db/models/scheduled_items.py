"""Scheduled items set from chat: stored, listed, paused, deleted, and claimed when due.

Items follow their chat by query: only items whose conversation is live (not
in the trash, not archived) are listed, counted or claimed, so trashing or
archiving a chat suspends them and restoring it brings them back; a trigger
deletes them with the conversation row (migration 0076).

claim_due_items flips due active rows to "running" in one UPDATE ...
RETURNING, so two overlapping scheduler runs never handle one twice.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import astuple, fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from src.db.models.dataclasses import ScheduledItem
from src.db.models.timestamps import from_db, from_db_or_none, to_db, to_db_or_none
from src.utils.clock import local_day_start, utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

_LIVE_CHAT = """conversation_id IN (SELECT id FROM conversations
    WHERE deleted_at IS NULL AND (archived = 0 OR archived IS NULL))"""
# An agent's standing job (same id as the agent): managed as the agent
# (Agents page, update_agent), never as a chat item
_AGENT_JOB = "id IN (SELECT job_id FROM conversations WHERE is_agent = 1 AND job_id IS NOT NULL)"
# Back from a run: an agent disabled meanwhile stays paused
_AFTER_RUN_STATUS = "CASE WHEN paused_reason = 'disabled' THEN 'paused' ELSE 'active' END"
_COLUMNS = [f.name for f in fields(ScheduledItem)]
_TIMES = {"next_run_at", "expires_at", "created_at", "claimed_at"}
# A standing job with no schedule (run by hand or by another agent only)
NEVER_RUN_AT = datetime(9999, 12, 31, tzinfo=UTC)
# A migrated or new agent's job: its chat's standing instructions say what to do
STANDING_JOB_TEXT = "Do what this chat's standing instructions describe."
ITEM_INSERT_SQL = (
    f"INSERT INTO scheduled_items ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _COLUMNS)})"
)


def _grants(raw: str | None) -> list[str] | None:
    return [str(g) for g in json.loads(raw)] if raw is not None else None


def row_to_item(row: sqlite3.Row) -> ScheduledItem:
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
        grants=_grants(row["grants"]),
        model=row["model"],
        budget_usd=row["budget_usd"],
        fresh_context=bool(row["fresh_context"]),
        timezone=row["timezone"],
        paused_reason=row["paused_reason"],
    )


def _stored_value(name: str, value: object) -> object:
    if name in _TIMES:
        return to_db_or_none(value)  # type: ignore[arg-type]
    if name == "grants":
        return json.dumps(value) if value is not None else None
    return value


def stored_item(item: ScheduledItem) -> tuple[object, ...]:
    """An item's column values, in ITEM_INSERT_SQL's order."""
    return tuple(
        _stored_value(name, value) for name, value in zip(_COLUMNS, astuple(item), strict=True)
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
                ITEM_INSERT_SQL,
                stored_item(item),
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
        return row_to_item(row) if row else None

    def list_items(self, user_id: str, conversation_id: str | None = None) -> list[ScheduledItem]:
        """The user's items in live chats (optionally one chat), soonest first;
        agents' jobs are listed as agents, not here."""
        query = (
            f"SELECT * FROM scheduled_items WHERE user_id = ? AND {_LIVE_CHAT} AND NOT {_AGENT_JOB}"
        )
        params: tuple[object, ...] = (user_id,)
        if conversation_id is not None:
            query += " AND conversation_id = ?"
            params = (user_id, conversation_id)
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(conn, query + " ORDER BY next_run_at", params)
            return [row_to_item(row) for row in rows.fetchall()]

    def list_all_items(self, user_id: str) -> list[ScheduledItem]:
        """Every item and job of the user in live chats - agents' jobs
        included (the job list), soonest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"SELECT * FROM scheduled_items WHERE user_id = ? AND {_LIVE_CHAT} ORDER BY next_run_at",
                (user_id,),
            )
            return [row_to_item(row) for row in rows.fetchall()]

    def job_week_stats(self, user_id: str, days: int = 7) -> dict[str, dict[str, float]]:
        """Each standing job's runs (by outcome) and its own cost over the
        trailing window: {job_id: {runs, completed, failed, cost_usd}}."""
        since = to_db(utc_now() - timedelta(days=days))
        stats: dict[str, dict[str, float]] = {}
        with self._pool.get_connection() as conn:
            runs = self._execute_with_timing(
                conn,
                """SELECT e.item_id AS job_id, e.status, COUNT(*) AS n
                   FROM job_runs e JOIN scheduled_items s ON s.id = e.item_id
                   WHERE s.user_id = ? AND e.started_at >= ? GROUP BY 1, 2""",
                (user_id, since),
            ).fetchall()
            costs = self._execute_with_timing(
                conn,
                """SELECT mc.job_id, COALESCE(SUM(mc.cost_usd), 0) AS cost
                   FROM message_costs mc JOIN scheduled_items s ON s.id = mc.job_id
                   WHERE s.user_id = ? AND mc.created_at >= ? GROUP BY 1""",
                (user_id, since),
            ).fetchall()
        for row in runs:
            job = stats.setdefault(
                row["job_id"], {"runs": 0, "completed": 0, "failed": 0, "cost_usd": 0.0}
            )
            job["runs"] += row["n"]
            if row["status"] in ("completed", "failed"):
                job[row["status"]] += row["n"]
        for row in costs:
            job = stats.setdefault(
                row["job_id"], {"runs": 0, "completed": 0, "failed": 0, "cost_usd": 0.0}
            )
            job["cost_usd"] = float(row["cost"])
        return stats

    def count_items(self, user_id: str) -> int:
        """The user's light items in live chats, paused included (the cap counts
        them); standing jobs have no count limit."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT COUNT(*) FROM scheduled_items
                    WHERE user_id = ? AND grants IS NULL AND {_LIVE_CHAT}""",
                (user_id,),
            ).fetchone()
        return int(row[0])

    def set_item_paused(
        self, item_id: str, user_id: str, paused: bool, reason: str | None = None
    ) -> bool:
        """Pause (with an optional reason) or resume one of the user's items;
        resuming clears the reason and the failure count. False if none matched."""
        source, target = ("active", "paused") if paused else ("paused", "active")
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE scheduled_items
                   SET status = ?, paused_reason = ?,
                       failures = CASE WHEN ? THEN failures ELSE 0 END
                   WHERE id = ? AND user_id = ? AND status = ?""",
                (target, reason if paused else None, paused, item_id, user_id, source),
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_agent_job(self, item_id: str) -> bool:
        """Whether the item is an agent's standing job (managed as the agent)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT 1 FROM conversations WHERE is_agent = 1 AND job_id = ?",
                (item_id,),
            ).fetchone()
        return row is not None

    def job_spend_today(self, job_id: str) -> float:
        """A standing job's own unattended spend since local midnight (its
        daily budget; the user's turns in the same chat are not counted)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COALESCE(SUM(cost_usd), 0) FROM message_costs
                   WHERE job_id = ? AND created_at >= ?""",
                (job_id, to_db(local_day_start(utc_now()))),
            ).fetchone()
        return float(row[0])

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
        return sorted((row_to_item(row) for row in rows), key=lambda i: i.next_run_at)

    def claim_item(self, item_id: str, now: datetime) -> tuple[str, datetime] | None:
        """Claim one item for a hand-started run, as the scheduler claims due
        ones (so neither runs it twice); returns the status to restore and the
        claim, or None when it is running already or gone."""
        for prior in ("active", "paused"):
            with self._pool.get_connection() as conn:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE scheduled_items SET status = 'running', claimed_at = ?
                       WHERE id = ? AND status = ?""",
                    (to_db(now), item_id, prior),
                )
                conn.commit()
            if cursor.rowcount > 0:
                return prior, now
        return None

    def release_item(self, item_id: str, claimed_at: datetime, status: str) -> bool:
        """End a hand-started run's claim, back to `status`, keeping the
        schedule; only if that claim still holds."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE scheduled_items
                   SET status = CASE WHEN paused_reason = 'disabled' THEN 'paused' ELSE ? END,
                       claimed_at = NULL
                   WHERE id = ? AND status = 'running' AND claimed_at = ?""",
                (status, item_id, to_db(claimed_at)),
            )
            conn.commit()
            return cursor.rowcount > 0

    def finish_item_run(
        self,
        item_id: str,
        next_run_at: datetime,
        last_result: str | None,
        quiet_runs: int,
        failures: int,
        claimed_at: datetime | None = None,
    ) -> bool:
        """Hand a run item back to the scheduler for its next run; with
        `claimed_at`, only if that claim still holds (a run that outlived a
        stale reset must not overwrite the newer claim). False if nothing matched."""
        query = f"""UPDATE scheduled_items SET status = {_AFTER_RUN_STATUS}, claimed_at = NULL,
                       next_run_at = ?, last_result = ?, quiet_runs = ?, failures = ?
                   WHERE id = ?"""
        params: tuple[object, ...] = (
            to_db(next_run_at),
            last_result,
            quiet_runs,
            failures,
            item_id,
        )
        if claimed_at is not None:
            query += " AND status = 'running' AND claimed_at = ?"
            params = (*params, to_db(claimed_at))
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(conn, query, params)
            conn.commit()
            return cursor.rowcount > 0

    def item_claim_state(
        self, item_id: str, claimed_at: datetime | None
    ) -> Literal["gone", "suspended", "live"]:
        """Whether a run's result may be delivered: its claim is gone (the item
        was cancelled or re-claimed), its chat is suspended (trashed or
        archived meanwhile), or it is live."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT {_LIVE_CHAT} AS live FROM scheduled_items
                    WHERE id = ? AND status = 'running' AND claimed_at IS ?""",
                (item_id, to_db_or_none(claimed_at)),
            ).fetchone()
        if row is None:
            return "gone"
        return "live" if row["live"] else "suspended"

    def reset_stale_runs(self, now: datetime, stale_minutes: int) -> int:
        """Give back items whose run never finished (a crashed or killed scheduler),
        counting it as a failure - a run that always dies must not re-run forever."""
        cutoff = to_db(now - timedelta(minutes=stale_minutes))
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE scheduled_items
                   SET status = {_AFTER_RUN_STATUS}, claimed_at = NULL, failures = failures + 1
                   WHERE status = 'running' AND claimed_at <= ?""",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
