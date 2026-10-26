"""Unit tests for src/auth/garmin_auth.py.

Mocks use ``spec=Garmin`` so that attribute access matches the real
``garminconnect.Garmin`` class; this guards against silent breakage when
upstream renames attributes (e.g. the ``.garth`` -> ``.client`` rename in
garminconnect 0.3.x).
"""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from garminconnect import Garmin
from garminconnect import client as garmin_client

from src.auth.garmin_auth import (
    GarminAuthError,
    GarminMfaRequired,
    authenticate,
    authenticate_with_mfa,
    bound_request_timeouts,
    create_client_from_tokens,
    serialize_tokens,
)
from src.config import Config


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

            with pytest.raises(GarminAuthError, match=r"[Rr]ate limited"):
                authenticate_with_mfa("u@x.com", "pw", "123456")


_TIMEOUT_SECONDS = 7  # distinct from garminconnect's own 15/30 s defaults


def _ok_response(request: Any) -> Any:
    """A real 200 JSON response (requests is only reachable through garminconnect)."""
    response = garmin_client.requests.Response()
    response.status_code = 200
    response._content = b"{}"
    response.headers["Content-Type"] = "application/json"
    response.request = request
    response.url = request.url
    return response


def _build_with_tokens() -> Any:
    return create_client_from_tokens("t" * 600)


def _build_with_password() -> Any:
    with patch("src.auth.garmin_auth.serialize_tokens", return_value="tokens"):
        authenticate("user@example.com", "secret")


def _build_with_mfa() -> Any:
    with patch("src.auth.garmin_auth.serialize_tokens", return_value="tokens"):
        authenticate_with_mfa("user@example.com", "secret", "123456")


class TestRequestTimeout:
    """Every Garmin client we build bounds its HTTP calls with GARMIN_API_TIMEOUT (S5)."""

    @pytest.fixture
    def sent(self) -> Any:
        """Fake transport: record (adapter, timeout) per request, answer 200 {}."""
        calls: list[tuple[Any, Any]] = []

        def fake_send(adapter: Any, request: Any, **kwargs: Any) -> Any:
            calls.append((adapter, kwargs.get("timeout")))
            return _ok_response(request)

        with (
            patch.object(garmin_client.HTTPAdapter, "send", autospec=True, side_effect=fake_send),
            patch.object(Config, "GARMIN_API_TIMEOUT", _TIMEOUT_SECONDS),
        ):
            yield calls

    @pytest.fixture
    def built(self) -> Any:
        """Capture the Garmin client a builder creates; login itself is a no-op."""
        clients: list[Garmin] = []

        def fake_login(garmin: Garmin, *args: Any, **kwargs: Any) -> tuple[object, object]:
            clients.append(garmin)
            return (object(), object())

        with patch.object(Garmin, "login", autospec=True, side_effect=fake_login):
            yield clients

    @pytest.mark.parametrize("build", [_build_with_tokens, _build_with_password, _build_with_mfa])
    def test_every_session_uses_the_configured_timeout(
        self, build: Any, built: list[Garmin], sent: list[tuple[Any, Any]]
    ) -> None:
        build()
        client = built[0].client
        original_adapter = client._api_session.adapters["https://"]._inner

        # An API call through the library's own request path (which passes 15 s)
        with patch.object(client, "get_api_headers", return_value={}):
            built[0].connectapi("/userprofile-service/socialProfile")
        # The SSO / token-refresh session (the library passes 10-30 s)
        client.cs.get("https://sso.garmin.com/sso/embed", timeout=30)

        assert [timeout for _, timeout in sent] == [_TIMEOUT_SECONDS, _TIMEOUT_SECONDS]
        # Delegates to the library's own adapter: pools and retries unchanged
        assert sent[0][0] is original_adapter

    def test_applying_twice_does_not_double_wrap(self, sent: list[tuple[Any, Any]]) -> None:
        garmin = Garmin()
        bound_request_timeouts(garmin)
        bound_request_timeouts(garmin)

        adapter = garmin.client._api_session.adapters["https://"]
        assert not hasattr(adapter._inner, "_inner")

    def test_curl_cffi_session_gets_the_timeout_as_its_default(self) -> None:
        if not garmin_client.HAS_CFFI:
            pytest.skip("curl_cffi not installed")
        garmin = Garmin()
        garmin.client.cs = garmin_client.cffi_requests.Session()

        with patch.object(Config, "GARMIN_API_TIMEOUT", _TIMEOUT_SECONDS):
            bound_request_timeouts(garmin)

        assert garmin.client.cs.timeout == _TIMEOUT_SECONDS

    def test_missing_session_logs_a_warning_and_bounds_the_rest(
        self, sent: list[tuple[Any, Any]], caplog: pytest.LogCaptureFixture
    ) -> None:
        """A library upgrade that renames a session must not break Garmin."""
        garmin = Garmin()
        del garmin.client._api_session

        with caplog.at_level(logging.WARNING, logger="src.auth.garmin_auth"):
            bound_request_timeouts(garmin)

        warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
        assert warning.__dict__["session"] == "_api_session"
        garmin.client.cs.get("https://sso.garmin.com/sso/embed")
        assert [timeout for _, timeout in sent] == [_TIMEOUT_SECONDS]

    def test_missing_client_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        garmin = MagicMock(spec=[])

        with caplog.at_level(logging.WARNING, logger="src.auth.garmin_auth"):
            bound_request_timeouts(garmin)

        assert any(r.levelno == logging.WARNING for r in caplog.records)
