"""
Add planner feature support.

This migration adds:
1. is_planning flag to conversations table to identify the planner conversation
2. planner_last_reset_at timestamp to users table for daily 4am reset tracking
3. Updates FTS triggers to exclude planning conversations from search index

The planner is a special single-per-user conversation that:
- Has ephemeral chat that resets daily at 4am (or manually)
- Is excluded from search results
- Shows at the top of the conversation list
"""

from yoyo import step

steps = [
    # Add is_planning column to conversations table
    step(
        """
        ALTER TABLE conversations ADD COLUMN is_planning INTEGER DEFAULT 0
        """,
        """
        ALTER TABLE conversations DROP COLUMN is_planning
        """,
    ),
    # Add planner_last_reset_at column to users table
    step(
        """
        ALTER TABLE users ADD COLUMN planner_last_reset_at TEXT
        """,
        """
        ALTER TABLE users DROP COLUMN planner_last_reset_at
        """,
    ),
    # Drop and recreate FTS triggers to exclude planning conversations
    # Trigger: Insert conversation title when conversation is created (skip planning)
    step(
        """
        DROP TRIGGER IF EXISTS fts_insert_conversation
        """,
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
    ),
    step(
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        WHEN NEW.is_planning = 0 OR NEW.is_planning IS NULL
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
    ),
    # Trigger: Update conversation title when it changes (skip planning)
    step(
        """
        DROP TRIGGER IF EXISTS fts_update_conversation
        """,
        """
        CREATE TRIGGER IF NOT EXISTS fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
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
        WHEN OLD.title != NEW.title AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id AND type = 'conversation';
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END
        """,
        "DROP TRIGGER IF EXISTS fts_update_conversation",
    ),
    # Trigger: Insert message content when message is created (skip planning conversations)
    step(
        """
        DROP TRIGGER IF EXISTS fts_insert_message
        """,
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_message AFTER INSERT ON messages
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            SELECT c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c
            WHERE c.id = NEW.conversation_id;
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
            AND (c.is_planning = 0 OR c.is_planning IS NULL);
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_message",
    ),
    # Delete trigger doesn't need to check is_planning - deleting from FTS is always OK
    # The fts_delete_conversation and fts_delete_message triggers remain unchanged
    # Remove any existing planning conversations from search index (cleanup for safety)
    step(
        """
        DELETE FROM search_index
        WHERE conversation_id IN (
            SELECT id FROM conversations WHERE is_planning = 1
        )
        """,
        None,  # No rollback needed - data was already excluded from search
    ),
]
