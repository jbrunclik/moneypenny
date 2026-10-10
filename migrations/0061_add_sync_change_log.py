"""Change log for cross-device sync.

Every write to a conversation or its messages bumps a global, monotonic
sequence number and records it as that conversation's latest change. The
sync endpoint returns conversations changed after a client's cursor, so
another device sees archive / trash / delete / pin / rename / anonymous
toggles and message edits, regenerates and deletions - not just new
messages (the old updated_at + message_count detector missed all of those).

Triggers, not application code: they fire in the SAME transaction as the
write and cover every write path, including future ones. SQLite serializes
writers, so seq order equals commit order and a cursor never skips a change
(the updated_at-vs-server_time race of timestamp sync).

A permanent delete leaves its row behind (the conversation is gone, the
change row says so); the daily cleanup can prune old rows.
"""

from yoyo import step

__depends__ = {"0060_add_message_action"}


def _bump(conversation_id: str, user_id_select: str) -> str:
    """Trigger body: next seq, then upsert the conversation's change row."""
    return f"""
            UPDATE sync_counter SET value = value + 1 WHERE id = 1;
            INSERT INTO conversation_changes (conversation_id, user_id, seq)
            SELECT {conversation_id}, {user_id_select}, (SELECT value FROM sync_counter WHERE id = 1)
            WHERE {user_id_select} IS NOT NULL
            ON CONFLICT(conversation_id) DO UPDATE SET seq = excluded.seq;"""


_CONV_USER_OF_NEW_MSG = "(SELECT user_id FROM conversations WHERE id = NEW.conversation_id)"
_CONV_USER_OF_OLD_MSG = "(SELECT user_id FROM conversations WHERE id = OLD.conversation_id)"

_TRIGGERS = {
    "sync_change_conversation_insert": (
        "AFTER INSERT ON conversations",
        _bump("NEW.id", "NEW.user_id"),
    ),
    "sync_change_conversation_update": (
        "AFTER UPDATE ON conversations",
        _bump("NEW.id", "NEW.user_id"),
    ),
    "sync_change_conversation_delete": (
        "AFTER DELETE ON conversations",
        _bump("OLD.id", "OLD.user_id"),
    ),
    "sync_change_message_insert": (
        "AFTER INSERT ON messages",
        _bump("NEW.conversation_id", _CONV_USER_OF_NEW_MSG),
    ),
    "sync_change_message_update": (
        "AFTER UPDATE ON messages",
        _bump("NEW.conversation_id", _CONV_USER_OF_NEW_MSG),
    ),
    # A message deleted with its conversation already gone has no owner
    # left: the conversation's own delete trigger recorded the change
    "sync_change_message_delete": (
        "AFTER DELETE ON messages",
        _bump("OLD.conversation_id", _CONV_USER_OF_OLD_MSG),
    ),
}

steps = [
    step(
        "CREATE TABLE sync_counter (id INTEGER PRIMARY KEY CHECK (id = 1), value INTEGER NOT NULL)",
        "DROP TABLE sync_counter",
    ),
    step(
        "INSERT INTO sync_counter (id, value) VALUES (1, 0)",
        "DELETE FROM sync_counter",
    ),
    step(
        """CREATE TABLE conversation_changes (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            seq INTEGER NOT NULL
        )""",
        "DROP TABLE conversation_changes",
    ),
    step(
        "CREATE INDEX idx_conversation_changes_user_seq ON conversation_changes(user_id, seq)",
        "DROP INDEX IF EXISTS idx_conversation_changes_user_seq",
    ),
    *[
        step(
            f"CREATE TRIGGER {name} {when} BEGIN{body}\n        END",
            f"DROP TRIGGER IF EXISTS {name}",
        )
        for name, (when, body) in _TRIGGERS.items()
    ],
]
