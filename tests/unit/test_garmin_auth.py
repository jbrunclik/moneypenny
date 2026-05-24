"""Unit tests for src/auth/garmin_auth.py.

Mocks use ``spec=Garmin`` so that attribute access matches the real
``garminconnect.Garmin`` class; this guards against silent breakage when
upstream renames attributes (e.g. the ``.garth`` -> ``.client`` rename in
garminconnect 0.3.x).
"""

from unittest.mock import MagicMock, patch

import pytest
from garminconnect import Garmin

from src.auth.garmin_auth import (
    GarminAuthError,
    GarminMfaRequired,
    authenticate,
    authenticate_with_mfa,
    serialize_tokens,
)


class TestSerializeTokens:
    """Tests for serialize_tokens()."""

    def test_uses_client_dumps(self) -> None:
        """serialize_tokens must read tokens from garmin.client.dumps()."""
        garmin = MagicMock(spec=Garmin)
        garmin.client = MagicMock()
        garmin.client.dumps.return_value = "serialized-tokens"

        result = serialize_tokens(garmin)

        assert result == "serialized-tokens"
        garmin.client.dumps.assert_called_once()

    def test_raises_garmin_auth_error_on_failure(self) -> None:
        """Any exception from dumps() should be wrapped in GarminAuthError."""
        garmin = MagicMock(spec=Garmin)
        garmin.client = MagicMock()
        garmin.client.dumps.side_effect = RuntimeError("boom")

        with pytest.raises(GarminAuthError, match="Failed to save session tokens"):
            serialize_tokens(garmin)


class TestAuthenticate:
    """Tests for authenticate()."""

    def test_mfa_required_raises_marker_exception(self) -> None:
        """When Garmin returns ('needs_mfa', ...), raise GarminMfaRequired with no payload."""
        with patch("garminconnect.Garmin") as mock_cls:
            instance = MagicMock(spec=Garmin)
            instance.login.return_value = ("needs_mfa", None)
            mock_cls.return_value = instance

            with pytest.raises(GarminMfaRequired):
                authenticate("user@example.com", "secret")

    def test_no_mfa_returns_serialized_tokens(self) -> None:
        """Without MFA, login should serialize via client.dumps() and return tokens."""
        with patch("garminconnect.Garmin") as mock_cls:
            instance = MagicMock(spec=Garmin)
            instance.login.return_value = (object(), object())
            instance.client = MagicMock()
            instance.client.dumps.return_value = "tokens-b64"
            instance.display_name = "John"
            mock_cls.return_value = instance

            tokens, display_name = authenticate("user@example.com", "secret")

        assert tokens == "tokens-b64"
        assert display_name == "John"


class TestAuthenticateWithMfa:
    """Tests for authenticate_with_mfa()."""

    def test_success_passes_code_via_prompt_mfa(self) -> None:
        """The supplied mfa_code should be wired through as the prompt_mfa callback."""
        with patch("garminconnect.Garmin") as mock_cls:
            instance = MagicMock(spec=Garmin)
            instance.client = MagicMock()
            instance.client.dumps.return_value = "fresh-tokens"
            instance.display_name = "Jane Runner"
            mock_cls.return_value = instance

            tokens, display_name = authenticate_with_mfa("u@x.com", "pw", "123456")

        assert tokens == "fresh-tokens"
        assert display_name == "Jane Runner"

        # The Garmin client must be constructed with a prompt_mfa callable
        # that, when invoked, returns the user's MFA code.
        _, kwargs = mock_cls.call_args
        assert kwargs["email"] == "u@x.com"
        assert kwargs["password"] == "pw"
        assert callable(kwargs["prompt_mfa"])
        assert kwargs["prompt_mfa"]() == "123456"

    def test_invalid_code_maps_to_clear_error(self) -> None:
        """Garmin's 'invalid verification code' surfaces as a user-friendly message."""
        with patch("garminconnect.Garmin") as mock_cls:
            instance = MagicMock(spec=Garmin)
            instance.login.side_effect = Exception("Invalid MFA verification code")
            mock_cls.return_value = instance

            with pytest.raises(GarminAuthError, match="Invalid MFA code"):
                authenticate_with_mfa("u@x.com", "pw", "000000")

    def test_rate_limit_maps_to_clear_error(self) -> None:
        with patch("garminconnect.Garmin") as mock_cls:
            instance = MagicMock(spec=Garmin)
            instance.login.side_effect = Exception("Rate limited by Garmin (429)")
            mock_cls.return_value = instance

            with pytest.raises(GarminAuthError, match="[Rr]ate limited"):
                authenticate_with_mfa("u@x.com", "pw", "123456")
