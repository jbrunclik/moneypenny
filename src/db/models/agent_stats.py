"""Agent observability database operations mixin.

Command center aggregation, per-agent run/cost stats and budget spend.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from src.db.models.agent_rows import row_to_agent
from src.db.models.timestamps import to_db
from src.utils.clock import local_day_start, utc_now
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

    def list_agents_with_status(self, user_id: str) -> list[dict[str, Any]]:
        """List agents with unread/pending/last-execution status in one query.

        Replaces the per-agent has_pending_approval + get_agent_unread_count +
        get_last_execution_status loop (3 queries per agent) in the listing
        route (Q1).
        """
        now = utc_now()
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
                (to_db(now), user_id),
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

    def get_agents_daily_spending(self, user_id: str) -> dict[str, float]:
        """Get today's spending per agent in one query (agent_id -> USD).

        Same local-midnight window as get_agent_daily_spending.
        """
        today_start = local_day_start(utc_now())

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
                (user_id, to_db(today_start)),
            ).fetchall()
            return {row["agent_id"]: float(row["total"]) for row in rows}

    def get_agent_daily_spending(self, agent_id: str) -> float:
        """Get the total spending for an agent today (in USD).

        Calculates the sum of all costs for messages in the agent's conversation
        created on the current day (server-local time - the budget window
        resets at local midnight, matching how message_costs.created_at is
        stored).

        Returns:
            Total spending in USD for today.
        """
        # The daily budget resets at local midnight (APP_TIMEZONE)
        today_start = local_day_start(utc_now())

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT COALESCE(SUM(mc.cost_usd), 0) as total
                   FROM message_costs mc
                   JOIN messages m ON mc.message_id = m.id
                   JOIN conversations c ON m.conversation_id = c.id
                   WHERE c.agent_id = ?
                   AND mc.created_at >= ?""",
                (agent_id, to_db(today_start)),
            ).fetchone()

            return float(row["total"]) if row else 0.0
