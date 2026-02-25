"""Integration tests for Google Calendar API endpoints."""

from datetime import datetime, timedelta
from unittest.mock import patch

from flask.testing import FlaskClient

from src.auth.google_calendar import GoogleCalendarAuthError
from src.db.models import Database, User


class TestGetCalendarAuthUrl:
    """Tests for GET /auth/calendar/auth-url."""

    def test_get_auth_url_success(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return auth URL when calendar is configured."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch("src.api.routes.calendar.get_google_calendar_auth_url") as mock_url:
                mock_url.return_value = "https://accounts.google.com/o/oauth2/v2/auth?..."
                response = client.get("/auth/calendar/auth-url", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert "auth_url" in data
        assert "state" in data

    def test_get_auth_url_not_configured(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when calendar is not configured."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=False):
            response = client.get("/auth/calendar/auth-url", headers=auth_headers)

        assert response.status_code == 400

    def test_get_auth_url_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/auth/calendar/auth-url")
        assert response.status_code == 401


class TestConnectGoogleCalendar:
    """Tests for POST /auth/calendar/connect."""

    def test_connect_success(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should connect calendar with valid code."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch(
                "src.api.routes.calendar.exchange_calendar_code_for_tokens"
            ) as mock_exchange:
                mock_exchange.return_value = {
                    "access_token": "test-access-token",
                    "refresh_token": "test-refresh-token",
                    "expires_in": 3600,
                }
                with patch("src.api.routes.calendar.get_google_calendar_user_info") as mock_user:
                    mock_user.return_value = {"email": "user@example.com"}

                    response = client.post(
                        "/auth/calendar/connect",
                        headers=auth_headers,
                        json={"code": "test-code", "state": "test-state"},
                    )

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["calendar_email"] == "user@example.com"

    def test_connect_not_configured(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when calendar is not configured."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=False):
            response = client.post(
                "/auth/calendar/connect",
                headers=auth_headers,
                json={"code": "test-code", "state": "test-state"},
            )

        assert response.status_code == 400

    def test_connect_exchange_fails(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 400 when token exchange fails."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch(
                "src.api.routes.calendar.exchange_calendar_code_for_tokens"
            ) as mock_exchange:
                mock_exchange.side_effect = GoogleCalendarAuthError("Exchange failed")

                response = client.post(
                    "/auth/calendar/connect",
                    headers=auth_headers,
                    json={"code": "invalid-code", "state": "test-state"},
                )

        assert response.status_code == 400

    def test_connect_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/auth/calendar/connect",
            json={"code": "test-code", "state": "test-state"},
        )
        assert response.status_code == 401


class TestDisconnectGoogleCalendar:
    """Tests for POST /auth/calendar/disconnect."""

    def test_disconnect_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should disconnect calendar."""
        # First connect calendar and set custom selected IDs
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="test-token",
            refresh_token="refresh-token",
            expires_at=datetime.now() + timedelta(hours=1),
            email="user@example.com",
        )
        test_database.update_user_calendar_selected_ids(
            test_user.id, ["primary", "old-calendar-id@group.calendar.google.com"]
        )

        response = client.post("/auth/calendar/disconnect", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "disconnected"

        # Verify token was cleared and selected IDs were reset
        user = test_database.get_user_by_id(test_user.id)
        assert user.google_calendar_access_token is None
        assert user.google_calendar_selected_ids == ["primary"]

    def test_disconnect_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/auth/calendar/disconnect")
        assert response.status_code == 401


class TestGetCalendarStatus:
    """Tests for GET /auth/calendar/status."""

    def test_status_not_connected(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return not connected when no token stored."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            response = client.get("/auth/calendar/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is False
        assert data["calendar_email"] is None

    def test_status_connected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should return connected status with email."""
        # Connect calendar
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="test-token",
            refresh_token="refresh-token",
            expires_at=datetime.now() + timedelta(hours=1),
            email="user@example.com",
        )

        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch("src.api.routes.calendar.get_google_calendar_user_info") as mock_user:
                mock_user.return_value = {"email": "user@example.com"}
                response = client.get("/auth/calendar/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["calendar_email"] == "user@example.com"

    def test_status_needs_reconnect_when_refresh_fails(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should set needs_reconnect when token refresh fails."""
        # Connect calendar with expired token
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="expired-token",
            refresh_token="refresh-token",
            expires_at=datetime.now() - timedelta(hours=1),  # Expired
            email="user@example.com",
        )

        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch("src.api.routes.calendar.refresh_google_calendar_token") as mock_refresh:
                mock_refresh.side_effect = GoogleCalendarAuthError("Refresh failed")

                response = client.get("/auth/calendar/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["needs_reconnect"] is True

    def test_status_proactive_refresh(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Should proactively refresh token expiring within 5 minutes."""
        # Connect calendar with token expiring in 3 minutes
        test_database.update_user_google_calendar_tokens(
            test_user.id,
            access_token="expiring-token",
            refresh_token="refresh-token",
            expires_at=datetime.now() + timedelta(minutes=3),
            email="user@example.com",
        )

        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=True):
            with patch("src.api.routes.calendar.refresh_google_calendar_token") as mock_refresh:
                mock_refresh.return_value = {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                }
                with patch("src.api.routes.calendar.get_google_calendar_user_info") as mock_user:
                    mock_user.return_value = {"email": "user@example.com"}

                    response = client.get("/auth/calendar/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is True
        assert data["needs_reconnect"] is False

        # Verify token was refreshed
        mock_refresh.assert_called_once()

    def test_status_not_configured(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return not connected when not configured."""
        with patch("src.api.routes.calendar._is_google_calendar_configured", return_value=False):
            response = client.get("/auth/calendar/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["connected"] is False

    def test_status_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/auth/calendar/status")
        assert response.status_code == 401
