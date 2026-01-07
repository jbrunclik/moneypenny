"""Unit tests for rate limiting functionality."""

from datetime import datetime

import pytest
from flask import Flask, g

from src.api.rate_limiting import (
    get_rate_limit_key,
    init_rate_limiting,
)
from src.config import Config
from src.db.models import User


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
        with app.app_context():
            with app.test_request_context(
                "/api/version", environ_base={"REMOTE_ADDR": "192.168.1.1"}
            ):
                # Ensure no user is set
                if hasattr(g, "user"):
                    delattr(g, "user")

                key = get_rate_limit_key()

                assert key == "ip:192.168.1.1"

    def test_returns_ip_key_when_user_is_none(self, app: Flask) -> None:
        """Test that requests with g.user=None use IP address."""
        with app.app_context():
            with app.test_request_context("/api/version", environ_base={"REMOTE_ADDR": "10.0.0.1"}):
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


class TestRateLimitErrorFormat:
    """Tests for rate limit error response format."""

    def test_error_response_format(self, app: Flask) -> None:
        """Test that rate limit errors use our standard error format."""
        from src.api.errors import ErrorCode, is_retryable

        # Verify error code and retryability
        assert ErrorCode.RATE_LIMITED.value == "RATE_LIMITED"
        assert is_retryable(ErrorCode.RATE_LIMITED) is True
