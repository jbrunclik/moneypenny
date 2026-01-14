"""Integration tests for health check routes."""

import json
from unittest.mock import patch

from flask.testing import FlaskClient


class TestHealthCheck:
    """Tests for GET /api/health endpoint (liveness probe)."""

    def test_returns_ok_status(self, client: FlaskClient) -> None:
        """Should return ok status when application is running."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"

    def test_includes_version(self, client: FlaskClient) -> None:
        """Should include app version in response."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "version" in data

    def test_no_auth_required(self, client: FlaskClient) -> None:
        """Should work without authentication."""
        # No auth headers
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_does_not_check_database(self, client: FlaskClient) -> None:
        """Liveness probe should not check database (quick response)."""
        # Even with broken database, health should return ok
        with patch("src.db.models.check_database_connectivity", return_value=(False, "DB error")):
            response = client.get("/api/health")

        # Should still return 200 - liveness only checks if app is responding
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ok"


class TestReadinessCheck:
    """Tests for GET /api/ready endpoint (readiness probe)."""

    def test_returns_ready_when_healthy(self, client: FlaskClient) -> None:
        """Should return ready status when all dependencies are available."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "ready"

    def test_includes_checks(self, client: FlaskClient) -> None:
        """Should include individual check results."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "checks" in data
        assert "database" in data["checks"]
        assert data["checks"]["database"]["status"] == "ok"

    def test_includes_version(self, client: FlaskClient) -> None:
        """Should include app version in response."""
        response = client.get("/api/ready")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "version" in data

    def test_no_auth_required(self, client: FlaskClient) -> None:
        """Should work without authentication."""
        # No auth headers
        response = client.get("/api/ready")
        assert response.status_code == 200

    def test_returns_503_when_database_unavailable(self, client: FlaskClient) -> None:
        """Should return 503 when database is not accessible."""
        with patch(
            "src.api.routes.system.check_database_connectivity",
            return_value=(False, "Database connection failed"),
        ):
            response = client.get("/api/ready")

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["status"] == "not_ready"
        assert data["checks"]["database"]["status"] == "error"
        assert "Database connection failed" in data["checks"]["database"]["message"]

    def test_database_check_error_message(self, client: FlaskClient) -> None:
        """Should include database error message in checks."""
        error_msg = "Permission denied accessing database file"
        with patch(
            "src.api.routes.system.check_database_connectivity",
            return_value=(False, error_msg),
        ):
            response = client.get("/api/ready")

        assert response.status_code == 503
        data = json.loads(response.data)
        assert error_msg in data["checks"]["database"]["message"]


class TestVersionEndpoint:
    """Tests for GET /api/version endpoint."""

    def test_returns_version(self, client: FlaskClient) -> None:
        """Should return app version."""
        response = client.get("/api/version")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "version" in data

    def test_no_auth_required(self, client: FlaskClient) -> None:
        """Should work without authentication."""
        response = client.get("/api/version")
        assert response.status_code == 200
