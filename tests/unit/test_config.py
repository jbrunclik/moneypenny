"""Unit tests for configuration validation."""

import os
from collections.abc import Iterator
from unittest.mock import patch

import pytest

import src.config


@pytest.fixture(autouse=True)
def _restore_config_module() -> Iterator[None]:
    """These tests reload src.config; put the original module contents back so
    modules that imported Config at load time and the rest of the suite keep
    sharing one Config class (a leftover reload made later tests patch a class
    nobody else reads)."""
    original = dict(vars(src.config))
    yield
    vars(src.config).clear()
    vars(src.config).update(original)


class TestConfigValidation:
    """Tests for Config.validate() method."""

    def test_missing_gemini_api_key(self) -> None:
        """Should require GEMINI_API_KEY."""
        # Reset module to pick up new env vars
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            # Reimport to get fresh config with patched env
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("GEMINI_API_KEY" in e for e in errors)

    def test_production_requires_google_client_id(self) -> None:
        """Should require GOOGLE_CLIENT_ID in production."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "",
                "ALLOWED_EMAILS": "test@example.com",
                "JWT_SECRET_KEY": "secure-production-key",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("GOOGLE_CLIENT_ID" in e for e in errors)

    def test_production_requires_allowed_emails(self) -> None:
        """Should require ALLOWED_EMAILS in production."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "ALLOWED_EMAILS": "",
                "JWT_SECRET_KEY": "secure-production-key",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("ALLOWED_EMAILS" in e for e in errors)

    def test_production_requires_secure_jwt_secret(self) -> None:
        """Should require secure JWT_SECRET_KEY in production."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "ALLOWED_EMAILS": "test@example.com",
                "JWT_SECRET_KEY": "dev-secret-change-me",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("JWT_SECRET_KEY" in e for e in errors)

    def test_development_mode_skips_auth_validation(self) -> None:
        """Should not require auth config in development mode."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "",
                "ALLOWED_EMAILS": "",
                "JWT_SECRET_KEY": "dev-secret-change-me",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            # Should not have auth-related errors in development mode
            assert not any("GOOGLE_CLIENT_ID" in e for e in errors)
            assert not any("ALLOWED_EMAILS" in e for e in errors)
            assert not any("JWT_SECRET_KEY" in e for e in errors)

    def test_invalid_port(self) -> None:
        """Should reject invalid PORT values."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "GEMINI_API_KEY": "test-key",
                "PORT": "99999",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("PORT" in e for e in errors)

    def test_invalid_currency(self) -> None:
        """Should reject unsupported currencies."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "GEMINI_API_KEY": "test-key",
                "COST_CURRENCY": "XYZ",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("COST_CURRENCY" in e for e in errors)

    def test_invalid_log_level(self) -> None:
        """Should reject invalid LOG_LEVEL values."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "GEMINI_API_KEY": "test-key",
                "LOG_LEVEL": "INVALID",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("LOG_LEVEL" in e for e in errors)

    def test_short_jwt_secret_in_production(self) -> None:
        """Should reject JWT secret shorter than 32 characters in production."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "ALLOWED_EMAILS": "test@example.com",
                "JWT_SECRET_KEY": "too-short-key",  # 13 characters
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert any("JWT_SECRET_KEY" in e and "32 characters" in e for e in errors)

    def test_valid_config_development(self) -> None:
        """Should pass validation with valid development config."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "GEMINI_API_KEY": "test-key",
                "PORT": "8000",
                "COST_CURRENCY": "USD",
                "LOG_LEVEL": "INFO",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert len(errors) == 0

    def test_valid_config_production(self) -> None:
        """Should pass validation with valid production config."""
        from cryptography.fernet import Fernet

        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "ALLOWED_EMAILS": "test@example.com",
                # JWT secret must be at least 32 characters in production
                "JWT_SECRET_KEY": "secure-production-key-1234567890123456",
                # Set explicitly so the test doesn't depend on a local .env
                "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "PORT": "8000",
                "COST_CURRENCY": "CZK",
                "LOG_LEVEL": "WARNING",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            assert len(errors) == 0

    def test_error_messages_are_helpful(self) -> None:
        """Error messages should include guidance on how to fix."""
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "",
            },
        ):
            from importlib import reload

            import src.config

            reload(src.config)
            from src.config import Config

            errors = Config.validate()
            # Should include URL for getting API key
            gemini_error = next(e for e in errors if "GEMINI_API_KEY" in e)
            assert "https://" in gemini_error or "ai.google.dev" in gemini_error


@pytest.fixture(autouse=True)
def reset_config_after_test() -> None:
    """Reset config module after each test to avoid pollution."""
    yield
    # Restore test environment for other tests
    os.environ["FLASK_ENV"] = "testing"
    os.environ["GEMINI_API_KEY"] = "test-api-key"
    os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["ALLOWED_EMAILS"] = "test@example.com,allowed@example.com"
    from importlib import reload

    import src.config

    reload(src.config)


class TestLangdetectLanguages:
    """LANGDETECT_LANGUAGES must name at least two shipped langdetect profiles."""

    def test_default_is_valid(self) -> None:
        from src.config import Config

        assert not [e for e in Config.validate() if "LANGDETECT_LANGUAGES" in e]

    def test_unknown_code_is_rejected(self) -> None:
        from src.config import Config

        with patch.object(Config, "LANGDETECT_LANGUAGES", ["cs", "xx"]):
            errors = Config.validate()
        assert any("LANGDETECT_LANGUAGES" in e and "xx" in e for e in errors)

    def test_single_language_is_rejected(self) -> None:
        from src.config import Config

        with patch.object(Config, "LANGDETECT_LANGUAGES", ["cs"]):
            errors = Config.validate()
        assert any("LANGDETECT_LANGUAGES" in e for e in errors)


class TestAuthCannotFailOpen:
    """A missing or wrong environment setting must never switch authentication off."""

    def _reloaded_config(self, env: dict[str, str]) -> type:
        from importlib import reload

        import src.config

        with patch.dict(os.environ, env):
            reload(src.config)
            return src.config.Config

    def test_unset_flask_env_means_production(self) -> None:
        # load_dotenv never overrides a set variable, so "" stands in for "not set"
        config = self._reloaded_config({"FLASK_ENV": "", "E2E_TESTING": ""})
        assert config.FLASK_ENV == "production"
        assert config.should_bypass_auth() is False

    def test_e2e_flag_is_ignored_outside_testing(self) -> None:
        config = self._reloaded_config({"FLASK_ENV": "production", "E2E_TESTING": "true"})
        with patch.dict(os.environ, {"E2E_TESTING": "true"}):
            assert config.should_bypass_auth() is False

    def test_e2e_flag_bypasses_auth_in_testing(self) -> None:
        config = self._reloaded_config({"FLASK_ENV": "testing", "E2E_TESTING": "true"})
        with patch.dict(os.environ, {"E2E_TESTING": "true"}):
            assert config.should_bypass_auth() is True

    def test_create_app_refuses_an_invalid_production_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gunicorn starts the app through create_app(), never main()."""
        import src.app

        monkeypatch.setattr(src.app.Config, "FLASK_ENV", "production")
        monkeypatch.setattr(src.app.Config, "JWT_SECRET_KEY", "dev-secret-change-me")
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            src.app.create_app()


