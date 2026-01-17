"""Add budget_limit column to autonomous_agents table.

Allows per-agent daily spending limits in USD.
"""

from yoyo import step

steps = [
    step(
        """
        ALTER TABLE autonomous_agents ADD COLUMN budget_limit REAL DEFAULT NULL
        """,
        """
        -- SQLite doesn't support DROP COLUMN easily, so we just leave it
        -- The column will be ignored if this migration is rolled back
        """,
    ),
]
