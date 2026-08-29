"""Integration tests for the Rouvy connect/status/disconnect routes.

The headless login is mocked — no live Rouvy calls in tests.
"""

from unittest.mock import patch

from src.auth.rouvy_auth import RouvyAuthError


def test_connect_stores_credentials(client, auth_headers, test_user, test_database):
    with patch("src.api.routes.rouvy.login", return_value="[]") as login:
        r = client.post(
            "/auth/rouvy/connect",
            json={"email": "e@x.com", "password": "pw"},
            headers=auth_headers,
        )
    assert r.status_code == 200
    assert r.json["connected"] is True
    assert login.called
    u = test_database.get_user_by_id(test_user.id)
    assert u.rouvy_email == "e@x.com"
    assert u.rouvy_session == "[]"


def test_connect_bad_credentials_returns_400(client, auth_headers):
    with patch("src.api.routes.rouvy.login", side_effect=RouvyAuthError("wrong")):
        r = client.post(
            "/auth/rouvy/connect",
            json={"email": "e@x.com", "password": "bad"},
            headers=auth_headers,
        )
    assert r.status_code == 400


def test_disconnect_clears(client, auth_headers, test_user, test_database):
    test_database.update_user_rouvy_credentials(test_user.id, "e@x.com", "pw", "[]")
    r = client.post("/auth/rouvy/disconnect", headers=auth_headers)
    assert r.status_code == 200
    assert test_database.get_user_by_id(test_user.id).rouvy_session is None


def test_status_reports_connected(client, auth_headers, test_user, test_database):
    test_database.update_user_rouvy_credentials(
        test_user.id, "e@x.com", "pw", '[{"name":"s","value":"v"}]'
    )
    r = client.get("/auth/rouvy/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json["connected"] is True
    assert r.json["needs_reconnect"] is False


def test_status_reports_disconnected(client, auth_headers):
    r = client.get("/auth/rouvy/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json["connected"] is False
