"""
Add user_memories table for storing LLM-extracted user facts.

This migration creates the user_memories table to store facts about users
that the LLM extracts during conversations for personalization.
"""

from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS user_memories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """,
        "DROP TABLE IF EXISTS user_memories",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_user_memories_user_id ON user_memories(user_id)",
        "DROP INDEX IF EXISTS idx_user_memories_user_id",
    ),
]
