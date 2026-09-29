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
from src.db.models.dataclasses import Agent
from src.db.models.helpers import delete_messages_blobs
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


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
        agent_model = model or Config.DEFAULT_MODEL
        agent_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        now = utcnow_naive()

        logger.debug(
            "Creating agent",
            extra={"user_id": user_id, "agent_id": agent_id, "agent_name": name},
        )

        tool_permissions_json = json.dumps(tool_permissions) if tool_permissions else None

        # Calculate next run time if schedule is provided
        next_run_at = None
        if schedule and enabled:
            next_run_at = self.calculate_next_run(schedule, timezone)

        with self._pool.get_connection() as conn:
            # Create the dedicated conversation first (use agent's model)
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations
                   (id, user_id, title, model, created_at, updated_at, is_agent, agent_id)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    conv_id,
                    user_id,
                    f"Agent: {name}",
                    agent_model,
                    now.isoformat(),
                    now.isoformat(),
                    agent_id,
                ),
            )

            # Create the agent
            self._execute_with_timing(
                conn,
                """INSERT INTO autonomous_agents
                   (id, user_id, conversation_id, name, description, system_prompt,
                    schedule, timezone, enabled, tool_permissions, model, created_at, updated_at,
                    next_run_at, budget_limit, fresh_context, system_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    user_id,
                    conv_id,
                    name,
                    description,
                    system_prompt,
                    schedule,
                    timezone,
                    1 if enabled else 0,
                    tool_permissions_json,
                    agent_model,
                    now.isoformat(),
                    now.isoformat(),
                    next_run_at.isoformat() if next_run_at else None,
                    budget_limit,
                    1 if fresh_context else 0,
                    system_type,
                ),
            )
            conn.commit()

        logger.info("Agent created", extra={"agent_id": agent_id, "user_id": user_id})

        return Agent(
            id=agent_id,
            user_id=user_id,
            conversation_id=conv_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            schedule=schedule,
            timezone=timezone,
            enabled=enabled,
            tool_permissions=tool_permissions,
            model=agent_model,
            created_at=now,
            updated_at=now,
            last_run_at=None,
            next_run_at=next_run_at,
            budget_limit=budget_limit,
            fresh_context=fresh_context,
            system_type=system_type,
        )

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

    def list_agents(self, user_id: str) -> list[Agent]:
        """List all agents for a user."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM autonomous_agents
                   WHERE user_id = ?
                   ORDER BY created_at DESC""",
                (user_id,),
            ).fetchall()

            return [row_to_agent(row) for row in rows]

    def list_all_scheduled_agents(self) -> list[Agent]:
        """List all enabled agents with schedules (for scheduler).

        This is used by the dev scheduler to evaluate all agents across all users.
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM autonomous_agents
                   WHERE enabled = 1 AND schedule IS NOT NULL
                   ORDER BY next_run_at ASC""",
                (),
            ).fetchall()

            return [row_to_agent(row) for row in rows]

    def update_agent(
        self,
        agent_id: str,
        user_id: str,
        name: str | None | EllipsisType = ...,
        description: str | None | EllipsisType = ...,
        system_prompt: str | None | EllipsisType = ...,
        schedule: str | None | EllipsisType = ...,
        timezone: str | None | EllipsisType = ...,
        tool_permissions: list[str] | None | EllipsisType = ...,
        enabled: bool | None | EllipsisType = ...,
        model: str | None | EllipsisType = ...,
        budget_limit: float | None | EllipsisType = ...,
        fresh_context: bool | None | EllipsisType = ...,
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

        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [utcnow_naive().isoformat()]

        if not isinstance(name, EllipsisType):
            updates.append("name = ?")
            params.append(name)
        if not isinstance(description, EllipsisType):
            updates.append("description = ?")
            params.append(description)
        if not isinstance(system_prompt, EllipsisType):
            updates.append("system_prompt = ?")
            params.append(system_prompt)
        if not isinstance(schedule, EllipsisType):
            updates.append("schedule = ?")
            params.append(schedule)
        if not isinstance(timezone, EllipsisType):
            updates.append("timezone = ?")
            params.append(timezone)
        if not isinstance(tool_permissions, EllipsisType):
            updates.append("tool_permissions = ?")
            params.append(json.dumps(tool_permissions) if tool_permissions is not None else None)
        if not isinstance(enabled, EllipsisType):
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if not isinstance(fresh_context, EllipsisType):
            updates.append("fresh_context = ?")
            params.append(1 if fresh_context else 0)
        if not isinstance(model, EllipsisType):
            updates.append("model = ?")
            params.append(model)
        if not isinstance(budget_limit, EllipsisType):
            updates.append("budget_limit = ?")
            params.append(budget_limit)

        # Determine if we need to recalculate next_run_at
        needs_schedule_update = (
            not isinstance(schedule, EllipsisType)
            or not isinstance(timezone, EllipsisType)
            or not isinstance(enabled, EllipsisType)
        )

        if needs_schedule_update:
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
                updates.append("next_run_at = ?")
                params.append(None)
            else:
                # Recalculate next_run_at
                next_run = self.calculate_next_run(effective_schedule, effective_timezone or "UTC")
                updates.append("next_run_at = ?")
                params.append(next_run.isoformat() if next_run else None)

        params.extend([agent_id, user_id])

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE autonomous_agents SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                tuple(params),
            )

            if cursor.rowcount == 0:
                return None

            # Update conversation title if name changed
            if not isinstance(name, EllipsisType) and name is not None:
                self._execute_with_timing(
                    conn,
                    """UPDATE conversations SET title = ?
                       WHERE agent_id = ? AND user_id = ?""",
                    (f"Agent: {name}", agent_id, user_id),
                )

            # Update conversation model if agent model changed
            if not isinstance(model, EllipsisType) and model is not None:
                self._execute_with_timing(
                    conn,
                    """UPDATE conversations SET model = ?
                       WHERE agent_id = ? AND user_id = ?""",
                    (model, agent_id, user_id),
                )

            conn.commit()

            # Fetch and return the updated agent
            return self.get_agent(agent_id, user_id)

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

            # Delete the agent
            self._execute_with_timing(
                conn,
                "DELETE FROM autonomous_agents WHERE id = ? AND user_id = ?",
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
