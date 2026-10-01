"""Add trash support for conversations.

deleted_at marks a conversation as in the trash (NULL = live). Trashed rows
are hidden from every user-facing query and purged by the daily cleanup
sweep after TRASH_RETENTION_DAYS.
"""

from yoyo import step

__depends__ = {"0055_add_message_stop_reason"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN deleted_at TEXT",
        "ALTER TABLE conversations DROP COLUMN deleted_at",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_deleted"
        " ON conversations(user_id, deleted_at)",
        "DROP INDEX IF EXISTS idx_conversations_user_deleted",
    ),
]
