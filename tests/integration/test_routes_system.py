"""Integration tests for the system routes (health, readiness, version, models, upload config)."""

from flask.testing import FlaskClient


class TestSystemRoutes:
    def test_health(self, client: FlaskClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_ready(self, client: FlaskClient) -> None:
        response = client.get("/api/ready")
        assert response.status_code == 200

    def test_version(self, client: FlaskClient) -> None:
        response = client.get("/api/version")
        assert response.status_code == 200
        assert "version" in response.get_json()

    def test_models_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/models").status_code == 401

    def test_models_lists_configured_models(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/models", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["models"]) > 0
        assert data["default"]

    def test_upload_config(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/api/config/upload", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["maxFileSize"] > 0
        assert len(data["allowedFileTypes"]) > 0
        assert data["maxVideoFileSize"] == 100 * 1024 * 1024
        assert "video/mp4" in data["allowedFileTypes"]
