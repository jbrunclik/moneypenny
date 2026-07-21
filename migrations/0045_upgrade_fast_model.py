"""
Upgrade conversations and autonomous agents from Gemini 3.5 Flash to Gemini 3.6 Flash.

Gemini 3.6 Flash (released July 2026) replaces 3.5 Flash as the "Fast" model
option. The old model ID is no longer in the MODELS dict, so the UI wouldn't
display a model name for existing conversations without this migration.

Note: cost_tracking / message_costs rows are intentionally left untouched to
preserve historical per-model spend records.
"""

from yoyo import step

__depends__ = {"0044_add_tool_round_telemetry"}

steps = [
    step(
        "UPDATE conversations SET model = 'gemini-3.6-flash' WHERE model = 'gemini-3.5-flash'",
        "UPDATE conversations SET model = 'gemini-3.5-flash' WHERE model = 'gemini-3.6-flash'",
    ),
    step(
        "UPDATE autonomous_agents SET model = 'gemini-3.6-flash' WHERE model = 'gemini-3.5-flash'",
        "UPDATE autonomous_agents SET model = 'gemini-3.5-flash' WHERE model = 'gemini-3.6-flash'",
    ),
]
