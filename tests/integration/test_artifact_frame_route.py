"""The sandboxed artifact frame page and its own security headers."""

from unittest.mock import patch

from flask.testing import FlaskClient

from src.app import build_frame_csp
from src.config import Config

_PROD_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
)


def test_production_frame_csp_is_exact() -> None:
    assert build_frame_csp(dev_mode=False) == _PROD_CSP


def test_dev_frame_csp_allows_only_the_vite_server_on_top() -> None:
    csp = build_frame_csp(dev_mode=True)
    assert "script-src 'self' 'unsafe-inline' http://localhost:5173" in csp
    assert "connect-src ws://localhost:5173" in csp
    assert "http://localhost:5173" not in build_frame_csp(dev_mode=False)


def test_frame_route_headers_in_production(client: FlaskClient) -> None:
    with patch.object(Config, "FLASK_ENV", "production"):
        response = client.get("/artifact-frame")
    # 500 when the frontend is not built; the headers hold either way
    assert response.status_code in (200, 500)
    assert response.headers["Content-Security-Policy"] == _PROD_CSP
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Cache-Control"] == "no-cache"
    assert "Set-Cookie" not in response.headers


def test_frame_route_renders_the_shell_in_dev(client: FlaskClient) -> None:
    with patch.object(Config, "FLASK_ENV", "development"):
        response = client.get("/artifact-frame")
    assert response.status_code == 200
    assert "src/artifact/frame.ts" in response.get_data(as_text=True)


def test_app_csp_allows_same_origin_frames(client: FlaskClient) -> None:
    with patch.object(Config, "FLASK_ENV", "production"):
        response = client.get("/api/health")
    assert (
        "frame-src https://accounts.google.com 'self'"
        in response.headers["Content-Security-Policy"]
    )
    assert response.headers["X-Frame-Options"] == "DENY"
