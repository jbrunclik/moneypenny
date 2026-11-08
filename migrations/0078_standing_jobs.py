"""Standing jobs: scheduled items that carry grants, a model, a budget and a timezone.

A row with grants set is a standing job (an agent's schedule); NULL grants is a
light item from chat, as before. message_costs.job_id attributes an unattended
run's cost to its job, so a job's daily budget counts its own runs only.
docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md (Part A).
"""

from yoyo import step

__depends__ = {"0077_message_memory_note"}

_ITEM_COLUMNS = [
    ("grants", "TEXT"),
    ("model", "TEXT"),
    ("budget_usd", "REAL"),
    ("fresh_context", "INTEGER NOT NULL DEFAULT 1"),
    ("timezone", "TEXT"),
    ("paused_reason", "TEXT"),
]

steps = [
    *(
        step(
            f"ALTER TABLE scheduled_items ADD COLUMN {name} {kind}",
            f"ALTER TABLE scheduled_items DROP COLUMN {name}",
        )
        for name, kind in _ITEM_COLUMNS
    ),
    step(
        "ALTER TABLE message_costs ADD COLUMN job_id TEXT",
        "ALTER TABLE message_costs DROP COLUMN job_id",
    ),
    step(
        "CREATE INDEX idx_message_costs_job ON message_costs(job_id, created_at)",
        "DROP INDEX idx_message_costs_job",
    ),
]
