"""Drop what only the switch to UTC storage needed (timezone design, step 4).

- The app_settings flag ``timestamp_storage``: since Nov 7 2026 the app
  always writes fixed-width UTC and no longer reads the flag.
- Cached Gemini Files URIs whose ``expires_at`` has no offset: written before
  Oct 27 2026, so expired long ago (47 h TTL), and ``from_db`` no longer reads
  naive values.

Rollback restores the flag (code from before step 4 reads it); the expired
cache entries stay gone.
"""

from yoyo import step

__depends__ = {"0073_add_conversation_facts"}

steps = [
    step(
        "DELETE FROM app_settings WHERE key = 'timestamp_storage'",
        """INSERT OR IGNORE INTO app_settings (key, value, updated_at)
           VALUES ('timestamp_storage', 'utc',
                   strftime('%Y-%m-%dT%H:%M:%S.000000+00:00', 'now'))""",
    ),
    step(
        """DELETE FROM kv_store
           WHERE namespace = 'gemini_files'
             AND json_valid(value)
             AND json_extract(value, '$.expires_at') NOT LIKE '%+00:00'""",
        "SELECT 1",  # expired entries are not restored
    ),
]
