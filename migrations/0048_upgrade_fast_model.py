"""
Upgrade conversations and autonomous agents from Gemini 3.6 Flash to Gemini 3.7 Flash.

Gemini 3.7 Flash (released August 2026) replaces 3.6 Flash as the "Fast" model
option. The old model ID is no longer in the MODELS dict, so the UI wouldn't
display a model name for existing conversations without this migration.

Note: cost_tracking / message_costs rows are intentionally left untouched to
preserve historical per-model spend records.
"""

from yoyo import step

__depends__ = {"0047_add_conversation_anonymous_mode"}

steps = [
    step(
        "UPDATE conversations SET model = 'gemini-3.7-flash' WHERE model = 'gemini-3.6-flash'",
        "UPDATE conversations SET model = 'gemini-3.6-flash' WHERE model = 'gemini-3.7-flash'",
    ),
    step(
        "UPDATE autonomous_agents SET model = 'gemini-3.7-flash' WHERE model = 'gemini-3.6-flash'",
        "UPDATE autonomous_agents SET model = 'gemini-3.6-flash' WHERE model = 'gemini-3.7-flash'",
    ),
]
