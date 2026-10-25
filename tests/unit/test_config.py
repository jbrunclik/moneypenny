"""Unit tests for configuration validation."""

import os
from unittest.mock import patch

import pytest


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
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "GEMINI_API_KEY": "test-key",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "ALLOWED_EMAILS": "test@example.com",
                # JWT secret must be at least 32 characters in production
                "JWT_SECRET_KEY": "secure-production-key-1234567890123456",
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
