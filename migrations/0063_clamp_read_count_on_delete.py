"""Keep a conversation's read count within its message count on deletes.

Delete / truncate / regenerate removed messages but left read_message_count
above the real count, so the next messages another device added got no
unread badge anywhere until the count caught up.
"""

from yoyo import step

__depends__ = {"0062_add_conversation_read_count"}

steps = [
    step(
        """CREATE TRIGGER read_count_clamp_message_delete AFTER DELETE ON messages
        BEGIN
            UPDATE conversations
            SET read_message_count = (
                SELECT COUNT(*) FROM messages WHERE conversation_id = OLD.conversation_id)
            WHERE id = OLD.conversation_id
              AND read_message_count > (
                SELECT COUNT(*) FROM messages WHERE conversation_id = OLD.conversation_id);
        END""",
        "DROP TRIGGER IF EXISTS read_count_clamp_message_delete",
    ),
]
