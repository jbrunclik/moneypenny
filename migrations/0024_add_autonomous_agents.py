"""Add autonomous agents support.

This migration adds:
1. autonomous_agents table to store agent configurations
2. agent_approval_requests table for permission workflow
3. agent_executions table to track execution history
4. is_agent and agent_id columns to conversations table
5. Updates FTS triggers to exclude agent conversations from search index

Autonomous agents:
- Run on cron schedules (checked every minute via systemd timer)
- Have dedicated conversations (auto-created)
- Require approval for dangerous operations (no timeout - waits indefinitely)
- Can trigger other agents
"""

from yoyo import step

__depends__ = {"0023_add_calendar_cache"}

steps = [
    # Create autonomous_agents table
    step(
        """
        CREATE TABLE IF NOT EXISTS autonomous_agents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            conversation_id TEXT REFERENCES conversations(id),
            name TEXT NOT NULL,
            description TEXT,
            system_prompt TEXT,
            schedule TEXT,
            timezone TEXT DEFAULT 'UTC',
            enabled INTEGER DEFAULT 1,
            tool_permissions TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT,
            next_run_at TEXT,
            last_viewed_at TEXT,
            model TEXT DEFAULT 'gemini-3-flash-preview',
            UNIQUE(user_id, name)
        )
        """,
        "DROP TABLE IF EXISTS autonomous_agents",
    ),
    # Indexes for autonomous_agents
    step(
        "CREATE INDEX IF NOT EXISTS idx_agents_user ON autonomous_agents(user_id)",
        "DROP INDEX IF EXISTS idx_agents_user",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_agents_next_run ON autonomous_agents(next_run_at) WHERE enabled = 1",
        "DROP INDEX IF EXISTS idx_agents_next_run",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_agents_conversation ON autonomous_agents(conversation_id)",
        "DROP INDEX IF EXISTS idx_agents_conversation",
    ),
    # Create agent_approval_requests table
    step(
        """
        CREATE TABLE IF NOT EXISTS agent_approval_requests (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES autonomous_agents(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            tool_name TEXT NOT NULL,
            tool_args TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            expires_at TEXT
        )
        """,
        "DROP TABLE IF EXISTS agent_approval_requests",
    ),
    # Index for pending approvals lookup
    step(
        "CREATE INDEX IF NOT EXISTS idx_approvals_user_pending ON agent_approval_requests(user_id, status)",
        "DROP INDEX IF EXISTS idx_approvals_user_pending",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_approvals_agent ON agent_approval_requests(agent_id)",
        "DROP INDEX IF EXISTS idx_approvals_agent",
    ),
    # Index for expiration filtering (pending + not expired)
    step(
        "CREATE INDEX IF NOT EXISTS idx_approvals_expires ON agent_approval_requests(status, expires_at) WHERE status = 'pending'",
        "DROP INDEX IF EXISTS idx_approvals_expires",
    ),
    # Create agent_executions table
    step(
        """
        CREATE TABLE IF NOT EXISTS agent_executions (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES autonomous_agents(id),
            status TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            triggered_by_agent_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        )
        """,
        "DROP TABLE IF EXISTS agent_executions",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_executions_agent ON agent_executions(agent_id)",
        "DROP INDEX IF EXISTS idx_executions_agent",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_executions_status ON agent_executions(status)",
        "DROP INDEX IF EXISTS idx_executions_status",
    ),
    # Composite index for getting latest execution per agent (optimizes "last execution" queries)
    step(
        "CREATE INDEX IF NOT EXISTS idx_executions_agent_started ON agent_executions(agent_id, started_at DESC)",
        "DROP INDEX IF EXISTS idx_executions_agent_started",
    ),
    # Index for filtering messages by role (optimizes unread count queries)
    step(
        "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)",
        "DROP INDEX IF EXISTS idx_messages_role",
    ),
    # Add is_agent and agent_id columns to conversations table
    step(
        "ALTER TABLE conversations ADD COLUMN is_agent INTEGER DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN is_agent",
    ),
    step(
        "ALTER TABLE conversations ADD COLUMN agent_id TEXT REFERENCES autonomous_agents(id)",
        "ALTER TABLE conversations DROP COLUMN agent_id",
    ),
    # Index on conversations.agent_id for efficient agent-to-conversation lookups
    # (used in command center unread counts and agent conversation queries)
    step(
        "CREATE INDEX IF NOT EXISTS idx_conversations_agent_id ON conversations(agent_id) WHERE agent_id IS NOT NULL",
        "DROP INDEX IF EXISTS idx_conversations_agent_id",
    ),
    # Update FTS triggers to exclude agent conversations (same pattern as planner)
    # Drop and recreate conversation insert trigger
    step(
        "DROP TRIGGER IF EXISTS fts_insert_conversation",
        """
        CREATE TRIGGER IF NOT EXISTS fts_insert_conversation AFTER INSERT ON conversations
        WHEN NEW.is_planning = 0 OR NEW.is_planning IS NULL
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
        WHEN OLD.title != NEW.title AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
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
            AND (c.is_planning = 0 OR c.is_planning IS NULL);
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
            AND (c.is_agent = 0 OR c.is_agent IS NULL);
        END
        """,
        "DROP TRIGGER IF EXISTS fts_insert_message",
    ),
    # Remove any existing agent conversations from search index (cleanup for safety)
    step(
        """
        DELETE FROM search_index
        WHERE conversation_id IN (
            SELECT id FROM conversations WHERE is_agent = 1
        )
        """,
        None,
    ),
]
