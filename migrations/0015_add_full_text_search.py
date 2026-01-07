"""
Add FTS5 full-text search for conversations and messages.

Creates a single FTS5 virtual table (search_index) that indexes:
- Conversation titles
- Message content (both user and assistant messages)

Uses triggers to keep the FTS index automatically synced with source tables.
The tokenizer uses Porter stemmer for English word stemming (e.g., "running"
matches "run") and unicode61 for international character support with
diacritic removal (e.g., "cafe" matches "café").

UNINDEXED columns (user_id, conversation_id, message_id, type) are stored
for filtering but not searchable - this is more efficient than indexing
columns we only use in WHERE clauses.
"""

from yoyo import step

steps = [
    # Create the FTS5 virtual table for search
    step(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
            user_id UNINDEXED,
            conversation_id UNINDEXED,
            message_id UNINDEXED,
            type UNINDEXED,
            title,
            content,
            tokenize='porter unicode61 remove_diacritics 2'
        )
        """,
        "DROP TABLE IF EXISTS search_index",
    ),
    # Trigger: Insert conversation title when conversation is created
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
    ),
    # Trigger: Update conversation title when it changes
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id AND type = 'conversation';
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_update_conversation",
    ),
    # Trigger: Delete conversation from search index (cascade deletes all related entries)
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_delete_conversation AFTER DELETE ON conversations
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id;
        END
        """,
        "DROP TRIGGER IF EXISTS fts_delete_conversation",
    ),
    # Trigger: Insert message content when message is created
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_message AFTER INSERT ON messages
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            SELECT c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c
            WHERE c.id = NEW.conversation_id;
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_message",
    ),
    # Trigger: Delete message from search index
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_delete_message AFTER DELETE ON messages
        BEGIN
            DELETE FROM search_index WHERE message_id = OLD.id;
        END
        """,
        "DROP TRIGGER IF EXISTS fts_delete_message",
    ),
    # Populate search index with existing conversation titles
    step(
        """
        INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
        SELECT c.user_id, c.id, NULL, 'conversation', c.title, ''
        FROM conversations c
        """,
        None,  # No rollback needed - DROP TABLE handles cleanup
    ),
    # Populate search index with existing message content
    step(
        """
        INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
        SELECT c.user_id, m.conversation_id, m.id, 'message', '', m.content
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        """,
        None,  # No rollback needed - DROP TABLE handles cleanup
    ),
]
