"""Standing chats: an agent is a chat with standing settings (name,
instructions, description, built-in type) plus a standing job with the same
id that carries its schedule, grants, model and budget (scheduled_items).

Read together as a StandingChat; created, changed and deleted together.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from types import EllipsisType
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from croniter import croniter

from src.config import Config
from src.db.models.dataclasses import ScheduledItem, StandingChat
from src.db.models.helpers import delete_messages_blobs
from src.db.models.scheduled_items import (
    ITEM_INSERT_SQL,
    NEVER_RUN_AT,
    STANDING_JOB_TEXT,
    row_to_item,
    stored_item,
)
from src.db.models.timestamps import from_db, from_db_or_none, to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

ALL_GRANTS = "*"

_SELECT = """
SELECT s.*, c.standing_name, c.standing_instructions, c.standing_description,
       c.standing_type, c.updated_at AS chat_updated_at,
       (SELECT MAX(r.started_at) FROM job_runs r WHERE r.item_id = s.id) AS last_run_at
FROM conversations c JOIN scheduled_items s ON s.id = c.job_id
WHERE c.is_agent = 1
"""

# Conversation columns a None update must not blank
_NOT_NULL = frozenset({"title", "model", "standing_name"})
# enabled=True means "run again": it undoes a disable and a pause after
# failures (clearing the count); SET expressions all read the row's old values
_ENABLE_SQL = (
    "status = CASE WHEN paused_reason IN ('disabled', 'failures') THEN 'active' ELSE status END",
    "failures = CASE WHEN paused_reason = 'failures' THEN 0 ELSE failures END",
    "paused_reason = CASE WHEN paused_reason IN ('disabled', 'failures') THEN NULL "
    "ELSE paused_reason END",
)
_DISABLE_SQL = (
    "status = CASE WHEN status = 'running' THEN status ELSE 'paused' END",
    "paused_reason = 'disabled'",
)


def _row_to_standing_chat(row: sqlite3.Row) -> StandingChat:
    return StandingChat(
        job=row_to_item(row),
        name=row["standing_name"],
        instructions=row["standing_instructions"],
        description=row["standing_description"],
        standing_type=row["standing_type"],
        updated_at=from_db(row["chat_updated_at"]),
        last_run_at=from_db_or_none(row["last_run_at"]),
    )


def _set_clauses(fields: list[tuple[str, Any]]) -> tuple[list[str], list[Any]]:
    """SET clauses for the fields given (Ellipsis = unchanged; None never
    blanks a NOT NULL conversation column)."""
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in fields:
        if isinstance(value, EllipsisType) or (column in _NOT_NULL and value is None):
            continue
        clauses.append(f"{column} = ?")
        params.append(value)
    return clauses, params


def next_cron_run(schedule: str, timezone: str) -> datetime | None:
    """The next run of a cron schedule, as aware UTC; None if it is invalid."""
    try:
        cron = croniter(schedule, utc_now().astimezone(ZoneInfo(timezone)))
        next_run: datetime = cron.get_next(datetime)
        return next_run.astimezone(UTC)
    except Exception as e:  # a bad stored schedule must not break the scheduler
        logger.warning(
            "Failed to calculate next run",
            extra={"schedule": schedule, "timezone": timezone, "error": str(e)},
            exc_info=True,
        )
        return None


def _new_job(
    user_id: str, conv_id: str, schedule: str | None, timezone: str, settings: dict[str, Any]
) -> ScheduledItem:
    enabled = settings["enabled"]
    next_run = next_cron_run(schedule, timezone) if schedule else None
    return ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conv_id,
        kind="recurring",
        text=STANDING_JOB_TEXT,
        end_condition=None,
        schedule=schedule,
        interval_hours=None,
        next_run_at=next_run or NEVER_RUN_AT,
        expires_at=None,
        status="active" if enabled else "paused",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=utc_now(),
        grants=settings["grants"],
        model=settings["model"],
        budget_usd=settings["budget_usd"],
        fresh_context=settings["fresh_context"],
        timezone=timezone,
        paused_reason=None if enabled else "disabled",
    )


class StandingChatMixin:
    """Mixin providing standing chat (agent) operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def create_standing_chat(
        self,
        user_id: str,
        name: str,
        instructions: str | None = None,
        *,
        schedule: str | None = None,
        timezone: str = "UTC",
        grants: list[str] | None = None,
        model: str | None = None,
        budget_usd: float | None = None,
        fresh_context: bool = True,
        enabled: bool = True,
        description: str | None = None,
        standing_type: str | None = None,
    ) -> StandingChat:
        """A new standing chat and its job, written together.

        grants None = all tools (["*"]); [] = only the always-safe tools. The
        first run is the schedule's next slot; no schedule = run on demand.
        """
        if self.get_standing_chat_by_name(user_id, name) is not None:
            raise sqlite3.IntegrityError(f"An agent named {name!r} exists already")
        chat_model = model or Config.DEFAULT_MODEL
        conv_id = str(uuid.uuid4())
        settings = {
            "enabled": enabled,
            "grants": grants if grants is not None else [ALL_GRANTS],
            "model": chat_model,
            "budget_usd": budget_usd,
            "fresh_context": fresh_context,
        }
        job = _new_job(user_id, conv_id, schedule, timezone, settings)
        now = to_db(job.created_at)
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations
                   (id, user_id, title, model, created_at, updated_at, is_agent, job_id,
                    standing_name, standing_instructions, standing_type, standing_description)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (
                    conv_id,
                    user_id,
                    f"Agent: {name}",
                    chat_model,
                    now,
                    now,
                    job.id,
                    name,
                    instructions,
                    standing_type,
                    description,
                ),
            )
            self._execute_with_timing(conn, ITEM_INSERT_SQL, stored_item(job))
            conn.commit()
        logger.info("Standing chat created", extra={"job_id": job.id, "user_id": user_id})
        chat = self.get_standing_chat(job.id, user_id)
        if chat is None:  # just written
            raise RuntimeError(f"Standing chat {job.id} vanished after create")
        return chat

    def get_standing_chat(self, job_id: str, user_id: str) -> StandingChat | None:
        """A standing chat by its job id."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, f"{_SELECT} AND s.id = ? AND s.user_id = ?", (job_id, user_id)
            ).fetchone()
        return _row_to_standing_chat(row) if row else None

    def get_standing_chat_by_name(self, user_id: str, name: str) -> StandingChat | None:
        """A user's standing chat by its name, ignoring case (names are unique that way)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"{_SELECT} AND s.user_id = ? AND lower(c.standing_name) = lower(?)",
                (user_id, name),
            ).fetchone()
        return _row_to_standing_chat(row) if row else None

    def list_standing_chats(self, user_id: str) -> list[StandingChat]:
        """A user's standing chats, newest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn, f"{_SELECT} AND s.user_id = ? ORDER BY s.created_at DESC", (user_id,)
            ).fetchall()
        return [_row_to_standing_chat(row) for row in rows]

    def update_standing_chat(
        self,
        job_id: str,
        user_id: str,
        *,
        name: str | EllipsisType = ...,
        description: str | EllipsisType | None = ...,
        instructions: str | EllipsisType | None = ...,
        schedule: str | EllipsisType | None = ...,
        timezone: str | EllipsisType = ...,
        grants: list[str] | EllipsisType | None = ...,
        enabled: bool | EllipsisType = ...,
        model: str | EllipsisType | None = ...,
        budget_usd: float | EllipsisType | None = ...,
        fresh_context: bool | EllipsisType = ...,
    ) -> StandingChat | None:
        """Change a standing chat (Ellipsis = unchanged; grants None = all).

        A schedule, timezone or enabled change recomputes the next run: the
        schedule's next slot, or never when disabled or unscheduled.
        """
        current = self.get_standing_chat(job_id, user_id)
        if current is None:
            return None
        if isinstance(name, str) and name != current.name:
            clash = self.get_standing_chat_by_name(user_id, name)
            if clash is not None and clash.id != job_id:
                raise sqlite3.IntegrityError(f"An agent named {name!r} exists already")
        conv_updates, conv_params = _set_clauses(
            [
                ("standing_name", name),
                ("title", name if isinstance(name, EllipsisType) else f"Agent: {name}"),
                ("standing_description", description),
                ("standing_instructions", instructions),
                ("model", model),
            ]
        )
        conv_updates.insert(0, "updated_at = ?")
        conv_params.insert(0, to_db(utc_now()))
        job_updates, job_params = self._job_changes(
            current, schedule, timezone, grants, enabled, model, budget_usd, fresh_context
        )
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE conversations SET {', '.join(conv_updates)} "
                "WHERE job_id = ? AND user_id = ?",
                (*conv_params, job_id, user_id),
            )
            if cursor.rowcount == 0:  # deleted meanwhile; release the write lock
                conn.rollback()
                return None
            if job_updates:
                self._execute_with_timing(
                    conn,
                    f"UPDATE scheduled_items SET {', '.join(job_updates)} "
                    "WHERE id = ? AND user_id = ?",
                    (*job_params, job_id, user_id),
                )
            conn.commit()
        return self.get_standing_chat(job_id, user_id)

    def _job_changes(
        self,
        current: StandingChat,
        schedule: str | EllipsisType | None,
        timezone: str | EllipsisType,
        grants: list[str] | EllipsisType | None,
        enabled: bool | EllipsisType,
        model: str | EllipsisType | None,
        budget_usd: float | EllipsisType | None,
        fresh_context: bool | EllipsisType,
    ) -> tuple[list[str], list[Any]]:
        stored_grants = (
            grants
            if isinstance(grants, EllipsisType)
            else json.dumps(grants if grants is not None else [ALL_GRANTS])
        )
        fresh = fresh_context if isinstance(fresh_context, EllipsisType) else int(fresh_context)
        updates, params = _set_clauses(
            [
                ("schedule", schedule),
                ("timezone", timezone),
                ("grants", stored_grants),
                ("model", model),
                ("budget_usd", budget_usd),
                ("fresh_context", fresh),
            ]
        )
        if not isinstance(enabled, EllipsisType):
            updates.extend(_ENABLE_SQL if enabled else _DISABLE_SQL)
        next_run = _rescheduled_next_run(current, schedule, timezone, enabled)
        if not isinstance(next_run, EllipsisType):
            updates.append("next_run_at = ?")
            params.append(to_db(next_run or NEVER_RUN_AT))
        return updates, params

    def delete_standing_chat(self, job_id: str, user_id: str) -> bool:
        """Delete a standing chat: its messages, runs, approvals, notes
        (kv namespace agent:<id>), job and conversation."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT id FROM conversations WHERE job_id = ? AND user_id = ? AND is_agent = 1",
                (job_id, user_id),
            ).fetchone()
            if not row:
                return False
            conv_id = row["id"]
            # Blob cleanup AFTER the commit (a crash before it leaves only
            # harmless orphaned blobs)
            message_ids = [
                r["id"]
                for r in self._execute_with_timing(
                    conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
                ).fetchall()
            ]
            for sql, params in (
                ("DELETE FROM messages WHERE conversation_id = ?", (conv_id,)),
                ("DELETE FROM job_approvals WHERE item_id = ?", (job_id,)),
                ("DELETE FROM job_runs WHERE item_id = ?", (job_id,)),
                (
                    "DELETE FROM kv_store WHERE user_id = ? AND namespace = ?",
                    (user_id, f"agent:{job_id}"),
                ),
                ("DELETE FROM scheduled_items WHERE id = ? AND user_id = ?", (job_id, user_id)),
                ("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)),
            ):
                self._execute_with_timing(conn, sql, params)
            conn.commit()
        if message_ids:
            delete_messages_blobs(message_ids)
        logger.info("Standing chat deleted", extra={"job_id": job_id, "user_id": user_id})
        return True

    def standing_unread_count(self, job_id: str) -> int:
        """Assistant messages in the chat since the user last opened it."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) AS count FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.job_id = ? AND c.is_agent = 1 AND m.role = 'assistant'
                   AND (c.standing_viewed_at IS NULL OR m.created_at > c.standing_viewed_at)""",
                (job_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def mark_standing_viewed(self, job_id: str, user_id: str) -> bool:
        """The user opened the chat: its messages so far are read."""
        with self._pool.get_connection() as conn:
            # messages.created_at's format: the unread count compares as strings
            cursor = self._execute_with_timing(
                conn,
                """UPDATE conversations SET standing_viewed_at = ?
                   WHERE job_id = ? AND user_id = ? AND is_agent = 1""",
                (to_db(utc_now()), job_id, user_id),
            )
            conn.commit()
        return cursor.rowcount > 0


def _rescheduled_next_run(
    current: StandingChat,
    schedule: str | EllipsisType | None,
    timezone: str | EllipsisType,
    enabled: bool | EllipsisType,
) -> datetime | EllipsisType | None:
    """The next run after an update (Ellipsis = leave it; None = never)."""
    if all(isinstance(v, EllipsisType) for v in (schedule, timezone, enabled)):
        return ...
    effective_enabled = current.enabled if isinstance(enabled, EllipsisType) else enabled
    effective_schedule = current.job.schedule if isinstance(schedule, EllipsisType) else schedule
    effective_timezone = current.job.timezone if isinstance(timezone, EllipsisType) else timezone
    if not effective_enabled or not effective_schedule:
        return None
    return next_cron_run(effective_schedule, effective_timezone or "UTC")
