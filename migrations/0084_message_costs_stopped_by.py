"""Why a turn stopped early (turn budgets): cost, time, rounds or loop.

Replies whose turn hit the old 6-round cap keep their Continue: they are
backfilled as 'rounds'.
"""

from yoyo import step

__depends__ = {"0083_whats_new"}

steps = [
    step(
        "ALTER TABLE message_costs ADD COLUMN stopped_by TEXT",
        "ALTER TABLE message_costs DROP COLUMN stopped_by",
    ),
    step("UPDATE message_costs SET stopped_by = 'rounds' WHERE tool_rounds >= 6", "SELECT 1"),
]
