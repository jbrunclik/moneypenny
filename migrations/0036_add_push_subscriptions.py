"""
Add push_subscriptions table for Web Push notifications.

One row per device/browser subscription (a user can have several: iPhone
PWA, desktop Chrome, ...). endpoint is unique - re-subscribing the same
browser upserts. Subscriptions are pruned when a push send returns
404/410 (expired/revoked by the push service).
"""

from yoyo import step

__depends__ = {"0035_add_stream_journal"}

steps = [
    step(
        """
        CREATE TABLE push_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """,
        "DROP TABLE IF EXISTS push_subscriptions",
    ),
    step(
        "CREATE INDEX idx_push_subscriptions_user ON push_subscriptions(user_id)",
        "DROP INDEX IF EXISTS idx_push_subscriptions_user",
    ),
]
