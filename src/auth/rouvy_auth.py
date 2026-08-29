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


def cookies_to_jar(session_json: str) -> dict[str, str]:
    """Convert a stored cookie blob into an httpx-compatible name->value map."""
    try:
        cookies = json.loads(session_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(cookies, list):
        return {}
    return {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}


def login(email: str, password: str) -> str:
    """Headless Rouvy login. Returns a JSON string of .rouvy.com cookies.

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
    from playwright.sync_api import sync_playwright

    timeout = Config.ROUVY_LOGIN_TIMEOUT_MS
    sign_in = f"{Config.ROUVY_ACCOUNT_URL}/sign-in?riders=true&redirectTo=%2Ffeed"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout)
        try:
            page.goto(sign_in)
            # Best-effort: decline non-essential cookies so the banner can't
            # overlay the form (privacy-preserving default).
            try:
                page.get_by_role("button", name="Use necessary cookies only").click(timeout=6000)
            except Exception:
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
    return json.dumps(rouvy_cookies)


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
    logger.error("Rouvy login failed", extra={"error": str(e)}, exc_info=True)
    raise RouvyAuthError(f"Rouvy login failed: {e}") from e
