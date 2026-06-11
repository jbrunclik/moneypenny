"""Add budget_limit column to autonomous_agents table.

Allows per-agent daily spending limits in USD.
"""

from yoyo import step

__depends__ = {"0024_add_autonomous_agents"}

steps = [
    step(
        """
        ALTER TABLE autonomous_agents ADD COLUMN budget_limit REAL DEFAULT NULL
        """,
        # SQLite supports DROP COLUMN since 3.35 (2021); the previous
        # "rollback" was a SQL comment that silently succeeded doing nothing
        """
        ALTER TABLE autonomous_agents DROP COLUMN budget_limit
        """,
    ),
]
