"""Spend of side calls - titles, reviews, AI assist, compaction, memory review
and summaries - which never reached message_costs (Nov 15 2026 audit;
docs/superpowers/specs/2026-11-15-cost-telemetry-design.md)."""

from yoyo import step

__depends__ = {"0092_scheduled_items_resume"}

steps = [
    step(
        """CREATE TABLE side_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            user_id TEXT,
            feature TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0
        )""",
        "DROP TABLE side_costs",
    ),
    step(
        "CREATE INDEX idx_side_costs_created_at ON side_costs (created_at)",
        "DROP INDEX idx_side_costs_created_at",
    ),
]
