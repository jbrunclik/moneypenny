"""Conversation facts: settled facts per conversation, sent with every turn.

Each row remembers the assistant message that last set it, and goes with it:
deleting that reply (regenerate deletes it first) drops the facts it set, so a
wrong fact cannot outlive the answer that introduced it
(docs/features/conversation-facts.md).
"""

from yoyo import step

__depends__ = {"0072_timestamps_to_utc"}

steps = [
    step(
        """CREATE TABLE conversation_facts (
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            text TEXT NOT NULL,
            message_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, fact_key)
        )""",
        "DROP TABLE conversation_facts",
    ),
    step(
        "CREATE INDEX idx_conversation_facts_message ON conversation_facts(message_id)",
        "DROP INDEX IF EXISTS idx_conversation_facts_message",
    ),
    step(
        """CREATE TRIGGER conversation_facts_message_delete AFTER DELETE ON messages
        BEGIN
            DELETE FROM conversation_facts WHERE message_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS conversation_facts_message_delete",
    ),
    step(
        """CREATE TRIGGER conversation_facts_conversation_delete AFTER DELETE ON conversations
        BEGIN
            DELETE FROM conversation_facts WHERE conversation_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS conversation_facts_conversation_delete",
    ),
]
