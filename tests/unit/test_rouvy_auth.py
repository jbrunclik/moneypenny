"""Tests for the Rouvy auth module (Playwright login mocked)."""

import json

import pytest

from src.auth import rouvy_auth
from src.auth.rouvy_auth import RouvyAuthError


def test_cookies_to_jar():
    session = json.dumps(
        [
            {"name": "a", "value": "1", "domain": ".rouvy.com"},
            {"name": "b", "value": "2", "domain": ".rouvy.com"},
        ]
    )
    assert rouvy_auth.cookies_to_jar(session) == {"a": "1", "b": "2"}


def test_cookies_to_jar_bad_input():
    assert rouvy_auth.cookies_to_jar("not json") == {}
    assert rouvy_auth.cookies_to_jar("{}") == {}


def test_login_success(monkeypatch):
    fake = [{"name": "rouvy_session", "value": "xyz", "domain": ".rouvy.com"}]
    monkeypatch.setattr(rouvy_auth, "_login_sync", lambda e, p: json.dumps(fake))
    out = rouvy_auth.login("e@x.com", "pw")
    assert json.loads(out)[0]["name"] == "rouvy_session"


def test_login_invalid_credentials(monkeypatch):
    def boom(e, p):
        raise RuntimeError("email or password is wrong")

    monkeypatch.setattr(rouvy_auth, "_login_sync", boom)
    with pytest.raises(RouvyAuthError, match="email or password"):
        rouvy_auth.login("e@x.com", "pw")


def test_login_captcha_classified(monkeypatch):
    def boom(e, p):
        raise RuntimeError("recaptcha challenge blocked")

    monkeypatch.setattr(rouvy_auth, "_login_sync", boom)
    with pytest.raises(RouvyAuthError, match="captcha"):
        rouvy_auth.login("e@x.com", "pw")


def test_login_timeout(monkeypatch):
    import time

    monkeypatch.setattr(rouvy_auth.Config, "ROUVY_LOGIN_TIMEOUT_MS", 1)
    monkeypatch.setattr(rouvy_auth, "_LOGIN_JOIN_BUFFER_SECONDS", 0.0)
    monkeypatch.setattr(rouvy_auth, "_login_sync", lambda e, p: time.sleep(1))
    with pytest.raises(RouvyAuthError, match="timed out"):
        rouvy_auth.login("e@x.com", "pw")
