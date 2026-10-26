"""Device check runs (the in-app runner's results) and its fixture conversations.

The runner measures the real layout on a device - the standalone PWA on an
iPhone, where no external automation reaches - and stores one row per run for
the admin page. Scenario results and the environment are JSON. Timestamps use
the "utc" legacy format (src/db/models/timestamps.py).

device_check_fixtures lists the throwaway conversations a run scrolls
through, so a crashed run's fixture is found and purged by the next one
without ever matching a real conversation.
"""

from yoyo import step

__depends__ = {"0070_add_client_error_detail"}

steps = [
    step(
        """CREATE TABLE device_check_runs (
               id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               build_marker TEXT,
               app_version TEXT,
               standalone INTEGER NOT NULL,
               ua_summary TEXT NOT NULL,
               environment TEXT NOT NULL,
               scenarios TEXT NOT NULL,
               passed INTEGER NOT NULL,
               failed INTEGER NOT NULL,
               skipped INTEGER NOT NULL,
               started_at TIMESTAMP NOT NULL,
               finished_at TIMESTAMP NOT NULL,
               created_at TIMESTAMP NOT NULL
           )""",
        "DROP TABLE device_check_runs",
    ),
    step(
        "CREATE INDEX idx_device_check_runs_created_at ON device_check_runs(created_at)",
        "DROP INDEX idx_device_check_runs_created_at",
    ),
    step(
        """CREATE TABLE device_check_fixtures (
               conversation_id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               created_at TIMESTAMP NOT NULL
           )""",
        "DROP TABLE device_check_fixtures",
    ),
]
