"""
Upgrade conversations from Gemini 3 Pro to Gemini 3.1 Pro.

Gemini 3.1 Pro replaces 3.0 Pro as the "Advanced" model option.
Old model ID is no longer in the MODELS dict, so the UI wouldn't
display a model name for existing conversations without this migration.
"""

from yoyo import step

steps = [
    step(
        "UPDATE conversations SET model = 'gemini-3.1-pro-preview' WHERE model = 'gemini-3-pro-preview'",
        "UPDATE conversations SET model = 'gemini-3-pro-preview' WHERE model = 'gemini-3.1-pro-preview'",
    ),
]
