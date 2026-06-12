"""Encryption at rest for OAuth/Garmin tokens (S3).

Tokens are encrypted with Fernet keyed from TOKEN_ENCRYPTION_KEY and
stored with an `enc:` prefix. Decryption transparently passes through
legacy plaintext values, so the rollout is safe in any order:

- key set, then deploy: migration 0042 encrypts existing rows, new
  writes are encrypted
- deploy without a key: everything keeps working in plaintext; set the
  key later and run scripts/encrypt_existing_tokens.py

Generate a key with: make token-key
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

ENCRYPTED_PREFIX = "enc:"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet | None:
    key = Config.TOKEN_ENCRYPTION_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        logger.error(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key - token "
            "encryption is DISABLED. Generate one with: make token-key"
        )
        return None


def encryption_enabled() -> bool:
    """Whether a usable encryption key is configured."""
    return _get_fernet() is not None


def encrypt_token(value: str | None) -> str | None:
    """Encrypt a token for storage; passthrough when no key is set."""
    if not value:
        return value
    fernet = _get_fernet()
    if fernet is None:
        return value
    if value.startswith(ENCRYPTED_PREFIX):
        return value  # already encrypted (idempotent for re-runs)
    return ENCRYPTED_PREFIX + fernet.encrypt(value.encode()).decode()


def decrypt_token(value: str | None) -> str | None:
    """Decrypt a stored token; legacy plaintext passes through.

    A value that is marked encrypted but cannot be decrypted (wrong or
    missing key) returns None - the integration then presents as
    disconnected instead of leaking ciphertext into API calls.
    """
    if not value:
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    fernet = _get_fernet()
    if fernet is None:
        logger.error(
            "Encrypted token found but TOKEN_ENCRYPTION_KEY is not set - "
            "treating the integration as disconnected"
        )
        return None
    try:
        return fernet.decrypt(value[len(ENCRYPTED_PREFIX) :].encode()).decode()
    except InvalidToken:
        logger.error(
            "Stored token failed to decrypt (key changed?) - treating "
            "the integration as disconnected"
        )
        return None
