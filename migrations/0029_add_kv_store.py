"""
Add key-value store table for persistent structured data.

This migration creates a user-scoped, namespaced key-value store
for agents and features that need persistent storage across conversations.
"""

from yoyo import step

steps = [
    step(
        """
        CREATE TABLE kv_store (
            user_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, namespace, key),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """,
        "DROP TABLE IF EXISTS kv_store",
    ),
    step(
        "CREATE INDEX idx_kv_store_user_namespace ON kv_store(user_id, namespace)",
        "DROP INDEX IF EXISTS idx_kv_store_user_namespace",
    ),
]
