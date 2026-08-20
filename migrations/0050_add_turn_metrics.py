"""
Per-turn observability on message_costs (A3 remainder).

duration_ms  = wall-clock of the whole agent turn (graph run), measured in
               ChatAgent for both batch and streaming paths
tool_errors  = ToolMessages detected as failures by the same structural check
               self-correction uses (status/error envelope)
tools_used   = JSON array of unique tool names executed in the turn

Together with the existing tool_rounds/tokens/cost columns this makes
latency, tool reliability, and tool mix queryable per turn (analyze_costs.py
gains a Turn Metrics section).
"""

from yoyo import step

__depends__ = {"0049_add_embeddings"}

steps = [
    step(
        "ALTER TABLE message_costs ADD COLUMN duration_ms INTEGER",
        "ALTER TABLE message_costs DROP COLUMN duration_ms",
    ),
    step(
        "ALTER TABLE message_costs ADD COLUMN tool_errors INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_costs DROP COLUMN tool_errors",
    ),
    step(
        "ALTER TABLE message_costs ADD COLUMN tools_used TEXT",
        "ALTER TABLE message_costs DROP COLUMN tools_used",
    ),
]
