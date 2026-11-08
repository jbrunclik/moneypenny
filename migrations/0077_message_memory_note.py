"""Replies get a memory_note: what the background memory review saved.

docs/superpowers/specs/2026-11-08-background-memory-review-design.md.
"""

from yoyo import step

__depends__ = {"0076_scheduled_items"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN memory_note TEXT",
        "ALTER TABLE messages DROP COLUMN memory_note",
    ),
]
