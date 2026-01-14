"""Cost tracking database operations mixin.

Contains all methods for message cost tracking including:
- Save/get message costs
- Conversation cost totals
- Monthly user cost reports
- Cost history
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class CostMixin:
    """Mixin providing cost tracking database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def save_message_cost(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        image_generation_cost_usd: float = 0.0,
    ) -> None:
        """Save cost information for a message.

        Args:
            message_id: The message ID
            conversation_id: The conversation ID
            user_id: The user ID
            model: The model used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_usd: Total cost in USD
            image_generation_cost_usd: Cost for image generation in USD (default 0.0)
        """
        cost_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        logger.debug(
            "Saving message cost",
            extra={
                "message_id": message_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            },
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO message_costs (
                    id, message_id, conversation_id, user_id, model,
                    input_tokens, output_tokens, cost_usd, image_generation_cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cost_id,
                    message_id,
                    conversation_id,
                    user_id,
                    model,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    image_generation_cost_usd,
                    now,
                ),
            )
            conn.commit()

        logger.debug("Message cost saved", extra={"cost_id": cost_id, "message_id": message_id})

    def get_message_cost(self, message_id: str) -> dict[str, Any] | None:
        """Get cost information for a specific message.

        Args:
            message_id: The message ID

        Returns:
            Dict with 'cost_usd', 'input_tokens', 'output_tokens', 'model', 'image_generation_cost_usd', or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT cost_usd, input_tokens, output_tokens, model, image_generation_cost_usd
                   FROM message_costs
                   WHERE message_id = ?""",
                (message_id,),
            ).fetchone()

            if not row:
                return None

            return {
                "cost_usd": float(row["cost_usd"] or 0.0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "model": row["model"],
                "image_generation_cost_usd": float(
                    row["image_generation_cost_usd"]
                    if row["image_generation_cost_usd"] is not None
                    else 0.0
                ),
            }

    def get_conversation_cost(self, conversation_id: str) -> float:
        """Get total cost for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Total cost in USD
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT SUM(cost_usd) as total FROM message_costs WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            return float(row["total"] or 0.0) if row else 0.0

    def get_user_monthly_cost(self, user_id: str, year: int, month: int) -> dict[str, Any]:
        """Get cost for a user in a specific month.

        Args:
            user_id: The user ID
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            Dict with 'total_usd', 'message_count', and 'breakdown' (by model)

        Raises:
            ValueError: If month is not in range 1-12
        """
        # Validate month range
        if not (1 <= month <= 12):
            raise ValueError(f"Month must be between 1 and 12, got {month}")

        # Build date range for the month
        start_date = datetime(year, month, 1).isoformat()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).isoformat()
        else:
            end_date = datetime(year, month + 1, 1).isoformat()

        with self._pool.get_connection() as conn:
            # Get total cost and message count
            total_row = self._execute_with_timing(
                conn,
                """SELECT SUM(cost_usd) as total, COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ? AND created_at >= ? AND created_at < ?""",
                (user_id, start_date, end_date),
            ).fetchone()

            # Get breakdown by model
            breakdown_rows = self._execute_with_timing(
                conn,
                """SELECT model, SUM(cost_usd) as total, COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ? AND created_at >= ? AND created_at < ?
                   GROUP BY model""",
                (user_id, start_date, end_date),
            ).fetchall()

            total_usd = float(total_row["total"] or 0.0) if total_row else 0.0
            message_count = int(total_row["count"] or 0) if total_row else 0

            breakdown = {
                row["model"]: {
                    "total_usd": float(row["total"] or 0.0),
                    "message_count": int(row["count"] or 0),
                }
                for row in breakdown_rows
            }

            return {
                "total_usd": total_usd,
                "message_count": message_count,
                "breakdown": breakdown,
            }

    def get_user_cost_history(self, user_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Get monthly cost history for a user.

        Args:
            user_id: The user ID
            limit: Number of months to return (default 12)

        Returns:
            List of dicts with 'year', 'month', 'total_usd', 'message_count'
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT
                    strftime('%Y', created_at) as year,
                    strftime('%m', created_at) as month,
                    SUM(cost_usd) as total,
                    COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ?
                   GROUP BY year, month
                   ORDER BY year DESC, month DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()

            # Sort from current month to oldest (reverse chronological)
            # The database query already returns DESC, but we ensure proper sorting

            return [
                {
                    "year": int(row["year"]),
                    "month": int(row["month"]),
                    "total_usd": float(row["total"] or 0.0),
                    "message_count": int(row["count"] or 0),
                }
                for row in rows
            ]
