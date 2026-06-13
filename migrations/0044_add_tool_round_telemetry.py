"""
Add per-turn tool telemetry to message_costs.

tool_rounds  = distinct LLM responses in the turn that requested tool calls.
               This is the round-multiplication multiplier: each one re-invokes
               the model with the accumulated context, so a turn with 13 rounds
               re-sends the ~30k fixed prefix 13 times (June 2026 audit found a
               $0.83 turn that was 13 sequential web_search rounds).
tool_call_count = number of tool executions (ToolMessages) in the turn.

Both default to 0 for existing rows. Lets scripts/analyze_costs.py flag
round-multiplication directly instead of reconstructing it from journals.
"""

from yoyo import step

__depends__ = {"0043_add_cached_input_tokens"}

steps = [
    step(
        "ALTER TABLE message_costs ADD COLUMN tool_rounds INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_costs DROP COLUMN tool_rounds",
    ),
    step(
        "ALTER TABLE message_costs ADD COLUMN tool_call_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_costs DROP COLUMN tool_call_count",
    ),
]
