"""Integration tests for Garmin Connect API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

import src.api.routes.garmin as garmin_module
from src.auth.garmin_auth import GarminAuthError, GarminMfaRequired
from src.db.models import Database, User


@pytest.fixture(autouse=True)
def clear_mfa_pending():
    """Clear the MFA pending state before and after each test."""
    garmin_module._mfa_pending.clear()
    yield
    garmin_module._mfa_pending.clear()


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

    def test_connect_mfa_required(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """Should return mfa_required=True when account has MFA enabled."""
        mock_garmin_client = MagicMock()
        mfa_context = {"signin_params": "some-params", "client": mock_garmin_client}

        with patch("src.api.routes.garmin.authenticate") as mock_auth:
            mock_auth.side_effect = GarminMfaRequired(mock_garmin_client, mfa_context)

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

        # MFA pending state should be stored for the user
        assert test_user.id in garmin_module._mfa_pending

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

    def test_mfa_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Should complete MFA login with valid code."""
        mock_garmin_client = MagicMock()
        mfa_context = {"signin_params": "some-params"}

        # Seed the pending MFA state
        import time

        garmin_module._mfa_pending[test_user.id] = {
            "garmin": mock_garmin_client,
            "mfa_context": mfa_context,
            "created_at": time.time(),
        }

        with patch("src.api.routes.garmin.complete_mfa_login") as mock_mfa:
            mock_mfa.return_value = ("base64-token-string", "Jane Doe")

            response = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "123456"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["mfa_required"] is False
        assert data["display_name"] == "Jane Doe"

        # MFA state should be cleaned up after success
        assert test_user.id not in garmin_module._mfa_pending

    def test_mfa_no_pending_session(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when there is no pending MFA session."""
        response = client.post(
            "/auth/garmin/mfa",
            headers=auth_headers,
            json={"mfa_code": "123456"},
        )

        assert response.status_code == 400

    def test_mfa_invalid_code(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Should return 400 when MFA code is invalid."""
        mock_garmin_client = MagicMock()
        mfa_context = {"signin_params": "some-params"}

        import time

        garmin_module._mfa_pending[test_user.id] = {
            "garmin": mock_garmin_client,
            "mfa_context": mfa_context,
            "created_at": time.time(),
        }

        with patch("src.api.routes.garmin.complete_mfa_login") as mock_mfa:
            mock_mfa.side_effect = GarminAuthError("Invalid MFA code. Please try again.")

            response = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "000000"},
            )

        assert response.status_code == 400

    def test_mfa_concurrent_second_request_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Second concurrent MFA request should get 400 (pop removes state)."""
        mock_garmin_client = MagicMock()
        mfa_context = {"signin_params": "some-params"}

        import time

        garmin_module._mfa_pending[test_user.id] = {
            "garmin": mock_garmin_client,
            "mfa_context": mfa_context,
            "created_at": time.time(),
        }

        with patch("src.api.routes.garmin.complete_mfa_login") as mock_mfa:
            mock_mfa.return_value = ("base64-token-string", "Jane Doe")

            # First request succeeds and pops the pending state
            response1 = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "123456"},
            )
            assert response1.status_code == 200

            # Second request gets 400 — state was already consumed
            response2 = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "123456"},
            )
            assert response2.status_code == 400

        assert test_user.id not in garmin_module._mfa_pending

    def test_mfa_invalid_code_allows_retry(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Invalid MFA code should re-store state so user can retry."""
        mock_garmin_client = MagicMock()
        mfa_context = {"signin_params": "some-params"}

        import time

        garmin_module._mfa_pending[test_user.id] = {
            "garmin": mock_garmin_client,
            "mfa_context": mfa_context,
            "created_at": time.time(),
        }

        with patch("src.api.routes.garmin.complete_mfa_login") as mock_mfa:
            # First attempt: invalid code
            mock_mfa.side_effect = GarminAuthError("Invalid MFA code. Please try again.")
            response1 = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "000000"},
            )
            assert response1.status_code == 400
            # State should be re-stored for retry
            assert test_user.id in garmin_module._mfa_pending

            # Second attempt: correct code
            mock_mfa.side_effect = None
            mock_mfa.return_value = ("base64-token-string", "Jane Doe")
            response2 = client.post(
                "/auth/garmin/mfa",
                headers=auth_headers,
                json={"mfa_code": "123456"},
            )
            assert response2.status_code == 200
            data = response2.get_json()
            assert data["connected"] is True

        assert test_user.id not in garmin_module._mfa_pending

    def test_mfa_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/auth/garmin/mfa",
            json={"mfa_code": "123456"},
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
