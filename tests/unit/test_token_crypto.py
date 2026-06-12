"""Tests for token encryption at rest (S3)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from src.config import Config
from src.utils import token_crypto
from src.utils.token_crypto import decrypt_token, encrypt_token


@pytest.fixture
def encryption_key(monkeypatch):
    """Configure a valid Fernet key and clear the cached cipher."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", key)
    token_crypto._get_fernet.cache_clear()
    yield key
    token_crypto._get_fernet.cache_clear()


@pytest.fixture
def no_encryption_key(monkeypatch):
    monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", "")
    token_crypto._get_fernet.cache_clear()
    yield
    token_crypto._get_fernet.cache_clear()


class TestTokenCrypto:
    def test_round_trip(self, encryption_key) -> None:
        stored = encrypt_token("secret-token")
        assert stored is not None and stored.startswith("enc:")
        assert "secret-token" not in stored
        assert decrypt_token(stored) == "secret-token"

    def test_encrypt_is_idempotent(self, encryption_key) -> None:
        once = encrypt_token("secret")
        assert encrypt_token(once) == once

    def test_legacy_plaintext_passes_through(self, encryption_key) -> None:
        assert decrypt_token("legacy-plaintext") == "legacy-plaintext"

    def test_none_and_empty_pass_through(self, encryption_key) -> None:
        assert encrypt_token(None) is None
        assert decrypt_token(None) is None
        assert encrypt_token("") == ""

    def test_no_key_is_plaintext_passthrough(self, no_encryption_key) -> None:
        assert encrypt_token("secret") == "secret"
        assert decrypt_token("secret") == "secret"

    def test_undecryptable_value_returns_none(self, encryption_key, monkeypatch) -> None:
        stored = encrypt_token("secret")
        # Key rotation: a different key cannot decrypt the old value
        monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        token_crypto._get_fernet.cache_clear()
        assert decrypt_token(stored) is None

    def test_invalid_key_disables_encryption(self, monkeypatch) -> None:
        monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
        token_crypto._get_fernet.cache_clear()
        assert encrypt_token("secret") == "secret"
        token_crypto._get_fernet.cache_clear()


class TestEncryptedStorage:
    def test_tokens_encrypted_at_rest_decrypted_on_read(
        self, encryption_key, test_database, test_user
    ) -> None:
        test_database.update_user_todoist_token(test_user.id, "todoist-secret")
        test_database.update_user_garmin_token(test_user.id, "garmin-secret")

        # Reads through the model are plaintext
        user = test_database.get_user_by_id(test_user.id)
        assert user.todoist_access_token == "todoist-secret"
        assert user.garmin_token == "garmin-secret"

        # Raw rows are ciphertext
        with test_database._pool.get_connection() as conn:
            row = conn.execute(
                "SELECT todoist_access_token, garmin_token FROM users WHERE id = ?",
                (test_user.id,),
            ).fetchone()
        assert row["todoist_access_token"].startswith("enc:")
        assert "todoist-secret" not in row["todoist_access_token"]
        assert row["garmin_token"].startswith("enc:")

    def test_cas_refresh_works_under_encryption(
        self, encryption_key, test_database, test_user
    ) -> None:
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="at-1",
            refresh_token="rt-1",
            expires_at=datetime.now() + timedelta(hours=1),
            email="g@example.com",
        )

        # Winner: stored refresh token matches the one this refresh used
        won = test_database.refresh_user_google_calendar_tokens(
            test_user.id,
            used_refresh_token="rt-1",
            access_token="at-2",
            refresh_token="rt-2",
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert won is True
        user = test_database.get_user_by_id(test_user.id)
        assert user.google_calendar_access_token == "at-2"
        assert user.google_calendar_refresh_token == "rt-2"

        # Loser: a concurrent refresh that used the stale token must not win
        lost = test_database.refresh_user_google_calendar_tokens(
            test_user.id,
            used_refresh_token="rt-1",
            access_token="at-3",
            refresh_token="rt-3",
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert lost is False
        assert test_database.get_user_by_id(test_user.id).google_calendar_refresh_token == "rt-2"

    def test_migration_routine_encrypts_legacy_plaintext(
        self, encryption_key, test_database, test_user
    ) -> None:
        from scripts.encrypt_existing_tokens import encrypt_tokens_in_connection

        # Simulate pre-S3 plaintext rows
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE users SET todoist_access_token = ?, garmin_token = ? WHERE id = ?",
                ("plain-todoist", "plain-garmin", test_user.id),
            )
            conn.commit()

            count = encrypt_tokens_in_connection(conn)
            conn.commit()
        assert count == 2

        user = test_database.get_user_by_id(test_user.id)
        assert user.todoist_access_token == "plain-todoist"
        assert user.garmin_token == "plain-garmin"

        # Re-run is a no-op (idempotent)
        with test_database._pool.get_connection() as conn:
            assert encrypt_tokens_in_connection(conn) == 0
