"""The sandboxed artifact frame page and its own security headers."""

from unittest.mock import patch

from flask.testing import FlaskClient

from src.app import build_frame_csp
from src.config import Config

# Only the app's explicit origin, never 'self': in an opaque-origin sandbox
# WebKit matched nothing against 'self' for scripts, yet let images from ANY
# origin through (Oct 11 2026 probe); an explicit origin is enforced by both
_ORIGIN = "https://app.example"
_PROD_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "script-src https://app.example 'unsafe-inline'; "
    "style-src https://app.example 'unsafe-inline'; "
    "img-src https://app.example data: blob:; font-src https://app.example data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
)


def test_production_frame_csp_is_exact() -> None:
    assert build_frame_csp(dev_mode=False, origin=_ORIGIN) == _PROD_CSP


def test_dev_frame_csp_allows_only_the_vite_server_on_top() -> None:
    csp = build_frame_csp(dev_mode=True, origin=_ORIGIN)
    assert "script-src https://app.example 'unsafe-inline' http://localhost:5173" in csp
    assert "connect-src ws://localhost:5173" in csp
    assert "http://localhost:5173" not in build_frame_csp(dev_mode=False, origin=_ORIGIN)


def test_frame_route_headers_in_production(client: FlaskClient) -> None:
    # No APP_URL: the request's own origin (the local .env may set one)
    with patch.object(Config, "FLASK_ENV", "production"), patch.object(Config, "APP_URL", ""):
        response = client.get("/artifact-frame")
    # 500 when the frontend is not built; the headers hold either way
    assert response.status_code in (200, 500)
    # The test client's origin
    assert response.headers["Content-Security-Policy"] == _PROD_CSP.replace(
        _ORIGIN, "http://localhost"
    )
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


def test_built_assets_allow_the_opaque_frame_origin(client: FlaskClient) -> None:
    # The sandboxed frame's origin is "null": its module script and fonts are
    # CORS fetches, so the public bundle files must allow any origin
    response = client.get("/static/assets/artifact-frame.js")
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    preflight = client.options("/static/assets/artifact-frame.js")
    assert preflight.headers["Access-Control-Allow-Origin"] == "*"


def test_api_still_sends_no_cors_headers(client: FlaskClient) -> None:
    response = client.get("/api/health", headers={"Origin": "null"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_frame_starts_in_the_requested_theme(client: FlaskClient) -> None:
    with patch.object(Config, "FLASK_ENV", "development"):
        light = client.get("/artifact-frame?theme=light").get_data(as_text=True)
        dark = client.get("/artifact-frame?theme=evil%22").get_data(as_text=True)
    assert '<html lang="en" data-theme="light">' in light
    assert "data-theme" not in dark.split("<head>")[0]


def test_frame_csp_uses_the_configured_public_origin(client: FlaskClient) -> None:
    # APP_URL, when set, wins over the request's Host header
    with (
        patch.object(Config, "FLASK_ENV", "production"),
        patch.object(Config, "APP_URL", "https://app.example/"),
    ):
        response = client.get("/artifact-frame", headers={"Host": "evil.example"})
    csp = response.headers["Content-Security-Policy"]
    assert "script-src https://app.example 'unsafe-inline'" in csp
    assert "evil.example" not in csp
