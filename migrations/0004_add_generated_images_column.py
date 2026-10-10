"""
Add generated_images column to messages table.

Stores metadata about AI-generated images in assistant responses.
- generated_images: JSON array of image metadata objects [{prompt}, ...]
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN generated_images TEXT",
        # SQLite doesn't support DROP COLUMN easily, but for rollback we just ignore it
        ""
    ),
]