class TestTokenEncryptionKeyRequired:
    """Without the key, OAuth tokens and the Rouvy password are stored in plaintext."""

    def _production_errors(self, monkeypatch: pytest.MonkeyPatch, key: str) -> list[str]:
        from src.config import Config

        monkeypatch.setattr(Config, "FLASK_ENV", "production")
        monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", key)
        return Config.validate()

    def test_missing_key_is_an_error_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        errors = self._production_errors(monkeypatch, "")
        assert any("TOKEN_ENCRYPTION_KEY" in e for e in errors)

    def test_invalid_key_is_an_error_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        errors = self._production_errors(monkeypatch, "not-a-fernet-key")
        assert any("TOKEN_ENCRYPTION_KEY" in e for e in errors)

    def test_valid_key_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        errors = self._production_errors(monkeypatch, Fernet.generate_key().decode())
        assert not any("TOKEN_ENCRYPTION_KEY" in e for e in errors)

    def test_development_needs_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "FLASK_ENV", "development")
        monkeypatch.setattr(Config, "TOKEN_ENCRYPTION_KEY", "")
        assert not any("TOKEN_ENCRYPTION_KEY" in e for e in Config.validate())


class TestValidateCharacterization:
    """Every message validate() can produce, word for word and in order."""

    def test_every_error_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        for name, value in {
            "GEMINI_API_KEY": "",
            "FLASK_ENV": "production",
            "GOOGLE_CLIENT_ID": "",
            "ALLOWED_EMAILS": [],
            "JWT_SECRET_KEY": "dev-secret-change-me",
            "TOKEN_ENCRYPTION_KEY": "",
            "LANGDETECT_LANGUAGES": ["cs"],
            "PORT": 0,
            "MAX_FILE_SIZE": 0,
            "MAX_VIDEO_FILE_SIZE": -1,
            "MAX_REQUEST_SIZE": -2,
            "MAX_FILES_PER_MESSAGE": 0,
            "COST_CURRENCY": "XYZ",
            "LOG_LEVEL": "LOUD",
        }.items():
            monkeypatch.setattr(Config, name, value)
        currencies = ", ".join(sorted(Config.CURRENCY_RATES))

        assert Config.validate() == [
            "GEMINI_API_KEY is required. "
            "Get your API key from https://ai.google.dev/ and set it in .env",
            "GOOGLE_CLIENT_ID is required in production. "
            "Set up OAuth at https://console.cloud.google.com/apis/credentials "
            "or set FLASK_ENV=development to skip authentication",
            "ALLOWED_EMAILS is required in production. "
            "Set a comma-separated list of allowed email addresses "
            "or set FLASK_ENV=development to skip authentication",
            "JWT_SECRET_KEY must be set to a secure random value in production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"',
            "TOKEN_ENCRYPTION_KEY is required in production. Generate one with: make token-key",
            "LANGDETECT_LANGUAGES needs at least two language codes (e.g. cs,en)",
            "PORT must be between 1 and 65535, got 0",
            "MAX_FILE_SIZE must be positive, got 0",
            "MAX_VIDEO_FILE_SIZE must be positive, got -1",
            "MAX_REQUEST_SIZE (-2) must be at least 1.4x "
            "MAX_VIDEO_FILE_SIZE (-1) to fit a base64-encoded video",
            "MAX_FILES_PER_MESSAGE must be at least 1, got 0",
            f"COST_CURRENCY 'XYZ' is not supported. Valid currencies: {currencies}",
            "LOG_LEVEL 'LOUD' is not valid. Valid levels: CRITICAL, DEBUG, ERROR, INFO, WARNING",
        ]

    def test_short_jwt_secret_and_other_bad_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        for name, value in {
            "FLASK_ENV": "production",
            "JWT_SECRET_KEY": "too-short-key",
            "TOKEN_ENCRYPTION_KEY": "not-a-fernet-key",
            "LANGDETECT_LANGUAGES": ["cs", "xx", "yy"],
            "PORT": 65536,
            "MAX_VIDEO_FILE_SIZE": 100,
            "MAX_REQUEST_SIZE": 139,
        }.items():
            monkeypatch.setattr(Config, name, value)

        assert Config.validate() == [
            "JWT_SECRET_KEY must be at least 32 characters for security (got 13). "
            'Generate a secure key with: python -c "import secrets; print(secrets.token_hex(32))"',
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: make token-key",
            "LANGDETECT_LANGUAGES has codes with no langdetect profile: xx, yy",
            "PORT must be between 1 and 65535, got 65536",
            "MAX_REQUEST_SIZE (139) must be at least 1.4x "
            "MAX_VIDEO_FILE_SIZE (100) to fit a base64-encoded video",
        ]

    def test_development_skips_the_production_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        for name, value in {
            "FLASK_ENV": "development",
            "GOOGLE_CLIENT_ID": "",
            "ALLOWED_EMAILS": [],
            "JWT_SECRET_KEY": "dev-secret-change-me",
            "TOKEN_ENCRYPTION_KEY": "",
        }.items():
            monkeypatch.setattr(Config, name, value)
        assert Config.validate() == []


class TestTimezoneSettings:
    def test_defaults(self) -> None:
        from src.config import Config

        assert Config._timezone_errors() == []

    @pytest.mark.parametrize("zone", ["UTC", "Europe/Prague", "Pacific/Chatham"])
    def test_valid_zones(self, monkeypatch: pytest.MonkeyPatch, zone: str) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "APP_TIMEZONE", zone)
        monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", zone)
        assert Config._timezone_errors() == []

    @pytest.mark.parametrize("zone", ["Mars/Olympus", "CEST+2", "", "../etc/passwd"])
    def test_invalid_app_timezone(self, monkeypatch: pytest.MonkeyPatch, zone: str) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "APP_TIMEZONE", zone)
        errors = Config.validate()
        assert any(e.startswith("APP_TIMEZONE") for e in errors)

    def test_empty_legacy_zone_means_the_host_zone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "")
        assert Config._timezone_errors() == []

    def test_invalid_legacy_zone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "Europe/Atlantis")
        assert Config._timezone_errors() == [
            "LEGACY_TIMESTAMP_TIMEZONE 'Europe/Atlantis' is not a valid IANA timezone "
            "(e.g. 'Europe/Prague', 'UTC')"
        ]
