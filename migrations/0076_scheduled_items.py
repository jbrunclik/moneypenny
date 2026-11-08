"""Scheduled items: reminders, check-ins, watchers and recurring checks set from chat.

docs/superpowers/specs/2026-11-07-lightweight-agents-design.md. The reminders
table becomes scheduled_items (pending reminders carried over); every item
belongs to a chat and is deleted with it (trigger). Chat-created recurring
agents never recorded their chat, so they are removed (none in production on
Nov 7 2026). Messages get a delivery label for turns an item delivered.
Self-contained on purpose: later code changes must not change what this does.
"""

from typing import Any

from yoyo import step

__depends__ = {"0075_add_reminders"}

_REMOVE_CHAT_AGENTS = (
    """DELETE FROM messages WHERE conversation_id IN (SELECT conversation_id
       FROM autonomous_agents WHERE description LIKE 'Created from chat%')""",
    """DELETE FROM agent_executions WHERE agent_id IN (SELECT id
       FROM autonomous_agents WHERE description LIKE 'Created from chat%')""",
    """DELETE FROM conversations WHERE id IN (SELECT conversation_id
       FROM autonomous_agents WHERE description LIKE 'Created from chat%')""",
    "DELETE FROM autonomous_agents WHERE description LIKE 'Created from chat%'",
)


def _restore_reminders(conn: Any) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            text TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )"""
    )
    cursor.execute(
        """INSERT INTO reminders (id, user_id, conversation_id, text, due_at, status, created_at)
           SELECT id, user_id, conversation_id, text, next_run_at, 'pending', created_at
           FROM scheduled_items WHERE kind = 'reminder'"""
    )


def _remove_chat_agents(conn: Any) -> None:
    cursor = conn.cursor()
    for statement in _REMOVE_CHAT_AGENTS:
        cursor.execute(statement)


steps = [
    step(
        """CREATE TABLE scheduled_items (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            kind TEXT NOT NULL
                CHECK (kind IN ('reminder', 'check_in', 'watcher', 'recurring')),
            text TEXT NOT NULL,
            end_condition TEXT,
            schedule TEXT,
            interval_hours INTEGER,
            next_run_at TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'running')),
            last_result TEXT,
            quiet_runs INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            claimed_at TEXT
        )""",
        "DROP TABLE scheduled_items",
    ),
    step(
        "CREATE INDEX idx_scheduled_items_due ON scheduled_items(status, next_run_at)",
        "DROP INDEX IF EXISTS idx_scheduled_items_due",
    ),
    step(
        "CREATE INDEX idx_scheduled_items_user ON scheduled_items(user_id)",
        "DROP INDEX IF EXISTS idx_scheduled_items_user",
    ),
    step(
        "CREATE INDEX idx_scheduled_items_conversation ON scheduled_items(conversation_id)",
        "DROP INDEX IF EXISTS idx_scheduled_items_conversation",
    ),
    step(
        """INSERT INTO scheduled_items
               (id, user_id, conversation_id, kind, text, next_run_at, status, created_at)
           SELECT id, user_id, conversation_id, 'reminder', text, due_at, 'active', created_at
           FROM reminders WHERE status = 'pending' AND conversation_id IS NOT NULL""",
        "DELETE FROM scheduled_items",
    ),
    # Rollback brings the reminders back (watchers and the other new kinds
    # have no place in that table and are dropped)
    step("DROP TABLE reminders", _restore_reminders),
    step(
        """CREATE TRIGGER scheduled_items_follow_conversation
           AFTER DELETE ON conversations
           BEGIN
               DELETE FROM scheduled_items WHERE conversation_id = OLD.id;
           END""",
        "DROP TRIGGER IF EXISTS scheduled_items_follow_conversation",
    ),
    # irreversible: removed chat-created agents (and their runs) are not recreated
    step(_remove_chat_agents, None),
    step(
        "ALTER TABLE messages ADD COLUMN delivery TEXT",
        "ALTER TABLE messages DROP COLUMN delivery",
    ),
]
