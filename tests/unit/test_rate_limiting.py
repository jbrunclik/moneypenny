"""Unit tests for rate limiting functionality."""

from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask, g

from src.api.rate_limiting import (
    get_rate_limit_key,
    init_rate_limiting,
)
from src.config import Config
from src.db.models import User
from src.utils.rate_limit_storage import SQLiteStorage


class TestGetRateLimitKey:
    """Tests for the get_rate_limit_key function."""

    def test_returns_user_key_when_authenticated(self, app: Flask) -> None:
        """Test that authenticated requests use user ID for rate limiting."""
        with app.app_context():
            # Set up authenticated user in g
            g.user = User(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                picture=None,
                created_at=datetime.now(),
                custom_instructions=None,
            )

            key = get_rate_limit_key()

            assert key == "user:test-user-123"

    def test_returns_ip_key_when_unauthenticated(self, app: Flask) -> None:
        """Test that unauthenticated requests use IP address for rate limiting."""
        with (
            app.app_context(),
            app.test_request_context("/api/version", environ_base={"REMOTE_ADDR": "192.168.1.1"}),
        ):
            # Ensure no user is set
            if hasattr(g, "user"):
                delattr(g, "user")

            key = get_rate_limit_key()

            assert key == "ip:192.168.1.1"

    def test_returns_ip_key_when_user_is_none(self, app: Flask) -> None:
        """Test that requests with g.user=None use IP address."""
        with (
            app.app_context(),
            app.test_request_context("/api/version", environ_base={"REMOTE_ADDR": "10.0.0.1"}),
        ):
            g.user = None

            key = get_rate_limit_key()

            assert key == "ip:10.0.0.1"


class TestInitRateLimiting:
    """Tests for the init_rate_limiting function."""

    def test_returns_none_when_disabled(self, app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that init_rate_limiting returns None when rate limiting is disabled."""
        monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", False)

        limiter = init_rate_limiting(app)

        assert limiter is None

    def test_returns_limiter_when_enabled(
        self, app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that init_rate_limiting returns a Limiter when enabled."""
        monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", True)
        monkeypatch.setattr(Config, "RATE_LIMIT_STORAGE_URI", "memory://")
        monkeypatch.setattr(Config, "RATE_LIMIT_DEFAULT", "100 per minute")

        limiter = init_rate_limiting(app)

        assert limiter is not None

    def test_registers_429_error_handler(self, app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that init_rate_limiting registers a 429 error handler."""
        monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", True)
        monkeypatch.setattr(Config, "RATE_LIMIT_STORAGE_URI", "memory://")

        init_rate_limiting(app)

        # Check that error handler is registered
        assert 429 in app.error_handler_spec.get(None, {})


class TestRateLimitIntegration:
    """Integration tests for rate limiting with Flask test client."""

    def test_health_endpoint_exempt_from_rate_limiting(
        self, client: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that health endpoint is exempt from rate limiting."""
        monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", True)

        # Health endpoint should always work, even with very strict limits
        for _ in range(100):
            response = client.get("/api/health")
            assert response.status_code == 200

    def test_version_endpoint_exempt_from_rate_limiting(
        self, client: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that version endpoint is exempt from rate limiting."""
        monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", True)

        # Version endpoint should always work
        for _ in range(100):
            response = client.get("/api/version")
            assert response.status_code == 200


def _limited_app(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Flask:
    """A bare app whose only route carries the default limit of 2 per minute."""
    monkeypatch.setattr(Config, "RATE_LIMITING_ENABLED", True)
    monkeypatch.setattr(Config, "RATE_LIMIT_STORAGE_URI", "sqlite://")
    monkeypatch.setattr(Config, "RATE_LIMIT_DB_PATH", db_path)
    monkeypatch.setattr(Config, "RATE_LIMIT_DEFAULT", "2 per minute")
    flask_app = Flask(__name__)

    @flask_app.route("/ping")
    def ping() -> str:
        return "pong"

    init_rate_limiting(flask_app)
    return flask_app


class TestSQLiteStorageEnforcement:
    """The limiter enforces limits through the shared SQLite storage."""

    def test_limit_enforced_and_counted_in_the_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "ratelimits.db"
        client = _limited_app(monkeypatch, db_path).test_client()

        statuses = [client.get("/ping").status_code for _ in range(3)]

        assert statuses == [200, 200, 429]
        # A second worker (here: a fresh storage on the same file) sees the hits
        assert SQLiteStorage("sqlite://", path=str(db_path)).reset() == 1

    def test_storage_failure_fails_open(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The directory does not exist, so every storage call errors
        client = _limited_app(monkeypatch, tmp_path / "missing" / "rl.db").test_client()

        statuses = [client.get("/ping").status_code for _ in range(3)]

        # Fell back to per-worker memory counting: still limited, never a 500
        assert statuses == [200, 200, 429]


class TestRateLimitErrorFormat:
    """Tests for rate limit error response format."""

    def test_error_response_format(self, app: Flask) -> None:
        """Test that rate limit errors use our standard error format."""
        from src.api.errors import ErrorCode, is_retryable

        # Verify error code and retryability
        assert ErrorCode.RATE_LIMITED.value == "RATE_LIMITED"
        assert is_retryable(ErrorCode.RATE_LIMITED) is True
