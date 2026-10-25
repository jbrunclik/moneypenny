"""Admin page queries (S12): spend, turn quality, agent health, system facts.

Read-only aggregates across all users - names and numbers, never
conversation titles or content.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

# An error message can quote someone's content (a page, a prompt): show only
# its first line, short - enough to diagnose, not to read along
AGENT_ERROR_MAX_CHARS = 120

# Which feature a conversation belongs to; a purged conversation leaves its
# costs behind with no row to join
_FEATURE_SQL = """
    CASE
        WHEN c.id IS NULL THEN 'deleted'
        WHEN c.is_agent = 1 THEN 'agents'
        WHEN c.is_planning = 1 THEN 'planner'
        WHEN c.is_sports = 1 THEN 'sports'
        WHEN c.is_language = 1 THEN 'language'
        ELSE 'chat'
    END
"""


class AdminMixin:
    """Mixin providing the admin page's read-only aggregates."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _rows(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._pool.get_connection() as conn:
            return list(self._execute_with_timing(conn, query, params).fetchall())

    def admin_spend_per_user(
        self, day_start: datetime, month_start: datetime
    ) -> list[dict[str, Any]]:
        """Every user's spend today and this month, with this month's chats (any
        conversation with a billed turn) and turns (users without spend included)."""
        rows = self._rows(
            """SELECT u.id, u.name,
                      COALESCE(SUM(CASE WHEN mc.created_at >= ? THEN mc.cost_usd END), 0),
                      COALESCE(SUM(mc.cost_usd), 0),
                      COUNT(DISTINCT mc.conversation_id), COUNT(mc.id)
               FROM users u
               LEFT JOIN message_costs mc ON mc.user_id = u.id AND mc.created_at >= ?
               GROUP BY u.id ORDER BY u.name""",
            (day_start.isoformat(), month_start.isoformat()),
        )
        return [
            {
                "user_id": r[0],
                "name": r[1],
                "today_usd": r[2],
                "month_usd": r[3],
                "month_chats": r[4],
                "month_turns": r[5],
            }
            for r in rows
        ]

    def user_spend_since(self, user_id: str, since: datetime) -> float:
        """One user's spend since a moment (the spend banner)."""
        rows = self._rows(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM message_costs"
            " WHERE user_id = ? AND created_at >= ?",
            (user_id, since.isoformat()),
        )
        return float(rows[0][0])

    def admin_spend_by_day(self, since: datetime) -> list[tuple[str, float]]:
        """Family spend per calendar day since a moment (days with spend only)."""
        rows = self._rows(
            """SELECT substr(created_at, 1, 10) AS day, SUM(cost_usd)
               FROM message_costs WHERE created_at >= ?
               GROUP BY day ORDER BY day""",
            (since.isoformat(),),
        )
        return [(r[0], float(r[1])) for r in rows]

    def admin_spend_by_feature(self, since: datetime) -> dict[str, float]:
        """Family spend since a moment by feature (chat, agents, planner, ...)."""
        rows = self._rows(
            f"""SELECT {_FEATURE_SQL} AS feature, SUM(mc.cost_usd)
                FROM message_costs mc LEFT JOIN conversations c ON c.id = mc.conversation_id
                WHERE mc.created_at >= ? GROUP BY feature""",
            (since.isoformat(),),
        )
        return {r[0]: float(r[1]) for r in rows}

    def admin_spend_by_model(self, since: datetime) -> dict[str, float]:
        """Family spend since a moment by model."""
        rows = self._rows(
            "SELECT model, SUM(cost_usd) FROM message_costs WHERE created_at >= ? GROUP BY model",
            (since.isoformat(),),
        )
        return {r[0]: float(r[1]) for r in rows}

    def admin_turn_stats(self, since: datetime) -> dict[str, Any]:
        """Turn count, durations and tool-error turns since a moment."""
        rows = self._rows(
            "SELECT duration_ms, tool_errors FROM message_costs WHERE created_at >= ?",
            (since.isoformat(),),
        )
        return {
            "turns": len(rows),
            "durations_ms": [r[0] for r in rows if r[0] is not None],
            "turns_with_tool_errors": sum(1 for r in rows if (r[1] or 0) > 0),
        }

    def admin_agent_runs(self, since: datetime) -> dict[str, int]:
        """Agent runs and failed runs since a moment, plus pending approvals."""
        runs = self._rows(
            """SELECT COUNT(*), COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 END), 0)
               FROM agent_executions WHERE started_at >= ?""",
            (since.isoformat(),),
        )[0]
        pending = self._rows(
            "SELECT COUNT(*) FROM agent_approval_requests WHERE status = 'pending'"
        )[0][0]
        return {"runs": runs[0], "failed": runs[1], "pending_approvals": pending}

    def admin_recent_agent_failures(self, limit: int) -> list[dict[str, Any]]:
        """The latest failed agent runs, error messages cut short."""
        rows = self._rows(
            """SELECT a.name, u.name, e.started_at, e.error_message
               FROM agent_executions e
               JOIN autonomous_agents a ON a.id = e.agent_id
               JOIN users u ON u.id = a.user_id
               WHERE e.status = 'failed'
               ORDER BY e.started_at DESC LIMIT ?""",
            (limit,),
        )
        return [
            {
                "agent_name": r[0],
                "user_name": r[1],
                "started_at": r[2],
                "error": (r[3] or "").strip().split("\n", 1)[0][:AGENT_ERROR_MAX_CHARS],
            }
            for r in rows
        ]

    def admin_user_count(self) -> int:
        return int(self._rows("SELECT COUNT(*) FROM users")[0][0])

    def admin_latest_migration(self) -> str | None:
        rows = self._rows(
            "SELECT migration_id FROM _yoyo_migration ORDER BY applied_at_utc DESC LIMIT 1"
        )
        return rows[0][0] if rows else None
