"""Integration tests for authentication routes."""

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import jwt
from flask.testing import FlaskClient

from src.config import Config

if TYPE_CHECKING:
    from src.db.models import User


class TestGoogleAuthRoute:
    """Tests for POST /auth/google endpoint."""

    def test_successful_login_new_user(
        self, client: FlaskClient, mock_google_tokeninfo: MagicMock
    ) -> None:
        """Should create user and return JWT on successful Google auth."""
        response = client.post(
            "/auth/google",
            json={"credential": "valid-google-token"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == "test@example.com"

    def test_successful_login_existing_user(
        self,
        client: FlaskClient,
        mock_google_tokeninfo: MagicMock,
        test_user: User,
    ) -> None:
        """Should return JWT for existing user."""
        response = client.post(
            "/auth/google",
            json={"credential": "valid-google-token"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["user"]["id"] == test_user.id

    def test_login_refreshes_a_changed_google_profile(
        self,
        client: FlaskClient,
        mock_google_tokeninfo: MagicMock,
        test_database,
    ) -> None:
        """The avatar and name were stored once at first login and never
        refreshed; a fresh Google login must pick up a new photo/name."""
        test_database.get_or_create_user(
            email="test@example.com", name="Old Name", picture="https://example.com/old.jpg"
        )

        response = client.post("/auth/google", json={"credential": "valid-google-token"})

        data = json.loads(response.data)
        assert data["user"]["picture"] == "https://example.com/pic.jpg"
        assert data["user"]["name"] == "Test User"
        stored = test_database.get_user_by_id(data["user"]["id"])
        assert stored.picture == "https://example.com/pic.jpg"
        assert stored.name == "Test User"

    def test_missing_token(self, client: FlaskClient) -> None:
        """Should return 400 when token is missing."""
        response = client.post("/auth/google", json={})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_invalid_token(self, client: FlaskClient) -> None:
        """Should return 401 for invalid Google token."""
        with patch("src.auth.google_auth.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_get.return_value = mock_response

            response = client.post(
                "/auth/google",
                json={"credential": "invalid-token"},
            )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert "error" in data

    def test_email_not_allowed(self, client: FlaskClient) -> None:
        """Should return 403 when email is not in allowed list."""
        with patch("src.auth.google_auth.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "aud": "test-client-id",
                "email": "unauthorized@example.com",
                "name": "Unauthorized User",
                "email_verified": "true",
            }
            mock_get.return_value = mock_response

            response = client.post(
                "/auth/google",
                json={"credential": "valid-token"},
            )

        assert response.status_code == 403
        data = json.loads(response.data)
        # Error can be string or structured object
        error = data["error"]
        error_message = error["message"] if isinstance(error, dict) else error
        assert "not authorized" in error_message.lower()


class TestAuthMeRoute:
    """Tests for GET /auth/me endpoint."""

    def test_returns_current_user(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """Should return current authenticated user info."""
        response = client.get("/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["user"]["id"] == test_user.id
        assert data["user"]["email"] == test_user.email
        assert data["user"]["name"] == test_user.name

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without auth token."""
        response = client.get("/auth/me")

        assert response.status_code == 401
        data = json.loads(response.data)
        assert "error" in data

    def test_invalid_token(self, client: FlaskClient) -> None:
        """Should return 401 for invalid token."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401


class TestAuthClientIdRoute:
    """Tests for GET /auth/client-id endpoint."""

    def test_returns_client_id(self, client: FlaskClient) -> None:
        """Should return Google Client ID (no auth required)."""
        response = client.get("/auth/client-id")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "client_id" in data
        assert data["client_id"] == "test-client-id"

    def test_no_auth_required(self, client: FlaskClient) -> None:
        """Should work without authentication."""
        # No auth headers
        response = client.get("/auth/client-id")
        assert response.status_code == 200


class TestAuthRefreshRoute:
    """Tests for POST /auth/refresh endpoint."""

    def test_returns_new_token(
        self, client: FlaskClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """Should return a new JWT token with extended expiration."""
        response = client.post("/auth/refresh", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "token" in data

        # Verify the new token is valid and has correct claims
        decoded = jwt.decode(
            data["token"],
            Config.JWT_SECRET_KEY,
            algorithms=[Config.JWT_ALGORITHM],
        )
        assert decoded["sub"] == test_user.id
        assert decoded["email"] == test_user.email

    def test_new_token_has_extended_expiration(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """New token should have a fresh expiration time."""
        response = client.post("/auth/refresh", headers=auth_headers)
        data = json.loads(response.data)

        decoded = jwt.decode(
            data["token"],
            Config.JWT_SECRET_KEY,
            algorithms=[Config.JWT_ALGORITHM],
        )

        exp_time = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        now = datetime.now(UTC)
        expected_exp = now + timedelta(seconds=Config.JWT_EXPIRATION_SECONDS)

        # Allow 60 second tolerance for test execution time
        assert abs((exp_time - expected_exp).total_seconds()) < 60

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without auth token."""
        response = client.post("/auth/refresh")

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"]["code"] == "AUTH_REQUIRED"

    def test_returns_auth_expired_for_expired_token(
        self, client: FlaskClient, test_user: User
    ) -> None:
        """Should return AUTH_EXPIRED error code for expired token."""
        # Create an expired token
        payload = {
            "sub": test_user.id,
            "email": test_user.email,
            "name": test_user.name,
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)

        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"]["code"] == "AUTH_EXPIRED"
        assert "expired" in data["error"]["message"].lower()


class TestAuthErrorCodes:
    """Tests for standardized auth error responses."""

    def test_missing_token_returns_auth_required(self, client: FlaskClient) -> None:
        """Missing token should return AUTH_REQUIRED error code."""
        response = client.get("/auth/me")

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"]["code"] == "AUTH_REQUIRED"
        assert data["error"]["retryable"] is False

    def test_invalid_token_returns_auth_invalid(self, client: FlaskClient) -> None:
        """Invalid/malformed token should return AUTH_INVALID error code."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"]["code"] == "AUTH_INVALID"
        assert data["error"]["retryable"] is False

    def test_expired_token_returns_auth_expired(self, client: FlaskClient, test_user: User) -> None:
        """Expired token should return AUTH_EXPIRED error code."""
        # Create an expired token
        payload = {
            "sub": test_user.id,
            "email": test_user.email,
            "name": test_user.name,
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)

        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data["error"]["code"] == "AUTH_EXPIRED"
        assert "expired" in data["error"]["message"].lower()
        assert data["error"]["retryable"] is False
