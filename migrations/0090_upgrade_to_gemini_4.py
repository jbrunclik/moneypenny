"""
Upgrade conversations and standing jobs to the Gemini 4 models.

Gemini 4 Hydrogen (released November 2026) replaces 3.8 Flash as the "Fast"
model and Gemini 4 Carbon replaces 3.1 Pro as "Advanced". The old model IDs
are no longer in the MODELS dict, so the UI wouldn't display a model name for
existing conversations without this migration. Standing jobs carry their own
model (scheduled_items.model; the agents view falls back to the chat's).

Note: cost_tracking / message_costs rows are intentionally left untouched to
preserve historical per-model spend records.
"""

from yoyo import step

__depends__ = {"0089_research_offers_to_proposals"}

steps = [
    step(
        "UPDATE conversations SET model = 'gemini-4-hydrogen' WHERE model = 'gemini-3.8-flash'",
        "UPDATE conversations SET model = 'gemini-3.8-flash' WHERE model = 'gemini-4-hydrogen'",
    ),
    step(
        "UPDATE conversations SET model = 'gemini-4-carbon' WHERE model = 'gemini-3.1-pro-preview'",
        "UPDATE conversations SET model = 'gemini-3.1-pro-preview' WHERE model = 'gemini-4-carbon'",
    ),
    step(
        "UPDATE scheduled_items SET model = 'gemini-4-hydrogen' WHERE model = 'gemini-3.8-flash'",
        "UPDATE scheduled_items SET model = 'gemini-3.8-flash' WHERE model = 'gemini-4-hydrogen'",
    ),
    step(
        "UPDATE scheduled_items SET model = 'gemini-4-carbon' WHERE model = 'gemini-3.1-pro-preview'",
        "UPDATE scheduled_items SET model = 'gemini-3.1-pro-preview' WHERE model = 'gemini-4-carbon'",
    ),
]
