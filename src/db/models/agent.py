"""Autonomous agent CRUD database operations mixin.

Related agent operations live in sibling mixins: agent_schedule (cron
math, due agents), agent_approvals, agent_executions, agent_conversation
(dedicated conversation, unread state, compaction) and agent_stats
(command center, observability, spend).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from types import EllipsisType
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.agent_rows import row_to_agent
from src.db.models.dataclasses import Agent, ScheduledItem
from src.db.models.helpers import delete_messages_blobs
from src.db.models.scheduled_items import (
    ITEM_INSERT_SQL,
    NEVER_RUN_AT,
    STANDING_JOB_TEXT,
    stored_item,
)
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

ALL_GRANTS = "*"


def _with_write_levels(new: list[str] | None, current: list[str] | None) -> list[str]:
    """The grants to store: the agent editor sends tool names only, so the
    write levels of tools still granted are kept (never silently dropped)."""
    if new is None:
        return [ALL_GRANTS]
    kept = [g for g in current or [] if g.endswith(":write") and g.removesuffix(":write") in new]
    return list(dict.fromkeys([*new, *kept]))


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


class AgentMixin:
    """Mixin providing Agent CRUD database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    if TYPE_CHECKING:

        def calculate_next_run(self, schedule: str, timezone: str) -> datetime | None:
            """Defined in AgentScheduleMixin."""

    # ============ Agent CRUD ============

    def create_agent(
        self,
        user_id: str,
        name: str,
        description: str | None = None,
        system_prompt: str | None = None,
        schedule: str | None = None,
        timezone: str = "UTC",
        tool_permissions: list[str] | None = None,
        enabled: bool = True,
        model: str | None = None,
        budget_limit: float | None = None,
        fresh_context: bool = True,
        system_type: str | None = None,
    ) -> Agent:
        """Create a new autonomous agent with a dedicated conversation.

        Args:
            user_id: The owner's user ID
            name: Agent name (unique per user)
            description: Optional description
            system_prompt: Agent's goals and instructions
            schedule: Cron expression for scheduling
            timezone: Timezone for cron interpretation
            tool_permissions: List of allowed tool names
            enabled: Whether agent is active
            model: LLM model to use (defaults to Config.DEFAULT_MODEL)
            budget_limit: Monthly budget limit in USD (None = unlimited)
            fresh_context: Run each execution without prior conversation
                history (default True - most agents' runs are independent)

        Returns:
            The created Agent object
        """
        if self.get_agent_by_name(user_id, name) is not None:
            raise sqlite3.IntegrityError(f"An agent named {name!r} exists already")
        agent_model = model or Config.DEFAULT_MODEL
        job_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        now = utc_now()
        next_run_at = self.calculate_next_run(schedule, timezone) if schedule else None
        job = ScheduledItem(
            id=job_id,
            user_id=user_id,
            conversation_id=conv_id,
            kind="recurring",
            text=STANDING_JOB_TEXT,
            end_condition=None,
            schedule=schedule,
            interval_hours=None,
            next_run_at=next_run_at or NEVER_RUN_AT,
            expires_at=None,
            status="active" if enabled else "paused",
            last_result=None,
            quiet_runs=0,
            failures=0,
            created_at=now,
            # "is not None": [] means "only the safe tools", None "all tools"
            grants=tool_permissions if tool_permissions is not None else [ALL_GRANTS],
            model=agent_model,
            budget_usd=budget_limit,
            fresh_context=fresh_context,
            timezone=timezone,
            paused_reason=None if enabled else "disabled",
        )
        with self._pool.get_connection() as conn:
            # The standing chat (its settings) and its job, together
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations
                   (id, user_id, title, model, created_at, updated_at, is_agent, agent_id,
                    standing_name, standing_instructions, standing_type, standing_description)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (
                    conv_id,
                    user_id,
                    f"Agent: {name}",
                    agent_model,
                    to_db(now),
                    to_db(now),
                    job_id,
                    name,
                    system_prompt,
                    system_type,
                    description,
                ),
            )
            self._execute_with_timing(conn, ITEM_INSERT_SQL, stored_item(job))
            conn.commit()

        logger.info("Agent created", extra={"agent_id": job_id, "user_id": user_id})
        agent = self.get_agent(job_id, user_id)
        if agent is None:  # just written in this transaction
            raise RuntimeError(f"Agent {job_id} vanished after create")
        return agent

    def get_agent(self, agent_id: str, user_id: str) -> Agent | None:
        """Get an agent by ID and user ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM autonomous_agents WHERE id = ? AND user_id = ?",
                (agent_id, user_id),
            ).fetchone()

            if not row:
                return None

            return row_to_agent(row)

    def get_agent_by_name(self, user_id: str, name: str) -> Agent | None:
        """Get an agent by name for a user."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM autonomous_agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()

            if not row:
                return None

            return row_to_agent(row)

    def update_agent(
        self,
        agent_id: str,
        user_id: str,
        name: str | EllipsisType | None = ...,
        description: str | EllipsisType | None = ...,
        system_prompt: str | EllipsisType | None = ...,
        schedule: str | EllipsisType | None = ...,
        timezone: str | EllipsisType | None = ...,
        tool_permissions: list[str] | EllipsisType | None = ...,
        enabled: bool | EllipsisType | None = ...,
        model: str | EllipsisType | None = ...,
        budget_limit: float | EllipsisType | None = ...,
        fresh_context: bool | EllipsisType | None = ...,
    ) -> Agent | None:
        """Update an agent's configuration.

        Args:
            agent_id: The agent ID
            user_id: The owner's user ID
            Other args: Fields to update (Ellipsis = no change)

        Returns:
            Updated Agent or None if not found

        Note:
            When schedule, timezone, or enabled changes, next_run_at is recalculated:
            - If disabled, next_run_at is cleared
            - If enabled with a schedule, next_run_at is computed from the new schedule/timezone
        """
        # First, get the current agent state for schedule recalculation
        current_agent = self.get_agent(agent_id, user_id)
        if not current_agent:
            return None
        if isinstance(name, str) and name != current_agent.name:
            clash = self.get_agent_by_name(user_id, name)
            if clash is not None and clash.id != agent_id:
                raise sqlite3.IntegrityError(f"An agent named {name!r} exists already")

        conv_updates, conv_params = _set_clauses(
            [
                ("standing_name", name),
                (
                    "title",
                    name if isinstance(name, EllipsisType) or name is None else f"Agent: {name}",
                ),
                ("standing_description", description),
                ("standing_instructions", system_prompt),
                ("model", model),
            ]
        )
        conv_updates.insert(0, "updated_at = ?")
        conv_params.insert(0, to_db(utc_now()))
        grants = (
            ...
            if isinstance(tool_permissions, EllipsisType)
            else json.dumps(_with_write_levels(tool_permissions, current_agent.tool_permissions))
        )
        fresh = (
            fresh_context if isinstance(fresh_context, EllipsisType) else int(bool(fresh_context))
        )
        job_updates, job_params = _set_clauses(
            [
                ("schedule", schedule),
                ("timezone", timezone),
                ("grants", grants),
                ("model", model),
                ("budget_usd", budget_limit),
                ("fresh_context", fresh),
            ]
        )
        if not isinstance(enabled, EllipsisType):
            job_updates.extend(_ENABLE_SQL if enabled else _DISABLE_SQL)
        next_run_at = self._rescheduled_next_run(current_agent, schedule, timezone, enabled)
        if not isinstance(next_run_at, EllipsisType):
            job_updates.append("next_run_at = ?")
            job_params.append(to_db(next_run_at or NEVER_RUN_AT))

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE conversations SET {', '.join(conv_updates)} WHERE agent_id = ? AND user_id = ?",
                (*conv_params, agent_id, user_id),
            )
            if cursor.rowcount == 0:  # deleted meanwhile; release the write lock
                conn.rollback()
                return None
            if job_updates:
                self._execute_with_timing(
                    conn,
                    f"UPDATE scheduled_items SET {', '.join(job_updates)} WHERE id = ? AND user_id = ?",
                    (*job_params, agent_id, user_id),
                )
            conn.commit()

        return self.get_agent(agent_id, user_id)

    def _rescheduled_next_run(
        self,
        current_agent: Agent,
        schedule: str | EllipsisType | None,
        timezone: str | EllipsisType | None,
        enabled: bool | EllipsisType | None,
    ) -> datetime | EllipsisType | None:
        """The next_run_at after an update (Ellipsis = leave it as is).

        Recalculated when schedule, timezone or enabled changes: cleared if
        disabled or unscheduled, else computed from the effective values.
        """
        # Determine if we need to recalculate next_run_at
        needs_schedule_update = (
            not isinstance(schedule, EllipsisType)
            or not isinstance(timezone, EllipsisType)
            or not isinstance(enabled, EllipsisType)
        )
        if not needs_schedule_update:
            return ...

        # Determine the effective values after update
        effective_enabled = (
            enabled if not isinstance(enabled, EllipsisType) else current_agent.enabled
        )
        effective_schedule = (
            schedule if not isinstance(schedule, EllipsisType) else current_agent.schedule
        )
        effective_timezone = (
            timezone if not isinstance(timezone, EllipsisType) else current_agent.timezone
        )

        if not effective_enabled or not effective_schedule:
            # Clear next_run_at if disabled or no schedule
            return None
        # Recalculate next_run_at
        return self.calculate_next_run(effective_schedule, effective_timezone or "UTC")

    def delete_agent(self, agent_id: str, user_id: str) -> bool:
        """Delete an agent and its associated conversation.

        Also deletes:
        - All messages in the agent's conversation
        - All approval requests for this agent
        - All execution records for this agent
        """
        with self._pool.get_connection() as conn:
            # Get the conversation ID
            row = self._execute_with_timing(
                conn,
                "SELECT conversation_id FROM autonomous_agents WHERE id = ? AND user_id = ?",
                (agent_id, user_id),
            ).fetchone()

            if not row:
                return False

            conv_id = row["conversation_id"]

            # Collect message ids for blob cleanup AFTER the commit (a crash
            # before blob cleanup leaves only harmless orphaned blobs)
            message_ids: list[str] = []
            if conv_id:
                message_rows = self._execute_with_timing(
                    conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
                ).fetchall()
                message_ids = [r["id"] for r in message_rows]

                # Delete messages
                self._execute_with_timing(
                    conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
                )

            # Delete approval requests
            self._execute_with_timing(
                conn, "DELETE FROM agent_approval_requests WHERE agent_id = ?", (agent_id,)
            )

            # Delete executions
            self._execute_with_timing(
                conn, "DELETE FROM agent_executions WHERE agent_id = ?", (agent_id,)
            )

            # Delete K/V store data for this agent's namespace
            self._execute_with_timing(
                conn,
                "DELETE FROM kv_store WHERE user_id = ? AND namespace = ?",
                (user_id, f"agent:{agent_id}"),
            )

            # Delete the agent's standing job (the chat goes below)
            self._execute_with_timing(
                conn,
                "DELETE FROM scheduled_items WHERE id = ? AND user_id = ?",
                (agent_id, user_id),
            )

            # Delete the conversation
            if conv_id:
                self._execute_with_timing(
                    conn,
                    "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                    (conv_id, user_id),
                )

            conn.commit()

        if message_ids:
            delete_messages_blobs(message_ids)

        logger.info("Agent deleted", extra={"agent_id": agent_id, "user_id": user_id})
        return True
