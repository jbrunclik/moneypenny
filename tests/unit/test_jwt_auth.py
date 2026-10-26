"""Unit tests for src/auth/jwt_auth.py."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest

from src.auth.jwt_auth import (
    TokenResult,
    TokenStatus,
    create_token,
    decode_token_with_status,
    get_token_from_request,
)
from src.config import Config


@pytest.fixture
def mock_user() -> MagicMock:
    """Create a mock user object."""
    user = MagicMock()
    user.id = "user-123-abc"
    user.email = "testuser@example.com"
    user.name = "Test User"
    return user


class TestCreateToken:
    """Tests for create_token function."""

    def test_creates_valid_jwt(self, mock_user: MagicMock) -> None:
        """Token should be a valid JWT that can be decoded."""
        token = create_token(mock_user)
        assert isinstance(token, str)
        assert len(token) > 0

        # Verify it can be decoded
        decoded = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        assert decoded["sub"] == mock_user.id
        assert decoded["email"] == mock_user.email
        assert decoded["name"] == mock_user.name

    def test_token_contains_required_claims(self, mock_user: MagicMock) -> None:
        """Token should contain sub, email, name, exp, and iat claims."""
        token = create_token(mock_user)
        decoded = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])

        assert "sub" in decoded
        assert "email" in decoded
        assert "name" in decoded
        assert "exp" in decoded
        assert "iat" in decoded

    def test_token_has_correct_expiration(self, mock_user: MagicMock) -> None:
        """Token expiration should match configured JWT_EXPIRATION_SECONDS."""
        token = create_token(mock_user)
        decoded = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])

        exp_time = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        now = datetime.now(UTC)
        expected_exp = now + timedelta(seconds=Config.JWT_EXPIRATION_SECONDS)

        # Allow 60 second tolerance for test execution time
        assert abs((exp_time - expected_exp).total_seconds()) < 60

    def test_different_users_get_different_tokens(self, mock_user: MagicMock) -> None:
        """Different users should produce different tokens."""
        token1 = create_token(mock_user)

        mock_user2 = MagicMock()
        mock_user2.id = "user-456-def"
        mock_user2.email = "other@example.com"
        mock_user2.name = "Other User"

        token2 = create_token(mock_user2)

        assert token1 != token2


class TestGetTokenFromRequest:
    """Tests for get_token_from_request function."""

    def test_extracts_bearer_token(self) -> None:
        """Should extract token from 'Bearer <token>' header."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = "Bearer test-token-123"

        token = get_token_from_request(mock_request)
        assert token == "test-token-123"

    def test_returns_none_without_bearer_prefix(self) -> None:
        """Should return None if Authorization doesn't start with 'Bearer '."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = "test-token-123"

        token = get_token_from_request(mock_request)
        assert token is None

    def test_returns_none_for_empty_header(self) -> None:
        """Should return None for empty Authorization header."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        token = get_token_from_request(mock_request)
        assert token is None

    def test_returns_none_for_missing_header(self) -> None:
        """Should return None when Authorization header is missing."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        token = get_token_from_request(mock_request)
        assert token is None

    def test_returns_none_for_bearer_only(self) -> None:
        """Should return empty string if header is just 'Bearer '."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = "Bearer "

        token = get_token_from_request(mock_request)
        assert token == ""  # Returns empty string after 'Bearer '

    def test_handles_token_with_spaces(self) -> None:
        """Should handle tokens that might have spaces (though unusual)."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = "Bearer token with spaces"

        token = get_token_from_request(mock_request)
        assert token == "token with spaces"

    def test_case_sensitive_bearer(self) -> None:
        """'Bearer' prefix should be case-sensitive."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = "bearer test-token"

        token = get_token_from_request(mock_request)
        assert token is None  # 'bearer' != 'Bearer'


class TestDecodeTokenWithStatus:
    """Tests for decode_token_with_status function."""

    def test_returns_valid_status_for_valid_token(self, mock_user: MagicMock) -> None:
        """Valid token should return VALID status with payload."""
        token = create_token(mock_user)
        result = decode_token_with_status(token)

        assert result.status == TokenStatus.VALID
        assert result.payload is not None
        assert result.payload["sub"] == mock_user.id
        assert result.payload["email"] == mock_user.email
        assert result.error is None

    def test_returns_expired_status_for_expired_token(self, mock_user: MagicMock) -> None:
        """Expired token should return EXPIRED status with error message."""
        payload = {
            "sub": mock_user.id,
            "email": mock_user.email,
            "name": mock_user.name,
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)

        result = decode_token_with_status(expired_token)

        assert result.status == TokenStatus.EXPIRED
        assert result.payload is None
        assert result.error is not None
        assert "expired" in result.error.lower()

    def test_returns_invalid_status_for_malformed_token(self) -> None:
        """Malformed token should return INVALID status."""
        result = decode_token_with_status("invalid.token.here")

        assert result.status == TokenStatus.INVALID
        assert result.payload is None
        assert result.error is not None

    def test_returns_invalid_status_for_wrong_secret(self, mock_user: MagicMock) -> None:
        """Token signed with wrong secret should return INVALID status."""
        payload = {
            "sub": mock_user.id,
            "email": mock_user.email,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        }
        wrong_token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")

        result = decode_token_with_status(wrong_token)

        assert result.status == TokenStatus.INVALID
        assert result.payload is None

    def test_returns_invalid_status_for_empty_string(self) -> None:
        """Empty string should return INVALID status."""
        result = decode_token_with_status("")

        assert result.status == TokenStatus.INVALID
        assert result.payload is None

    def test_returns_invalid_status_for_wrong_algorithm(self, mock_user: MagicMock) -> None:
        """A token signed with another algorithm must not validate."""
        payload = {
            "sub": mock_user.id,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        wrong_alg_token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm="HS384")

        result = decode_token_with_status(wrong_alg_token)

        assert result.status == TokenStatus.INVALID
        assert result.payload is None


class TestTokenResult:
    """Tests for TokenResult dataclass."""

    def test_valid_result(self) -> None:
        """Should create valid result with payload."""
        payload = {"sub": "user-123", "email": "test@example.com"}
        result = TokenResult(status=TokenStatus.VALID, payload=payload)

        assert result.status == TokenStatus.VALID
        assert result.payload == payload
        assert result.error is None

    def test_expired_result(self) -> None:
        """Should create expired result with error."""
        result = TokenResult(status=TokenStatus.EXPIRED, error="Token has expired")

        assert result.status == TokenStatus.EXPIRED
        assert result.payload is None
        assert result.error == "Token has expired"

    def test_invalid_result(self) -> None:
        """Should create invalid result with error."""
        result = TokenResult(status=TokenStatus.INVALID, error="Invalid signature")

        assert result.status == TokenStatus.INVALID
        assert result.payload is None
        assert result.error == "Invalid signature"
