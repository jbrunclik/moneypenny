"""
Add sources column to messages table.

Stores metadata about web sources cited in assistant responses.
- sources: JSON array of source objects [{title, url}, ...]
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN sources TEXT",
        # SQLite doesn't support DROP COLUMN easily, but for rollback we just ignore it
        ""
    ),
]
