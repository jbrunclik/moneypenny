"""Add language learning support for conversations.

This migration adds:
1. is_language column to conversations table (INTEGER DEFAULT 0)
2. language_program column to conversations table (TEXT DEFAULT NULL)
3. Composite index on (user_id, is_language, language_program) for efficient queries
4. Updates FTS triggers to exclude language learning conversations from search index
"""

from yoyo import step

__depends__ = {"0031_add_sports_tracking"}

steps = [
    # Add is_language column to conversations table
    step(
        "ALTER TABLE conversations ADD COLUMN is_language INTEGER DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN is_language",
    ),
    # Add language_program column to conversations table
    step(
        "ALTER TABLE conversations ADD COLUMN language_program TEXT DEFAULT NULL",
        "ALTER TABLE conversations DROP COLUMN language_program",
    ),
    # Index for efficient filtering by user + language program
    step(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_language ON conversations(user_id, is_language, language_program)",
        "DROP INDEX IF EXISTS idx_conversations_user_language",
    ),
    # Update FTS triggers to exclude language learning conversations
    # Drop and recreate conversation insert trigger
    step(
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        WHEN (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
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
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
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
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
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
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
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
            AND (c.is_agent = 0 OR c.is_agent IS NULL)
            AND (c.archived = 0 OR c.archived IS NULL)
            AND (c.is_sports = 0 OR c.is_sports IS NULL);
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
            AND (c.archived = 0 OR c.archived IS NULL)
            AND (c.is_sports = 0 OR c.is_sports IS NULL)
            AND (c.is_language = 0 OR c.is_language IS NULL);
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_message",
    ),
]
