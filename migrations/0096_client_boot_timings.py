"""How long each page load's startup stages took, reported by the browser
after the app is ready (POST /api/client-timing). Slow opening was
unmeasured; a cached sidebar or lazy KaTeX gets decided from these rows
(docs/superpowers/specs/2026-11-16-client-reliability-design.md). Rows older
than CLIENT_BOOT_TIMINGS_RETENTION_DAYS are pruned on insert."""

from yoyo import step

__depends__ = {"0095_message_embedding_cleanup"}

steps = [
    step(
        """CREATE TABLE client_boot_timings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            response_end_ms INTEGER,
            dom_content_loaded_ms INTEGER,
            script_ms INTEGER,
            auth_ms INTEGER,
            data_ms INTEGER,
            route_ms INTEGER,
            ready_ms INTEGER,
            standalone INTEGER NOT NULL,
            viewport TEXT NOT NULL,
            connection TEXT,
            app_version TEXT,
            route TEXT NOT NULL
        )""",
        "DROP TABLE client_boot_timings",
    ),
    step(
        "CREATE INDEX idx_client_boot_timings_created ON client_boot_timings (created_at)",
        "DROP INDEX IF EXISTS idx_client_boot_timings_created",
    ),
]
