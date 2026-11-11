"""Rouvy authentication via headless Playwright login.

Rouvy has no public API. This drives the account.rouvy.com email->password
sign-in flow headlessly and extracts the resulting .rouvy.com session cookies,
which then authenticate direct httpx calls to riders.rouvy.com.

Unlike Garmin, the password IS stored (Fernet-encrypted, by the caller) so the
short-lived session can be auto-refreshed. The login page has an invisible
reCAPTCHA; a headless login passes it in practice but could be scored low and
blocked, in which case the user must reconnect.

Playwright's sync API uses greenlets and cannot cross threads, so each login
runs its whole lifecycle on a dedicated thread.

The submit flow uses Enter (not a named button): Task 1 confirmed the sign-in /
login pages submit on Enter, and the password page's submit button is unlabeled.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from typing import Any, NoReturn

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_EMAIL_SELECTOR = "input[type=email], input[name=email]"
_PASSWORD_SELECTOR = "input[type=password]"  # noqa: S105 - a CSS selector, not a secret

# Extra wall-clock margin over ROUVY_LOGIN_TIMEOUT_MS for the thread join, so the
# join outlives Playwright's own internal timeout before we declare a hang.
_LOGIN_JOIN_BUFFER_SECONDS = 5.0


class RouvyAuthError(Exception):
    """Rouvy authentication failed (bad credentials, captcha, timeout, ...)."""


# Sent by sessions stored before Nov 2026 (a bare cookie list, no user agent):
# any ordinary Chrome; Cloudflare challenges httpx's default python-httpx
FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


def _load_session(session_json: str) -> tuple[list[dict[str, object]], str | None]:
    """(cookies, user agent) from a stored blob.

    Since Nov 2026 the blob is ``{"cookies": [...], "user_agent": "..."}``: the
    requests reuse the browser identity the login was issued to, which Rouvy's
    Cloudflare lets through. Older blobs are a bare cookie list (no agent).
    """
    try:
        data = json.loads(session_json)
    except json.JSONDecodeError, TypeError:
        return [], None
    if isinstance(data, dict):
        cookies, agent = data.get("cookies"), data.get("user_agent")
        return (
            [c for c in cookies if isinstance(c, dict)] if isinstance(cookies, list) else [],
            agent if isinstance(agent, str) and agent else None,
        )
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)], None
    return [], None


def _dump_session(cookies: list[dict[str, object]], user_agent: str | None) -> str:
    """The stored blob: the object form when there is an agent, else the old list."""
    if user_agent is None:
        return json.dumps(cookies)
    return json.dumps({"cookies": cookies, "user_agent": user_agent})


def cookies_to_jar(session_json: str) -> dict[str, str]:
    """Convert a stored cookie blob into an httpx-compatible name->value map."""
    cookies, _ = _load_session(session_json)
    return {str(c["name"]): str(c["value"]) for c in cookies if "name" in c and "value" in c}


def session_user_agent(session_json: str) -> str:
    """The browser identity to send with this session's requests."""
    _, user_agent = _load_session(session_json)
    return user_agent or FALLBACK_USER_AGENT


def merge_cookie_values(session_json: str, updates: Mapping[str, str]) -> str:
    """Return the stored cookie blob with rotated cookie values applied.

    Rouvy rotates ``rouvy_session`` (it wraps a 1h Firebase id token) via
    Set-Cookie on ordinary requests; persisting the rotation keeps the session
    alive without a full re-login. Existing entries keep their attributes,
    unknown cookies are appended, and the stored user agent is kept.
    """
    cookies, user_agent = _load_session(session_json)
    seen: set[str] = set()
    for c in cookies:
        name = c.get("name")
        if isinstance(name, str) and name in updates:
            c["value"] = updates[name]
            seen.add(name)
    for name, value in updates.items():
        if name not in seen:
            cookies.append({"name": name, "value": value, "domain": ".rouvy.com"})
    return _dump_session(cookies, user_agent)


