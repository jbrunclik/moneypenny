"""Add annotations and grounding to messages.

annotations: JSON list of claim annotations (verdict, quote, prefix, reason,
source, source_quote) from the post-answer grounding check; grounding: JSON
summary for the footer ({"checked": true, "source_count": N}). Both NULL for
messages that were never checked. Spec:
docs/superpowers/specs/2026-10-03-grounding-annotations-design.md.
"""

from yoyo import step

__depends__ = {"0056_add_conversation_trash"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN annotations TEXT",
        "ALTER TABLE messages DROP COLUMN annotations",
    ),
    step(
        "ALTER TABLE messages ADD COLUMN grounding TEXT",
        "ALTER TABLE messages DROP COLUMN grounding",
    ),
]
