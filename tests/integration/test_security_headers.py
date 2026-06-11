"""Integration tests for the security headers added in app.py (S10)."""

from unittest.mock import patch

from flask.testing import FlaskClient


class TestSecurityHeaders:
    """Every response carries the baseline security headers."""

    def test_baseline_headers_on_api_response(self, client: FlaskClient) -> None:
        response = client.get("/api/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"
        assert "microphone=(self)" in response.headers["Permissions-Policy"]

    def test_no_cors_headers(self, client: FlaskClient) -> None:
        """The API is same-origin only - no Access-Control-Allow-Origin anywhere."""
        response = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_hsts_only_over_https(self, client: FlaskClient) -> None:
        plain = client.get("/api/health")
        assert "Strict-Transport-Security" not in plain.headers

        proxied = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
        assert "max-age=" in proxied.headers["Strict-Transport-Security"]

    def test_csp_in_production_mode(self, client: FlaskClient) -> None:
        from src.config import Config

        with patch.object(Config, "FLASK_ENV", "production"):
            response = client.get("/api/health")
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "https://accounts.google.com" in csp

    def test_no_csp_in_development_mode(self, client: FlaskClient) -> None:
        from src.config import Config

        with patch.object(Config, "FLASK_ENV", "development"):
            response = client.get("/api/health")
        assert "Content-Security-Policy" not in response.headers
