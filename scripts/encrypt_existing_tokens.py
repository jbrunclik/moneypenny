#!/usr/bin/env python3
"""Encrypt existing plaintext OAuth/Garmin tokens in place (S3).

Idempotent and safe to re-run: already-encrypted values (enc: prefix)
are skipped. A no-op when TOKEN_ENCRYPTION_KEY is not configured.

Run automatically by migration 0042; run manually after setting the key
on an already-migrated database:

    .venv/bin/python scripts/encrypt_existing_tokens.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TOKEN_COLUMNS = (
    "todoist_access_token",
    "google_calendar_access_token",
    "google_calendar_refresh_token",
    "garmin_token",
)


def encrypt_tokens_in_connection(conn) -> int:  # noqa: ANN001 - sqlite3/yoyo connection
    """Encrypt plaintext token values on an open DB connection.

    Shared by migration 0042 and the manual script. Returns the number
    of values encrypted.
    """
    from src.utils.token_crypto import ENCRYPTED_PREFIX, encrypt_token, encryption_enabled

    if not encryption_enabled():
        print("TOKEN_ENCRYPTION_KEY not set - nothing to do (tokens stay plaintext).")
        return 0

    cursor = conn.cursor()
    columns = ", ".join(TOKEN_COLUMNS)
    rows = cursor.execute(f"SELECT id, {columns} FROM users").fetchall()  # noqa: S608 - constant columns

    encrypted = 0
    for row in rows:
        user_id = row[0]
        for index, column in enumerate(TOKEN_COLUMNS, start=1):
            value = row[index]
            if value and not value.startswith(ENCRYPTED_PREFIX):
                cursor.execute(
                    f"UPDATE users SET {column} = ? WHERE id = ?",  # noqa: S608 - constant column
                    (encrypt_token(value), user_id),
                )
                encrypted += 1
    return encrypted


def main() -> None:
    import sqlite3

    from src.config import Config

    conn = sqlite3.connect(Config.DATABASE_PATH)
    try:
        count = encrypt_tokens_in_connection(conn)
        conn.commit()
        print(f"Encrypted {count} token value(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
