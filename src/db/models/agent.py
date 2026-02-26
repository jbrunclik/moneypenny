"""Autonomous agent database operations mixin.

Contains all methods for Agent entity management including:
- Agent CRUD operations
- Approval request management
- Execution tracking
- Command center data aggregation
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from types import EllipsisType
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import Agent, AgentExecution, ApprovalRequest, Conversation
from src.db.models.helpers import delete_messages_blobs
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentMixin:
    """Mixin providing Agent-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _row_to_agent(self, row: sqlite3.Row) -> Agent:
        """Convert a database row to an Agent object."""
        tool_permissions = None
        if row["tool_permissions"]:
            tool_permissions = json.loads(row["tool_permissions"])

        # Handle budget_limit column (may not exist in older databases)
        budget_limit = None
        if "budget_limit" in row.keys():
            budget_limit = row["budget_limit"]

        return Agent(
            id=row["id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            name=row["name"],
            description=row["description"],
            system_prompt=row["system_prompt"],
            schedule=row["schedule"],
            timezone=row["timezone"] or "UTC",
            enabled=bool(row["enabled"]),
            tool_permissions=tool_permissions,
            model=row["model"] or Config.DEFAULT_MODEL,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_run_at=(
                datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None
            ),
            next_run_at=(
                datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else None
            ),
            last_viewed_at=(
                datetime.fromisoformat(row["last_viewed_at"]) if row["last_viewed_at"] else None
            ),
            budget_limit=budget_limit,
        )

    def _row_to_approval_request(self, row: sqlite3.Row) -> ApprovalRequest:
        """Convert a database row to an ApprovalRequest object."""
        tool_args = None
        if row["tool_args"]:
            tool_args = json.loads(row["tool_args"])

        return ApprovalRequest(
            id=row["id"],
            agent_id=row["agent_id"],
            user_id=row["user_id"],
            tool_name=row["tool_name"],
            tool_args=tool_args,
            description=row["description"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=(
                datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
            ),
            expires_at=(datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None),
        )

    def _row_to_execution(self, row: sqlite3.Row) -> AgentExecution:
        """Convert a database row to an AgentExecution object."""
        return AgentExecution(
            id=row["id"],
            agent_id=row["agent_id"],
            status=row["status"],
            trigger_type=row["trigger_type"],
            triggered_by_agent_id=row["triggered_by_agent_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            error_message=row["error_message"],
        )

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

        Returns:
            The created Agent object
        """
        agent_model = model or Config.DEFAULT_MODEL
        agent_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())
        now = datetime.now()

        logger.debug(
            "Creating agent",
            extra={"user_id": user_id, "agent_id": agent_id, "agent_name": name},
        )

        tool_permissions_json = json.dumps(tool_permissions) if tool_permissions else None

        # Calculate next run time if schedule is provided
        next_run_at = None
        if schedule and enabled:
            next_run_at = self._calculate_next_run(schedule, timezone)

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
                    next_run_at, budget_limit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

            return self._row_to_agent(row)

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

            return self._row_to_agent(row)

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

            return [self._row_to_agent(row) for row in rows]

    def get_agent_unread_count(self, agent_id: str) -> int:
        """Get the number of unread messages for an agent.

        Unread messages are assistant messages created after last_viewed_at.
        Only counts assistant messages (excludes trigger messages which are user role).
        If last_viewed_at is NULL, all assistant messages are considered unread.
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   JOIN autonomous_agents a ON c.agent_id = a.id
                   WHERE a.id = ?
                   AND m.role = 'assistant'
                   AND (a.last_viewed_at IS NULL OR m.created_at > a.last_viewed_at)""",
                (agent_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def update_agent_last_viewed(self, agent_id: str, user_id: str) -> bool:
        """Update the last_viewed_at timestamp for an agent.

        Called when user opens the agent's conversation to mark messages as read.

        Returns:
            True if updated, False if agent not found
        """
        with self._pool.get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET last_viewed_at = ?
                   WHERE id = ? AND user_id = ?""",
                (now, agent_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_last_execution_status(self, agent_id: str) -> str | None:
        """Get the status of the most recent execution for an agent.

        Returns:
            Status string ('completed', 'failed', etc.) or None if no executions
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT status FROM agent_executions
                   WHERE agent_id = ?
                   ORDER BY started_at DESC
                   LIMIT 1""",
                (agent_id,),
            ).fetchone()
            return row["status"] if row else None

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

            return [self._row_to_agent(row) for row in rows]

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
        params: list[Any] = [datetime.now().isoformat()]

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

            # Delete message blobs
            if conv_id:
                message_rows = self._execute_with_timing(
                    conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
                ).fetchall()
                message_ids = [r["id"] for r in message_rows]
                delete_messages_blobs(message_ids)

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

        logger.info("Agent deleted", extra={"agent_id": agent_id, "user_id": user_id})
        return True

    # ============ Scheduling ============

    def calculate_next_run(self, schedule: str, timezone: str) -> datetime | None:
        """Calculate the next run time based on a cron expression.

        Args:
            schedule: Cron expression (e.g., "0 9 * * *")
            timezone: Timezone for interpretation

        Returns:
            Next run datetime in UTC (naive), or None if invalid
        """
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
            cron = croniter(schedule, now)
            next_run: datetime = cron.get_next(datetime)
            # Convert to UTC for storage (naive datetime)
            return next_run.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"Failed to calculate next run: {e}")
            return None

    # Keep alias for backward compatibility within this file
    _calculate_next_run = calculate_next_run

    def get_due_agents(self, now: datetime | None = None) -> list[Agent]:
        """Get agents that are due for execution.

        Args:
            now: Current time in UTC (naive datetime). If None, uses current UTC time.

        Returns:
            Enabled agents where next_run_at <= now.
        """
        if now is None:
            # Use UTC to match how next_run_at is stored
            from datetime import UTC

            now = datetime.now(UTC).replace(tzinfo=None)

        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM autonomous_agents
                   WHERE enabled = 1
                   AND next_run_at IS NOT NULL
                   AND next_run_at <= ?
                   ORDER BY next_run_at ASC""",
                (now.isoformat(),),
            ).fetchall()

            return [self._row_to_agent(row) for row in rows]

    def update_agent_last_run(self, agent_id: str) -> None:
        """Update an agent's last_run_at and recalculate next_run_at.

        Only schedules the next run if the agent is still enabled.
        """
        now = datetime.now()

        with self._pool.get_connection() as conn:
            # Get the agent's schedule, timezone, and enabled status
            row = self._execute_with_timing(
                conn,
                "SELECT schedule, timezone, enabled FROM autonomous_agents WHERE id = ?",
                (agent_id,),
            ).fetchone()

            if not row:
                return

            next_run_at = None
            # Only calculate next run if agent is enabled and has a schedule
            if row["enabled"] and row["schedule"]:
                next_run_at = self._calculate_next_run(row["schedule"], row["timezone"] or "UTC")

            self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET last_run_at = ?, next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    now.isoformat(),
                    next_run_at.isoformat() if next_run_at else None,
                    now.isoformat(),
                    agent_id,
                ),
            )
            conn.commit()

    def update_agent_next_run(self, agent_id: str, next_run_at: datetime) -> None:
        """Update an agent's next_run_at directly.

        Used by the scheduler when manually setting the next run time.
        """
        now = datetime.now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE autonomous_agents
                   SET next_run_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    next_run_at.isoformat(),
                    now.isoformat(),
                    agent_id,
                ),
            )
            conn.commit()

    # ============ Approval Requests ============

    def create_approval_request(
        self,
        agent_id: str,
        user_id: str,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        description: str,
    ) -> ApprovalRequest:
        """Create a new approval request for a dangerous operation.

        The request will expire after AGENT_APPROVAL_TTL_HOURS (default: 24 hours).
        """
        request_id = str(uuid.uuid4())
        now = datetime.now()
        expires_at = now + timedelta(hours=Config.AGENT_APPROVAL_TTL_HOURS)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO agent_approval_requests
                   (id, agent_id, user_id, tool_name, tool_args, description, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    request_id,
                    agent_id,
                    user_id,
                    tool_name,
                    json.dumps(tool_args) if tool_args else None,
                    description,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()

        logger.info(
            "Approval request created",
            extra={
                "request_id": request_id,
                "agent_id": agent_id,
                "tool": tool_name,
                "expires_at": expires_at.isoformat(),
            },
        )

        return ApprovalRequest(
            id=request_id,
            agent_id=agent_id,
            user_id=user_id,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
            status="pending",
            created_at=now,
            resolved_at=None,
            expires_at=expires_at,
        )

    def get_approval_request(self, request_id: str, user_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM agent_approval_requests WHERE id = ? AND user_id = ?",
                (request_id, user_id),
            ).fetchone()

            if not row:
                return None

            return self._row_to_approval_request(row)

    def get_pending_approvals(self, user_id: str) -> list[ApprovalRequest]:
        """Get all pending (non-expired) approval requests for a user."""
        now = datetime.now()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_approval_requests
                   WHERE user_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY created_at DESC""",
                (user_id, now.isoformat()),
            ).fetchall()

            return [self._row_to_approval_request(row) for row in rows]

    def get_pending_approval_for_agent(self, agent_id: str) -> ApprovalRequest | None:
        """Get the pending (non-expired) approval request for an agent (if any)."""
        now = datetime.now()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_approval_requests
                   WHERE agent_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (agent_id, now.isoformat()),
            ).fetchone()

            if not row:
                return None

            return self._row_to_approval_request(row)

    def has_pending_approval(self, agent_id: str) -> bool:
        """Check if an agent has a pending (non-expired) approval request."""
        now = datetime.now()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_approval_requests
                   WHERE agent_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (agent_id, now.isoformat()),
            ).fetchone()

            return row is not None

    def resolve_approval(
        self, request_id: str, user_id: str, approved: bool
    ) -> ApprovalRequest | None:
        """Resolve an approval request (approve or reject).

        Args:
            request_id: The request ID
            user_id: The user ID (for authorization)
            approved: True to approve, False to reject

        Returns:
            Updated ApprovalRequest or None if not found
        """
        now = datetime.now()
        status = "approved" if approved else "rejected"

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE agent_approval_requests
                   SET status = ?, resolved_at = ?
                   WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (status, now.isoformat(), request_id, user_id),
            )

            if cursor.rowcount == 0:
                return None

            conn.commit()

        logger.info(
            "Approval request resolved",
            extra={"request_id": request_id, "status": status},
        )

        return self.get_approval_request(request_id, user_id)

    # ============ Execution Tracking ============

    def create_execution(
        self,
        agent_id: str,
        trigger_type: str,
        triggered_by_agent_id: str | None = None,
    ) -> AgentExecution:
        """Create a new execution record."""
        execution_id = str(uuid.uuid4())
        now = datetime.now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO agent_executions
                   (id, agent_id, status, trigger_type, triggered_by_agent_id, started_at)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (execution_id, agent_id, trigger_type, triggered_by_agent_id, now.isoformat()),
            )
            conn.commit()

        return AgentExecution(
            id=execution_id,
            agent_id=agent_id,
            status="running",
            trigger_type=trigger_type,
            triggered_by_agent_id=triggered_by_agent_id,
            started_at=now,
            completed_at=None,
            error_message=None,
        )

    def update_execution(
        self,
        execution_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update an execution's status."""
        now = datetime.now()

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = ?, completed_at = ?, error_message = ?
                   WHERE id = ?""",
                (status, now.isoformat(), error_message, execution_id),
            )
            conn.commit()

    def get_agent_executions(self, agent_id: str, limit: int = 20) -> list[AgentExecution]:
        """Get recent executions for an agent."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_executions
                   WHERE agent_id = ?
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (agent_id, limit),
            ).fetchall()

            return [self._row_to_execution(row) for row in rows]

    def has_running_execution(self, agent_id: str) -> bool:
        """Check if an agent has a currently running execution.

        Used to prevent overlapping executions of the same agent.
        Ignores executions older than AGENT_EXECUTION_TIMEOUT_MINUTES to prevent
        permanently locked agents due to stuck executions.
        """
        # Calculate the cutoff time (executions older than this are considered stuck)
        cutoff = datetime.now() - timedelta(minutes=Config.AGENT_EXECUTION_TIMEOUT_MINUTES)

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_executions
                   WHERE agent_id = ? AND status = 'running'
                   AND started_at > ?
                   LIMIT 1""",
                (agent_id, cutoff.isoformat()),
            ).fetchone()

            return row is not None

    def is_in_cooldown(self, agent_id: str) -> bool:
        """Check if an agent is within its execution cooldown period.

        Used to prevent spamming manual runs. Returns True if the agent
        completed an execution within AGENT_EXECUTION_COOLDOWN_SECONDS.
        """
        # Calculate the cooldown cutoff time
        cutoff = datetime.now() - timedelta(seconds=Config.AGENT_EXECUTION_COOLDOWN_SECONDS)

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_executions
                   WHERE agent_id = ? AND completed_at IS NOT NULL
                   AND completed_at > ?
                   LIMIT 1""",
                (agent_id, cutoff.isoformat()),
            ).fetchone()

            return row is not None

    def get_recent_executions(self, user_id: str, limit: int = 20) -> list[AgentExecution]:
        """Get recent executions across all agents for a user."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT e.* FROM agent_executions e
                   JOIN autonomous_agents a ON e.agent_id = a.id
                   WHERE a.user_id = ?
                   ORDER BY e.started_at DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()

            return [self._row_to_execution(row) for row in rows]

    def cleanup_zombie_executions(self) -> int:
        """Clean up executions stuck in 'running' or 'waiting_approval' status.

        Marks executions as 'failed' if they've been stuck for longer than
        AGENT_EXECUTION_TIMEOUT_MINUTES. This prevents permanently locked agents
        due to crashed executions.

        Returns:
            Number of zombie executions cleaned up.
        """
        cutoff = datetime.now() - timedelta(minutes=Config.AGENT_EXECUTION_TIMEOUT_MINUTES)

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE agent_executions
                   SET status = 'failed',
                       completed_at = ?,
                       error_message = 'Execution timed out (zombie cleanup)'
                   WHERE status IN ('running', 'waiting_approval')
                   AND started_at < ?""",
                (datetime.now().isoformat(), cutoff.isoformat()),
            )
            conn.commit()

            return cursor.rowcount

    # ============ Command Center ============

    def get_command_center_data(self, user_id: str) -> dict[str, Any]:
        """Get aggregated data for the command center dashboard.

        Returns:
            Dictionary with:
            - agents: List of agents with unread counts and pending status
            - pending_approvals: List of pending approval requests
            - recent_executions: List of recent executions
            - total_unread: Total unread messages across all agents
            - agents_waiting: Number of agents blocked on approval
        """
        with self._pool.get_connection() as conn:
            # Get agents with unread counts (assistant messages since last_viewed_at)
            # Also check for pending (non-expired) approvals and recent failed executions
            now = datetime.now()
            agent_rows = self._execute_with_timing(
                conn,
                """SELECT a.*,
                   (SELECT COUNT(*) FROM messages m
                    JOIN conversations c ON m.conversation_id = c.id
                    WHERE c.agent_id = a.id
                    AND m.role = 'assistant'
                    AND (a.last_viewed_at IS NULL OR m.created_at > a.last_viewed_at)
                   ) as unread_count,
                   (SELECT 1 FROM agent_approval_requests r
                    WHERE r.agent_id = a.id AND r.status = 'pending'
                    AND (r.expires_at IS NULL OR r.expires_at > ?)
                    LIMIT 1
                   ) as has_pending,
                   (SELECT status FROM agent_executions e
                    WHERE e.agent_id = a.id
                    ORDER BY e.started_at DESC
                    LIMIT 1
                   ) as last_execution_status
                   FROM autonomous_agents a
                   WHERE a.user_id = ?
                   ORDER BY a.created_at DESC""",
                (now.isoformat(), user_id),
            ).fetchall()

            agents = []
            total_unread = 0
            agents_waiting = 0
            agents_with_errors = 0

            for row in agent_rows:
                agent = self._row_to_agent(row)
                unread = int(row["unread_count"] or 0)
                has_pending = bool(row["has_pending"])
                last_status = row["last_execution_status"]
                has_error = last_status == "failed"

                agents.append(
                    {
                        "agent": agent,
                        "unread_count": unread,
                        "has_pending_approval": has_pending,
                        "has_error": has_error,
                        "last_execution_status": last_status,
                    }
                )

                total_unread += unread
                if has_pending:
                    agents_waiting += 1
                if has_error:
                    agents_with_errors += 1

            # Get pending (non-expired) approvals with agent names
            approval_rows = self._execute_with_timing(
                conn,
                """SELECT r.*, a.name as agent_name
                   FROM agent_approval_requests r
                   JOIN autonomous_agents a ON r.agent_id = a.id
                   WHERE r.user_id = ? AND r.status = 'pending'
                   AND (r.expires_at IS NULL OR r.expires_at > ?)
                   ORDER BY r.created_at DESC""",
                (user_id, now.isoformat()),
            ).fetchall()

            pending_approvals = []
            for row in approval_rows:
                approval = self._row_to_approval_request(row)
                pending_approvals.append(
                    {
                        "approval": approval,
                        "agent_name": row["agent_name"],
                    }
                )

            # Get recent executions
            recent_executions = self.get_recent_executions(user_id, limit=10)

            return {
                "agents": agents,
                "pending_approvals": pending_approvals,
                "recent_executions": recent_executions,
                "total_unread": total_unread,
                "agents_waiting": agents_waiting,
                "agents_with_errors": agents_with_errors,
            }

    def get_agent_conversation(self, agent_id: str, user_id: str) -> Conversation | None:
        """Get the dedicated conversation for an agent."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT c.* FROM conversations c
                   JOIN autonomous_agents a ON c.id = a.conversation_id
                   WHERE a.id = ? AND a.user_id = ?""",
                (agent_id, user_id),
            ).fetchone()

            if not row:
                return None

            # Import here to avoid circular imports

            # Use the existing _row_to_conversation method pattern
            last_reset = None
            if "last_reset" in row.keys():
                last_reset = (
                    datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None
                )

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                model=row["model"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                is_planning=bool(row["is_planning"]) if row["is_planning"] else False,
                last_reset=last_reset,
                is_agent=bool(row["is_agent"]) if row["is_agent"] else False,
                agent_id=row["agent_id"],
            )

    # ============ Budget Tracking ============

    def get_agent_daily_spending(self, agent_id: str) -> float:
        """Get the total spending for an agent today (in USD).

        Calculates the sum of all costs for messages in the agent's conversation
        created on the current day (UTC).

        Returns:
            Total spending in USD for today.
        """
        today = datetime.now().date()
        today_start = datetime(today.year, today.month, today.day, 0, 0, 0)

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COALESCE(SUM(mc.cost_usd), 0) as total
                   FROM message_costs mc
                   JOIN messages m ON mc.message_id = m.id
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.agent_id = ?
                   AND mc.created_at >= ?""",
                (agent_id, today_start.isoformat()),
            ).fetchone()

            return float(row["total"]) if row else 0.0

    def is_agent_over_budget(self, agent_id: str, budget_limit: float | None) -> bool:
        """Check if an agent has exceeded its daily budget.

        Args:
            agent_id: The agent ID
            budget_limit: Daily budget limit in USD (None = unlimited)

        Returns:
            True if over budget, False otherwise.
        """
        if budget_limit is None or budget_limit <= 0:
            return False

        daily_spending = self.get_agent_daily_spending(agent_id)
        return daily_spending >= budget_limit

    # ============ Conversation Compaction ============

    def get_agent_message_count(self, agent_id: str) -> int:
        """Get the number of messages in an agent's conversation."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM messages m
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.agent_id = ?""",
                (agent_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def compact_agent_conversation(
        self,
        agent_id: str,
        summary: str,
        keep_recent: int = 10,
    ) -> int:
        """Compact an agent's conversation by replacing old messages with a summary.

        Keeps the most recent `keep_recent` messages and replaces all older messages
        with a single summary message.

        Args:
            agent_id: The agent ID
            summary: Summary text to replace old messages with
            keep_recent: Number of recent messages to keep

        Returns:
            Number of messages deleted.
        """
        with self._pool.get_connection() as conn:
            # Get the conversation ID
            conv_row = self._execute_with_timing(
                conn,
                "SELECT conversation_id FROM autonomous_agents WHERE id = ?",
                (agent_id,),
            ).fetchone()

            if not conv_row or not conv_row["conversation_id"]:
                return 0

            conv_id = conv_row["conversation_id"]

            # Get the IDs of messages to keep (most recent)
            keep_rows = self._execute_with_timing(
                conn,
                """SELECT id FROM messages
                   WHERE conversation_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (conv_id, keep_recent),
            ).fetchall()

            keep_ids = {row["id"] for row in keep_rows}

            # Get all message IDs to delete
            all_rows = self._execute_with_timing(
                conn,
                "SELECT id FROM messages WHERE conversation_id = ?",
                (conv_id,),
            ).fetchall()

            delete_ids = [row["id"] for row in all_rows if row["id"] not in keep_ids]

            if not delete_ids:
                return 0

            # Delete old message blobs
            delete_messages_blobs(delete_ids)

            # Delete old messages
            placeholders = ",".join("?" * len(delete_ids))
            self._execute_with_timing(
                conn,
                f"DELETE FROM messages WHERE id IN ({placeholders})",
                tuple(delete_ids),
            )

            # Insert summary message at the beginning (as system context)
            now = datetime.now()
            summary_id = str(uuid.uuid4())
            self._execute_with_timing(
                conn,
                """INSERT INTO messages (id, conversation_id, role, content, created_at)
                   VALUES (?, ?, 'user', ?, ?)""",
                (
                    summary_id,
                    conv_id,
                    f"[Previous conversation summary]\n\n{summary}",
                    now.isoformat(),
                ),
            )

            conn.commit()

            logger.info(
                "Agent conversation compacted",
                extra={
                    "agent_id": agent_id,
                    "messages_deleted": len(delete_ids),
                    "messages_kept": len(keep_ids),
                },
            )

            return len(delete_ids)
