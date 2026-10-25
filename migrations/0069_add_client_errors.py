"""Errors the browser reports (uncaught errors, unhandled rejections, logged errors).

Until now they lived only in each device's console. One row per user and
fingerprint (kind + message + first stack frame) with a count, so a recurring
error stays one row. Rows unseen for CLIENT_ERROR_RETENTION_DAYS are pruned on
insert.
"""

from yoyo import step

__depends__ = {"0068_unique_planner_conversation"}

steps = [
    step(
        """CREATE TABLE client_errors (
               id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               fingerprint TEXT NOT NULL,
               kind TEXT NOT NULL,
               message TEXT NOT NULL,
               stack TEXT,
               path TEXT,
               app_version TEXT,
               user_agent TEXT,
               count INTEGER NOT NULL DEFAULT 1,
               first_seen TIMESTAMP NOT NULL,
               last_seen TIMESTAMP NOT NULL,
               UNIQUE (user_id, fingerprint)
           )""",
        "DROP TABLE client_errors",
    ),
    step(
        "CREATE INDEX idx_client_errors_last_seen ON client_errors(last_seen)",
        "DROP INDEX idx_client_errors_last_seen",
    ),
]
