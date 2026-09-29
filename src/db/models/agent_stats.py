"""Agent observability database operations mixin.

Command center aggregation, per-agent run/cost stats and budget spend.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.agent_rows import row_to_agent, row_to_approval_request
from src.db.models.dataclasses import AgentExecution
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentStatsMixin:
    """Mixin providing agent observability and spend aggregation."""

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

        def get_recent_executions(self, user_id: str, limit: int = 20) -> list[AgentExecution]:
            """Defined in AgentExecutionMixin."""

    def list_agents_with_status(self, user_id: str) -> list[dict[str, Any]]:
        """List agents with unread/pending/last-execution status in one query.

        Replaces the per-agent has_pending_approval + get_agent_unread_count +
        get_last_execution_status loop (3 queries per agent) in the listing
        route (Q1).
        """
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
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

            result: list[dict[str, Any]] = []
            for row in agent_rows:
                last_status = row["last_execution_status"]
                result.append(
                    {
                        "agent": row_to_agent(row),
                        "unread_count": int(row["unread_count"] or 0),
                        "has_pending_approval": bool(row["has_pending"]),
                        "has_error": last_status == "failed",
                        "last_execution_status": last_status,
                    }
                )
            return result

    def get_agent_observability_stats(self, user_id: str, days: int = 7) -> dict[str, Any]:
        """Per-agent run and cost aggregates over a trailing window.

        Returns {"days", "per_agent": {agent_id: {runs, completed, failed,
        waiting_approval, cost_usd, input_tokens, output_tokens}}}.

        Clock note: executions use UTC-naive timestamps while
        message_costs are local-naive - each filter uses its table's
        clock; the up-to-2h skew is irrelevant for day-scale windows.
        """
        exec_since = (utcnow_naive() - timedelta(days=days)).isoformat()
        cost_since = (datetime.now() - timedelta(days=days)).isoformat()

        per_agent: dict[str, dict[str, Any]] = {}

        def bucket(agent_id: str) -> dict[str, Any]:
            return per_agent.setdefault(
                agent_id,
                {
                    "runs": 0,
                    "completed": 0,
                    "failed": 0,
                    "waiting_approval": 0,
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )

        with self._pool.get_connection() as conn:
            exec_rows = self._execute_with_timing(
                conn,
                """SELECT e.agent_id, e.status, COUNT(*) as cnt
                   FROM agent_executions e
                   JOIN autonomous_agents a ON e.agent_id = a.id
                   WHERE a.user_id = ? AND e.started_at >= ?
                   GROUP BY e.agent_id, e.status""",
                (user_id, exec_since),
            ).fetchall()
            cost_rows = self._execute_with_timing(
                conn,
                """SELECT c.agent_id,
                          COALESCE(SUM(mc.cost_usd), 0) as cost_usd,
                          COALESCE(SUM(mc.input_tokens), 0) as input_tokens,
                          COALESCE(SUM(mc.output_tokens), 0) as output_tokens
                   FROM message_costs mc
                   JOIN conversations c ON mc.conversation_id = c.id
                   WHERE c.user_id = ? AND c.agent_id IS NOT NULL
                     AND mc.created_at >= ?
                   GROUP BY c.agent_id""",
                (user_id, cost_since),
            ).fetchall()

        for row in exec_rows:
            stats = bucket(row["agent_id"])
            count = int(row["cnt"])
            stats["runs"] += count
            status = row["status"]
            if status in ("completed", "failed", "waiting_approval"):
                stats[status] += count

        for row in cost_rows:
            stats = bucket(row["agent_id"])
            stats["cost_usd"] = float(row["cost_usd"])
            stats["input_tokens"] = int(row["input_tokens"])
            stats["output_tokens"] = int(row["output_tokens"])

        return {"days": days, "per_agent": per_agent}

    def get_agents_daily_spending(self, user_id: str) -> dict[str, float]:
        """Get today's spending per agent in one query (agent_id -> USD).

        Same local-midnight window as get_agent_daily_spending.
        """
        # LOCAL-naive on purpose: message_costs.created_at is stored local-naive
        today = datetime.now().date()
        today_start = datetime(today.year, today.month, today.day, 0, 0, 0)

        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT c.agent_id, COALESCE(SUM(mc.cost_usd), 0) as total
                   FROM message_costs mc
                   JOIN messages m ON mc.message_id = m.id
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.agent_id IS NOT NULL
                   AND mc.created_at >= ?
                   GROUP BY c.agent_id""",
                (user_id, today_start.isoformat()),
            ).fetchall()
            return {row["agent_id"]: float(row["total"]) for row in rows}

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
        agents = self.list_agents_with_status(user_id)
        total_unread = sum(a["unread_count"] for a in agents)
        agents_waiting = sum(1 for a in agents if a["has_pending_approval"])
        agents_with_errors = sum(1 for a in agents if a["has_error"])

        now = utcnow_naive()
        with self._pool.get_connection() as conn:
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

        pending_approvals = [
            {"approval": row_to_approval_request(row), "agent_name": row["agent_name"]}
            for row in approval_rows
        ]

        return {
            "agents": agents,
            "pending_approvals": pending_approvals,
            "recent_executions": self.get_recent_executions(user_id, limit=10),
            "total_unread": total_unread,
            "agents_waiting": agents_waiting,
            "agents_with_errors": agents_with_errors,
        }

    # ============ Budget Tracking ============

    def get_agent_daily_spending(self, agent_id: str) -> float:
        """Get the total spending for an agent today (in USD).

        Calculates the sum of all costs for messages in the agent's conversation
        created on the current day (server-local time - the budget window
        resets at local midnight, matching how message_costs.created_at is
        stored).

        Returns:
            Total spending in USD for today.
        """
        # LOCAL-naive on purpose: message_costs.created_at is stored local-naive,
        # so the daily window must use the same clock (resets at local midnight)
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
