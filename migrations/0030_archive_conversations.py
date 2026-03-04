"""Add archive support for conversations.

This migration adds:
1. archived column to conversations table (INTEGER DEFAULT 0)
2. Composite index on (user_id, archived) for efficient filtered queries
3. Updates FTS triggers to exclude archived conversations from search index
4. Cleanup step to remove already-archived conversations from search_index
"""

from yoyo import step

__depends__ = {"0029_add_kv_store"}

steps = [
    # Add archived column to conversations table
    step(
        "ALTER TABLE conversations ADD COLUMN archived INTEGER DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN archived",
    ),
    # Index for efficient filtering by user + archived status
    step(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_archived ON conversations(user_id, archived)",
        "DROP INDEX IF EXISTS idx_conversations_user_archived",
    ),
    # Update FTS triggers to exclude archived conversations
    # Drop and recreate conversation insert trigger
    step(
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        WHEN (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
    ),
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        WHEN (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
    ),
    # Drop and recreate conversation update trigger
    step(
        "DROP TRIGGER IF EXISTS fts_update_conversation",
        """
        CREATE TRIGGER IF NOT EXISTS fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id AND type = 'conversation';
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
    ),
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id AND type = 'conversation';
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_update_conversation",
    ),
    # Drop and recreate message insert trigger
    step(
        "DROP TRIGGER IF EXISTS fts_insert_message",
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_message AFTER INSERT ON messages
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            SELECT c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c
            WHERE c.id = NEW.conversation_id
            AND (c.is_planning = 0 OR c.is_planning IS NULL)
            AND (c.is_agent = 0 OR c.is_agent IS NULL);
        END
        """,
    ),
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_message AFTER INSERT ON messages
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            SELECT c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c
            WHERE c.id = NEW.conversation_id
            AND (c.is_planning = 0 OR c.is_planning IS NULL)
            AND (c.is_agent = 0 OR c.is_agent IS NULL)
            AND (c.archived = 0 OR c.archived IS NULL);
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_message",
    ),
    # Remove any existing archived conversations from search index (cleanup for safety)
    step(
        """
        DELETE FROM search_index
        WHERE conversation_id IN (
            SELECT id FROM conversations WHERE archived = 1
        )
        """,
        None,
    ),
]
