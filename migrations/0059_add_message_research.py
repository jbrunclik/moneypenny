"""Add research to messages.

Deep research (docs/superpowers/specs/2026-10-03-deep-research-design.md):
{"offer": {...}} on the assistant message that offers a run, {"run": {...}}
on the report. NULL for everything else.
"""

from yoyo import step

__depends__ = {"0058_convert_grounding_markers"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN research TEXT",
        "ALTER TABLE messages DROP COLUMN research",
    ),
]
