"""Tests for proxy-aware client IP handling (ProxyFix wiring).

Rate limiting keys on request.remote_addr for unauthenticated requests;
behind the TLS-terminating reverse proxy that must be the real client IP
from X-Forwarded-For - but only when the proxy is trusted, otherwise the
header is client-spoofable.
"""

from unittest.mock import patch

from flask import Flask, request

from src.app import apply_proxy_fix
from src.config import Config


def _make_echo_app() -> Flask:
    app = Flask(__name__)

    @app.route("/ip")
    def ip() -> str:
        return f"{request.remote_addr}|{'https' if request.is_secure else 'http'}"

    return app


def test_forwarded_headers_honored_behind_trusted_proxy() -> None:
    app = _make_echo_app()
    with patch.object(Config, "TRUSTED_PROXY_COUNT", 1):
        apply_proxy_fix(app)  # type: ignore[arg-type]

    response = app.test_client().get(
        "/ip",
        headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.get_data(as_text=True) == "203.0.113.7|https"


def test_only_the_last_hop_is_trusted() -> None:
    """A client prepending fake entries to X-Forwarded-For cannot spoof its IP."""
    app = _make_echo_app()
    with patch.object(Config, "TRUSTED_PROXY_COUNT", 1):
        apply_proxy_fix(app)  # type: ignore[arg-type]

    response = app.test_client().get(
        "/ip",
        headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.7"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.get_data(as_text=True).startswith("203.0.113.7|")


def test_forwarded_headers_ignored_without_trusted_proxy() -> None:
    app = _make_echo_app()
    with patch.object(Config, "TRUSTED_PROXY_COUNT", 0):
        apply_proxy_fix(app)  # type: ignore[arg-type]

    response = app.test_client().get(
        "/ip",
        headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.get_data(as_text=True) == "127.0.0.1|http"
