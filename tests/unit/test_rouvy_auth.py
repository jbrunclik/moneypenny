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


def test_merge_cookie_values_updates_and_appends():
    session = json.dumps(
        [
            {"name": "rouvy_session", "value": "old", "domain": ".rouvy.com", "httpOnly": True},
            {"name": "locale", "value": "en", "domain": ".rouvy.com"},
        ]
    )
    out = json.loads(
        rouvy_auth.merge_cookie_values(session, {"rouvy_session": "new", "GAESA": "aff"})
    )
    by_name = {c["name"]: c for c in out}
    assert by_name["rouvy_session"]["value"] == "new"
    assert by_name["rouvy_session"]["httpOnly"] is True  # other attrs preserved
    assert by_name["locale"]["value"] == "en"
    assert by_name["GAESA"]["value"] == "aff"
    assert len(out) == 3


def test_merge_cookie_values_bad_input():
    out = json.loads(rouvy_auth.merge_cookie_values("not json", {"rouvy_session": "x"}))
    assert out == [{"name": "rouvy_session", "value": "x", "domain": ".rouvy.com"}]


def test_login_success(monkeypatch):
    fake = [{"name": "rouvy_session", "value": "xyz", "domain": ".rouvy.com"}]
    session = json.dumps({"cookies": fake, "user_agent": "UA"})
    monkeypatch.setattr(rouvy_auth, "_login_sync", lambda e, p: session)
    out = rouvy_auth.login("e@x.com", "pw")
    assert rouvy_auth.cookies_to_jar(out) == {"rouvy_session": "xyz"}
    assert rouvy_auth.session_user_agent(out) == "UA"


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

    def slow_login(_email: str, _password: str) -> None:
        time.sleep(1)  # a login past its timeout

    monkeypatch.setattr(rouvy_auth, "_login_sync", slow_login)
    with pytest.raises(RouvyAuthError, match="timed out"):
        rouvy_auth.login("e@x.com", "pw")


def test_browser_user_agent_drops_the_headless_marker():
    """Rouvy's riders site (Cloudflare) blocks "HeadlessChrome" since Nov 2026."""
    headless = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "HeadlessChrome/141.0.7390.37 Safari/537.36"
    )
    ua = rouvy_auth.browser_user_agent(headless)
    assert "Headless" not in ua
    assert "Chrome/141.0.7390.37" in ua
    assert ua.startswith("Mozilla/5.0 (X11; Linux x86_64)")


def test_login_presents_the_ordinary_browser_name(monkeypatch):
    """The login context gets the browser's own user agent minus "Headless"."""
    contexts: list[dict[str, object]] = []

    class Page:
        def evaluate(self, _script):
            return "Mozilla/5.0 (X11) HeadlessChrome/141.0 Safari/537.36"

        def close(self):
            pass

    class Browser:
        def new_page(self):
            return Page()

        def new_context(self, **kwargs):
            contexts.append(kwargs)
            raise RuntimeError("stop after the context")

        def close(self):
            pass

    class Chromium:
        def launch(self, **_kwargs):
            return Browser()

    class Playwright:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: Playwright())
    with pytest.raises(RuntimeError):
        rouvy_auth._login_sync("a@b.c", "pw")
    assert contexts == [{"user_agent": "Mozilla/5.0 (X11) Chrome/141.0 Safari/537.36"}]


_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def test_a_session_carries_the_user_agent_it_was_issued_to():
    """Since Nov 2026 the session blob is {"cookies": [...], "user_agent": ...}:
    Rouvy's Cloudflare lets requests through with the login's browser identity."""
    session = json.dumps(
        {
            "cookies": [{"name": "rouvy_session", "value": "v", "domain": ".rouvy.com"}],
            "user_agent": _UA,
        }
    )
    assert rouvy_auth.cookies_to_jar(session) == {"rouvy_session": "v"}
    assert rouvy_auth.session_user_agent(session) == _UA


def test_an_old_cookie_list_session_falls_back_to_a_browser_identity():
    session = json.dumps([{"name": "rouvy_session", "value": "v", "domain": ".rouvy.com"}])
    assert rouvy_auth.cookies_to_jar(session) == {"rouvy_session": "v"}
    ua = rouvy_auth.session_user_agent(session)
    assert ua == rouvy_auth.FALLBACK_USER_AGENT
    assert "Chrome/" in ua and "Headless" not in ua


def test_merging_rotated_cookies_keeps_the_user_agent():
    session = json.dumps(
        {
            "cookies": [{"name": "rouvy_session", "value": "old", "domain": ".rouvy.com"}],
            "user_agent": _UA,
        }
    )
    merged = rouvy_auth.merge_cookie_values(session, {"rouvy_session": "new"})
    assert rouvy_auth.cookies_to_jar(merged) == {"rouvy_session": "new"}
    assert rouvy_auth.session_user_agent(merged) == _UA
