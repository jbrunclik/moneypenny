"""Where a turn's time went: time to first token, gate, lookup, model calls.

One JSON column (src/agent/turn_usage.py TurnClock): first_token_ms,
gate_ms, lookup_ms, model_ms, model_calls, finish_reason, gate_lookup,
thinking - queried with json_extract (docs/regular-review.md).
"""

from yoyo import step

__depends__ = {"0090_upgrade_to_gemini_4"}

steps = [
    step(
        "ALTER TABLE message_costs ADD COLUMN turn_timing TEXT",
        "ALTER TABLE message_costs DROP COLUMN turn_timing",
    ),
]
