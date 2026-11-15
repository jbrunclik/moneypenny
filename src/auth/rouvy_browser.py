"""Replay a Rouvy request as a fetch() inside a headless Chromium page.

Since Nov 15 2026 Rouvy's Cloudflare challenges every direct (httpx, curl)
request to the riders `.data` endpoints, with or without a browser
User-Agent, and headless Chromium cannot solve that challenge to earn a
reusable clearance cookie. The same request made by fetch() from a page on
riders.rouvy.com passes: it carries the browser's own TLS fingerprint and
fetch headers, like the Rouvy web app's own calls. Making the request this
way keeps Rouvy usable for the user's own account (the user's call, Nov 15
2026). The reply is turned back into an httpx.Response, so the client's
parsing, token rotation and re-login logic stays the same.

Like the login (rouvy_auth), Playwright's sync API runs its whole lifecycle
on a dedicated thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import cast

import httpx

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# fetch() hands back the decoded body: keeping these made httpx inflate it
# again ("Error -3 while decompressing data", Nov 15 2026); Set-Cookie is
# rebuilt from the context
_DROPPED_HEADERS = frozenset(
    {"content-encoding", "content-length", "transfer-encoding", "set-cookie"}
)

# One Chromium per request: cap them like the browser tool's sessions. A
# worker frees its slot only once its browser closed, also after a timeout
_SLOTS = threading.BoundedSemaphore(Config.BROWSER_MAX_CONCURRENT_SESSIONS)

# Over the page timeout, so the join outlives Playwright's own timeout
_JOIN_BUFFER_SECONDS = 10.0

_FETCH_JS = """async ([url, spec]) => {
  let body;
  if (spec.body && spec.body.kind === 'form') {
    body = new URLSearchParams(spec.body.fields);
  } else if (spec.body && spec.body.kind === 'multipart') {
    body = new FormData();
    for (const [field, f] of Object.entries(spec.body.files)) {
      body.append(field, new Blob([f.content], {type: f.type}), f.filename);
    }
  }
  const r = await fetch(url, {
    method: spec.method, body, credentials: 'include', redirect: 'manual',
  });
  return {
    status: r.type === 'opaqueredirect' ? 0 : r.status,
    headers: Object.fromEntries(r.headers.entries()),
    body: await r.text(),
  };
}"""


# (status, headers, body, the context's rouvy.com cookies afterwards)
_Reply = tuple[int, dict[str, str], str, dict[str, str]]
# httpx-style upload: field -> (filename, content, content type)
_Files = Mapping[str, tuple[str, str, str]]


class RouvyBrowserError(Exception):
    """The in-browser request could not run (launch failure, timeout)."""


def fetch_spec(method: str, kwargs: Mapping[str, object]) -> dict[str, object]:
    """What the page's fetch() sends, from the httpx-style request kwargs."""
    body: dict[str, object] | None = None
    files, data = kwargs.get("files"), kwargs.get("data")
    if files:
        body = {
            "kind": "multipart",
            "files": {
                field: {"filename": name, "content": content, "type": ctype}
                for field, (name, content, ctype) in cast("_Files", files).items()
            },
        }
    elif data:
        body = {"kind": "form", "fields": dict(cast("Mapping[str, str]", data))}
    return {"method": method, "body": body}


def to_response(
    method: str,
    url: str,
    status: int,
    headers: Mapping[str, str],
    body: str,
    sent: Mapping[str, str],
    after: Mapping[str, str],
) -> httpx.Response:
    """The page's reply as an httpx.Response.

    fetch() never exposes Set-Cookie, so cookies the browser set or rotated
    (read off its context afterwards) come back as Set-Cookie headers. A
    redirect fetch() would not follow (status 0) reads as a 302.
    """
    pairs = [(k, v) for k, v in headers.items() if k.lower() not in _DROPPED_HEADERS]
    for name, value in after.items():
        if value and sent.get(name) != value:
            pairs.append(("set-cookie", f"{name}={value}; Domain=.rouvy.com; Path=/"))
    return httpx.Response(
        status or 302,
        headers=pairs,
        content=body.encode(),
        request=httpx.Request(method, url),
    )


def fetch(
    method: str, url: str, kwargs: Mapping[str, object], jar: Mapping[str, str], user_agent: str
) -> httpx.Response:
    """Make the request from a riders.rouvy.com page with the session's cookies."""
    replies: list[_Reply] = []
    errors: list[Exception] = []
    started = time.monotonic()

    def _run() -> None:
        try:
            replies.append(_fetch_sync(url, fetch_spec(method, kwargs), jar, user_agent))
        except Exception as e:  # noqa: BLE001 - re-raised on the caller's thread
            errors.append(e)
        finally:
            _SLOTS.release()

    if not _SLOTS.acquire(timeout=Config.ROUVY_HTTP_TIMEOUT_SECONDS):
        raise RouvyBrowserError("Too many Rouvy browser requests at once")

    t = threading.Thread(target=_run, name="rouvy-fetch", daemon=True)
    t.start()
    t.join(timeout=Config.ROUVY_HTTP_TIMEOUT_SECONDS + _JOIN_BUFFER_SECONDS)
    if t.is_alive():
        raise RouvyBrowserError("Rouvy browser request timed out")
    if errors:
        raise RouvyBrowserError(str(errors[0])) from errors[0]
    status, headers, body, after = replies[0]
    logger.info(
        "Rouvy request via browser",
        extra={
            "method": method,
            "status": status,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return to_response(method, url, status, headers, body, jar, after)


def _fetch_sync(
    url: str, spec: dict[str, object], jar: Mapping[str, str], user_agent: str
) -> _Reply:
    """Blocking browser request; runs on the dedicated rouvy-fetch thread."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional dependency

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        try:
            context = browser.new_context(user_agent=user_agent)
            context.add_cookies(
                [
                    {"name": n, "value": v, "domain": ".rouvy.com", "path": "/"}
                    for n, v in jar.items()
                ]
            )
            page = context.new_page()
            page.set_default_timeout(Config.ROUVY_HTTP_TIMEOUT_SECONDS * 1000)
            # Any riders page Cloudflare serves: fetch() needs that origin
            page.goto(f"{Config.ROUVY_RIDERS_URL}/robots.txt")
            reply = page.evaluate(_FETCH_JS, [url, spec])
            after = {c["name"]: c["value"] for c in context.cookies() if "rouvy.com" in c["domain"]}
        finally:
            browser.close()
    return int(reply["status"]), dict(reply["headers"]), str(reply["body"]), after
