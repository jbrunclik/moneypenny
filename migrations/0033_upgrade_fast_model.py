"""
Upgrade conversations and autonomous agents from Gemini 3 Flash to Gemini 3.5 Flash.

Gemini 3.5 Flash (released at Google I/O 2026) replaces 3 Flash as the
"Fast" model option. Old model ID is no longer in the MODELS dict, so
the UI wouldn't display a model name for existing conversations without
this migration.

Note: cost_tracking rows are intentionally left untouched to preserve
historical per-model spend records.
"""

from yoyo import step

steps = [
    step(
        "UPDATE conversations SET model = 'gemini-3.5-flash' WHERE model = 'gemini-3-flash-preview'",
        "UPDATE conversations SET model = 'gemini-3-flash-preview' WHERE model = 'gemini-3.5-flash'",
    ),
    step(
        "UPDATE autonomous_agents SET model = 'gemini-3.5-flash' WHERE model = 'gemini-3-flash-preview'",
        "UPDATE autonomous_agents SET model = 'gemini-3-flash-preview' WHERE model = 'gemini-3.5-flash'",
    ),
]