def browser_user_agent(default: str) -> str:
    """The headless browser's own user agent with the "Headless" marker removed.

    Since Nov 2026 Rouvy's riders site (behind Cloudflare) answers a browser
    that calls itself "HeadlessChrome" with a block page right after the
    password step, so the login never reached /feed and timed out. Keeping the
    rest of the string keeps it consistent with the real browser and platform.
    """
    return default.replace("HeadlessChrome", "Chrome")


def login(email: str, password: str) -> str:
    """Headless Rouvy login. Returns the session blob (.rouvy.com cookies + user agent).

    Raises RouvyAuthError (with a user-friendly message) on any failure.
    """
    result: dict[str, Any] = {}

    def _run() -> None:
        try:
            result["cookies"] = _login_sync(email, password)
        except Exception as e:  # noqa: BLE001 - classified in _raise_typed_error
            result["error"] = e

    t = threading.Thread(target=_run, name="rouvy-login", daemon=True)
    t.start()
    t.join(timeout=Config.ROUVY_LOGIN_TIMEOUT_MS / 1000 + _LOGIN_JOIN_BUFFER_SECONDS)
    if t.is_alive():
        raise RouvyAuthError("Rouvy login timed out. Please try again.")
    if "error" in result:
        _raise_typed_error(result["error"])
    cookies: str = result["cookies"]
    return cookies


def _login_sync(email: str, password: str) -> str:
    """Blocking headless login; runs on the dedicated rouvy-login thread."""
    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415 - optional dependency
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional dependency

    timeout = Config.ROUVY_LOGIN_TIMEOUT_MS
    sign_in = f"{Config.ROUVY_ACCOUNT_URL}/sign-in?riders=true&redirectTo=%2Ffeed"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        probe = browser.new_page()
        user_agent = browser_user_agent(probe.evaluate("navigator.userAgent"))
        probe.close()
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()
        page.set_default_timeout(timeout)
        try:
            page.goto(sign_in)
            # Best-effort: decline non-essential cookies so the banner can't
            # overlay the form (privacy-preserving default).
            try:
                page.get_by_role("button", name="Use necessary cookies only").click(timeout=6000)
            except PlaywrightError:
                logger.debug("Rouvy cookie banner not present or already dismissed")
            # Email-first flow: fill email, Enter -> password page, fill, Enter.
            page.fill(_EMAIL_SELECTOR, email)
            page.press(_EMAIL_SELECTOR, "Enter")
            page.wait_for_selector(_PASSWORD_SELECTOR, timeout=20000)
            page.fill(_PASSWORD_SELECTOR, password)
            page.press(_PASSWORD_SELECTOR, "Enter")
            # Success = redirect into the riders portal feed.
            page.wait_for_url("**/feed", timeout=timeout)
            cookies = context.cookies()
        finally:
            context.close()
            browser.close()

    rouvy_cookies = [c for c in cookies if "rouvy.com" in c.get("domain", "")]
    if not rouvy_cookies:
        raise RouvyAuthError("Login did not produce a session. Please try again.")
    # The requests reuse this identity: Cloudflare challenges anything else
    return _dump_session([dict(c) for c in rouvy_cookies], user_agent)


def _raise_typed_error(e: Exception) -> NoReturn:
    """Classify a login exception into a user-friendly RouvyAuthError."""
    if isinstance(e, RouvyAuthError):
        raise e
    s = str(e).lower()
    if "email or password" in s or "wrong" in s or "invalid" in s or "credential" in s:
        raise RouvyAuthError("Rouvy email or password is wrong.") from e
    if "captcha" in s or "recaptcha" in s or "blocked" in s or "forbidden" in s:
        raise RouvyAuthError(
            "Rouvy blocked the automated login (captcha). Please reconnect in Settings."
        ) from e
    if "timeout" in s or "timed out" in s:
        raise RouvyAuthError("Rouvy login timed out. Please try again.") from e
    logger.error("Rouvy login failed", extra={"error": str(e)}, exc_info=e)
    raise RouvyAuthError(f"Rouvy login failed: {e}") from e
