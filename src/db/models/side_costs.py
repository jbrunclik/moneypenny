"""Side-call spend rows (src/services/side_costs.py writes them)."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


class SideCostsMixin:
    """One row per side call: feature, model, tokens, cost."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self, conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> sqlite3.Cursor:
        raise NotImplementedError  # defined in the base class

    def add_side_cost(
        self,
        feature: str,
        model: str,
        tokens: tuple[int, int, int],
        cost_usd: float,
        user_id: str | None = None,
    ) -> None:
        """Record a side call; ``tokens`` = (input, cached input, output)."""
        input_tokens, cached_tokens, output_tokens = tokens
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO side_costs (created_at, user_id, feature, model, input_tokens,
                       cached_input_tokens, output_tokens, cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    to_db(utc_now()),
                    user_id,
                    feature,
                    model,
                    input_tokens,
                    cached_tokens,
                    output_tokens,
                    cost_usd,
                ),
            )
            conn.commit()
