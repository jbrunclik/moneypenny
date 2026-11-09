"""What's new: a read-only chat per user that receives announcements
(docs/features/whats-new.md).

conversations.is_whats_new marks the chat; announcement_posts records which
announcement reached which user (the claim that makes posting once per user,
however many workers start at once).
"""

from yoyo import step

__depends__ = {"0082_job_tables"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN is_whats_new INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN is_whats_new",
    ),
    step(
        """CREATE TABLE announcement_posts (
            user_id TEXT NOT NULL REFERENCES users(id),
            announcement_id TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            PRIMARY KEY (user_id, announcement_id)
        )""",
        "DROP TABLE announcement_posts",
    ),
    # One live What's new chat per user: two workers posting two announcements
    # at once cannot both create it (the loser's post is retried next start)
    step(
        """CREATE UNIQUE INDEX idx_conversations_one_whats_new ON conversations(user_id)
           WHERE is_whats_new = 1 AND deleted_at IS NULL""",
        "DROP INDEX idx_conversations_one_whats_new",
    ),
]
