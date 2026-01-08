"""
Add language column to messages table.

Stores the ISO 639-1 language code of assistant messages (e.g., "en", "cs").
Used for text-to-speech voice selection.
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN language TEXT",
        # SQLite doesn't support DROP COLUMN easily, but for rollback we just ignore it
        ""
    ),
]
