"""A standing job's continuation after its cards were answered.

Approving a run's card used to resume the run on a thread in the web worker
(a deploy lost it); the outcome is now stored here and the scheduler's next
pass runs it (docs/superpowers/specs/2026-11-15-run-resume-and-tick-deadline-design.md).
"""

from yoyo import step

__depends__ = {"0091_message_costs_turn_timing"}

steps = [
    step(
        "ALTER TABLE scheduled_items ADD COLUMN resume_message TEXT",
        "ALTER TABLE scheduled_items DROP COLUMN resume_message",
    ),
    step(
        "ALTER TABLE scheduled_items ADD COLUMN resume_requested_at TEXT",
        "ALTER TABLE scheduled_items DROP COLUMN resume_requested_at",
    ),
]
