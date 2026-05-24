"""Integration tests for Garmin Connect API endpoints."""

from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

from src.auth.garmin_auth import GarminAuthError, GarminMfaRequired
from src.db.models import Database, User


class TestConnectGarmin:
    """Tests for POST /auth/garmin/connect."""

    def test_connect_success(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should connect Garmin account with valid credentials."""
        with patch("src.api.routes.garmin.authenticate") as mock_auth:
            mock_auth.return_value = ("base64-token-string", "John Doe")

            response = client.post(
                "/auth/garmin/connect",
                headers=auth_headers,
                json={"email": "user@garmin.com", "password": "secret123"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["mfa_required"] is False
        assert data["display_name"] == "John Doe"

    def test_connect_mfa_required(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return mfa_required=True when account has MFA enabled."""
        with patch("src.api.routes.garmin.authenticate") as mock_auth:
            mock_auth.side_effect = GarminMfaRequired()

            response = client.post(
                "/auth/garmin/connect",
                headers=auth_headers,
                json={"email": "user@garmin.com", "password": "secret123"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is False
        assert data["mfa_required"] is True
        assert data["display_name"] is None

    def test_connect_invalid_credentials(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when credentials are invalid."""
        with patch("src.api.routes.garmin.authenticate") as mock_auth:
            mock_auth.side_effect = GarminAuthError("Invalid email or password")

            response = client.post(
                "/auth/garmin/connect",
                headers=auth_headers,
                json={"email": "user@garmin.com", "password": "wrongpassword"},
            )

        assert response.status_code == 400

    def test_connect_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/auth/garmin/connect",
            json={"email": "user@garmin.com", "password": "secret123"},
        )
        assert response.status_code == 401


class TestGarminMfa:
    """Tests for POST /auth/garmin/mfa."""

    def test_mfa_success(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should complete login with email+password+MFA code in a single request."""
        with patch("src.api.routes.garmin.authenticate_with_mfa") as mock_mfa:
            mock_mfa.return_value = ("base64-token-string", "Jane Doe")

            response = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={
                    "email": "user@garmin.com",
                    "password": "secret123",
                    "mfa_code": "123456",
                },
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["mfa_required"] is False
        assert data["display_name"] == "Jane Doe"
        mock_mfa.assert_called_once_with("user@garmin.com", "secret123", "123456")

    def test_mfa_missing_credentials(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when email or password is missing."""
        response = client.post(
            "/auth/garmin/mfa",
            headers=auth_headers,
            json={"mfa_code": "123456"},
        )
        assert response.status_code == 400

    def test_mfa_invalid_code(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 and surface the real backend message for a bad code."""
        with patch("src.api.routes.garmin.authenticate_with_mfa") as mock_mfa:
            mock_mfa.side_effect = GarminAuthError("Invalid MFA code. Please try again.")

            response = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={
                    "email": "user@garmin.com",
                    "password": "secret123",
                    "mfa_code": "000000",
                },
            )

        assert response.status_code == 400
        assert "Invalid MFA code" in response.get_json()["error"]["message"]

    def test_mfa_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/auth/garmin/mfa",
            json={
                "email": "user@garmin.com",
                "password": "secret123",
                "mfa_code": "123456",
            },
        )
        assert response.status_code == 401


class TestDisconnectGarmin:
    """Tests for POST /auth/garmin/disconnect."""

    def test_disconnect_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should disconnect Garmin by clearing stored token."""
        # First connect Garmin by setting a token directly
        test_database.update_user_garmin_token(test_user.id, "base64-token-string")

        response = client.post("/auth/garmin/disconnect", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "disconnected"

        # Verify token was cleared
        user = test_database.get_user_by_id(test_user.id)
        assert user.garmin_token is None

    def test_disconnect_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/auth/garmin/disconnect")
        assert response.status_code == 401


class TestGetGarminStatus:
    """Tests for GET /auth/garmin/status."""

    def test_status_not_connected(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return not connected when no token stored."""
        response = client.get("/auth/garmin/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is False
        assert data["needs_reconnect"] is False

    def test_status_connected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should return connected status when valid token stored."""
        test_database.update_user_garmin_token(test_user.id, "base64-token-string")

        with patch("src.api.routes.garmin.create_client_from_tokens") as mock_create:
            mock_garmin_client = MagicMock()
            mock_create.return_value = mock_garmin_client

            response = client.get("/auth/garmin/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["needs_reconnect"] is False

    def test_status_needs_reconnect(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should return needs_reconnect=True when stored token is expired or invalid."""
        test_database.update_user_garmin_token(test_user.id, "expired-token-string")

        with patch("src.api.routes.garmin.create_client_from_tokens") as mock_create:
            mock_create.side_effect = GarminAuthError(
                "Session expired. Please reconnect your Garmin account."
            )

            response = client.get("/auth/garmin/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["needs_reconnect"] is True

    def test_status_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/auth/garmin/status")
        assert response.status_code == 401
