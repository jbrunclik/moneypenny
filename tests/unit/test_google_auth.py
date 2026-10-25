"""Unit tests for src/auth/google_auth.py."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.auth.google_auth import (
    GoogleAuthError,
    is_email_allowed,
    verify_google_id_token,
)


class TestVerifyGoogleIdToken:
    """Tests for verify_google_id_token function."""

    @patch("src.auth.google_auth.httpx.get")
    @patch("src.auth.google_auth.Config.GOOGLE_CLIENT_ID", "test-client-id")
    def test_valid_token_returns_user_info(self, mock_get: MagicMock) -> None:
        """Valid token should return user info dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            "email": "user@example.com",
            "name": "Test User",
            "picture": "https://example.com/pic.jpg",
            "email_verified": "true",
        }
        mock_get.return_value = mock_response

        result = verify_google_id_token("valid-token")

        assert result["email"] == "user@example.com"
        assert result["name"] == "Test User"
        assert result["picture"] == "https://example.com/pic.jpg"
        assert result["email_verified"] is True

    @patch("src.auth.google_auth.httpx.get")
    @patch("src.auth.google_auth.Config.GOOGLE_CLIENT_ID", "test-client-id")
    def test_email_verified_false(self, mock_get: MagicMock) -> None:
        """Should handle email_verified being false."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            "email": "user@example.com",
            "name": "Test User",
            "email_verified": "false",
        }
        mock_get.return_value = mock_response

        result = verify_google_id_token("valid-token")

        assert result["email_verified"] is False

    @patch("src.auth.google_auth.httpx.get")
    @patch("src.auth.google_auth.Config.GOOGLE_CLIENT_ID", "test-client-id")
    def test_uses_email_as_name_fallback(self, mock_get: MagicMock) -> None:
        """Should use email as name if name is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            "email": "user@example.com",
            # No name field
            "email_verified": "true",
        }
        mock_get.return_value = mock_response

        result = verify_google_id_token("valid-token")

        assert result["name"] == "user@example.com"

    @patch("src.auth.google_auth.httpx.get")
    def test_invalid_token_raises_error(self, mock_get: MagicMock) -> None:
        """Invalid token (HTTP error) should raise GoogleAuthError."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        with pytest.raises(GoogleAuthError, match="Invalid ID token"):
            verify_google_id_token("invalid-token")

    @patch("src.auth.google_auth.httpx.get")
    @patch("src.auth.google_auth.Config.GOOGLE_CLIENT_ID", "test-client-id")
    def test_wrong_audience_raises_error(self, mock_get: MagicMock) -> None:
        """Token with wrong audience should raise GoogleAuthError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "wrong-client-id",
            "email": "user@example.com",
        }
        mock_get.return_value = mock_response

        with pytest.raises(GoogleAuthError, match="not issued for this application"):
            verify_google_id_token("token-wrong-audience")

    @patch("src.auth.google_auth.httpx.get")
    @patch("src.auth.google_auth.Config.GOOGLE_CLIENT_ID", "test-client-id")
    def test_missing_email_raises_error(self, mock_get: MagicMock) -> None:
        """Token without email should raise GoogleAuthError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            # No email field
        }
        mock_get.return_value = mock_response

        with pytest.raises(GoogleAuthError, match="does not contain email"):
            verify_google_id_token("token-no-email")

    @patch("src.auth.google_auth.httpx.get")
    def test_request_exception_raises_error(self, mock_get: MagicMock) -> None:
        """Request exception should raise GoogleAuthError."""
        mock_get.side_effect = httpx.ConnectError("Network error")

        with pytest.raises(GoogleAuthError, match="Failed to verify token"):
            verify_google_id_token("token")

    @patch("src.auth.google_auth.httpx.get")
    def test_timeout_raises_error(self, mock_get: MagicMock) -> None:
        """Timeout should raise GoogleAuthError."""
        mock_get.side_effect = httpx.ReadTimeout("Request timed out")

        with pytest.raises(GoogleAuthError, match="Failed to verify token"):
            verify_google_id_token("token")


class TestIsEmailAllowed:
    """Tests for is_email_allowed function."""

    @patch(
        "src.auth.google_auth.Config.ALLOWED_EMAILS",
        ["allowed@example.com", "admin@test.com"],
    )
    def test_allowed_email_returns_true(self) -> None:
        """Allowed emails should return True."""
        assert is_email_allowed("allowed@example.com") is True
        assert is_email_allowed("admin@test.com") is True

    @patch(
        "src.auth.google_auth.Config.ALLOWED_EMAILS",
        ["allowed@example.com"],
    )
    def test_not_allowed_email_returns_false(self) -> None:
        """Non-allowed emails should return False."""
        assert is_email_allowed("hacker@evil.com") is False
        assert is_email_allowed("other@example.com") is False

    @patch(
        "src.auth.google_auth.Config.ALLOWED_EMAILS",
        ["Allowed@Example.com"],
    )
    def test_case_insensitive_comparison(self) -> None:
        """Email comparison should be case insensitive."""
        assert is_email_allowed("allowed@example.com") is True
        assert is_email_allowed("ALLOWED@EXAMPLE.COM") is True
        assert is_email_allowed("Allowed@Example.Com") is True

    @patch("src.auth.google_auth.Config.ALLOWED_EMAILS", [])
    def test_empty_allowed_list(self) -> None:
        """Empty allowed list should deny all emails."""
        assert is_email_allowed("any@example.com") is False

    @patch(
        "src.auth.google_auth.Config.ALLOWED_EMAILS",
        ["test@example.com"],
    )
    def test_email_with_different_domain(self) -> None:
        """Different domains should not match."""
        assert is_email_allowed("test@other.com") is False
        assert is_email_allowed("test@example.org") is False
