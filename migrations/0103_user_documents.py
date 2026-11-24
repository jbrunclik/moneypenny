"""Saved documents (document memory, Nov 24 2026): a per-user library of files
the agent keeps on purpose - a contract, an equity waterfall - with a summary
of what each holds and when to use it. The bytes live in the blob store under
doc/<id>, outside the chat attachments' retention sweep. Soft delete and an
optional last day (valid_until, a local date) mirror user_memories."""

from yoyo import step

__depends__ = {"0102_conversation_kv_follows_delete"}

steps = [
    step(
        """CREATE TABLE user_documents (
               id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               title TEXT NOT NULL,
               summary TEXT NOT NULL,
               use_for TEXT NOT NULL,
               filename TEXT NOT NULL,
               mime_type TEXT NOT NULL,
               size_bytes INTEGER NOT NULL,
               valid_until TEXT,
               source_conversation_id TEXT,
               source_message_id TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               deleted_at TEXT,
               last_opened_at TEXT
           )""",
        "DROP TABLE user_documents",
    ),
    step(
        "CREATE INDEX idx_user_documents_user ON user_documents(user_id, deleted_at)",
        "DROP INDEX idx_user_documents_user",
    ),
]
