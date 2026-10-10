"""Server-side read state for unread badges shared across devices.

read_message_count is the conversation's message count as of the last time
any of the user's devices showed it; unread = message_count - read_count.
Recording it updates the conversation row, so the sync change log (0061)
carries "read" to the other devices. Existing conversations start fully
read - no flood of badges on deploy.
"""

from yoyo import step

__depends__ = {"0061_add_sync_change_log"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN read_message_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN read_message_count",
    ),
    step(
        """UPDATE conversations SET read_message_count =
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = conversations.id)"""
    ),
]
