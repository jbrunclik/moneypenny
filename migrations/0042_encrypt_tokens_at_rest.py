"""
Encrypt existing OAuth/Garmin tokens at rest (S3).

No schema change - re-writes plaintext token values encrypted with
TOKEN_ENCRYPTION_KEY (Fernet, `enc:` prefix). Set the key in .env BEFORE
deploying for this to take effect; without a key the migration is a
no-op and tokens stay plaintext (still fully functional). After setting
the key later, run scripts/encrypt_existing_tokens.py manually - the
routine is shared and idempotent.
"""

import sys
from pathlib import Path

from yoyo import step

# Make src/ and scripts/ importable when yoyo runs this file directly
sys.path.insert(0, str(Path(__file__).parent.parent))

__depends__ = {"0041_add_preferred_language"}


def _encrypt_existing_tokens(conn):  # noqa: ANN001, ANN202 - yoyo step signature
    from scripts.encrypt_existing_tokens import encrypt_tokens_in_connection

    encrypt_tokens_in_connection(conn)


steps = [
    step(_encrypt_existing_tokens),
]
