"""Reminders: one-off pushes set from chat ("remind me Friday at 8 to call the plumber").

The every-minute scheduler claims due pending rows (status -> sent) in one
statement and pushes them - no model call (docs/features/agents.md).
"""

from yoyo import step

__depends__ = {"0074_drop_timestamp_storage_flag"}

steps = [
    step(
        """CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            text TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )""",
        "DROP TABLE reminders",
    ),
    step(
        "CREATE INDEX idx_reminders_status_due ON reminders(status, due_at)",
        "DROP INDEX IF EXISTS idx_reminders_status_due",
    ),
    step(
        "CREATE INDEX idx_reminders_user ON reminders(user_id, status)",
        "DROP INDEX IF EXISTS idx_reminders_user",
    ),
]
