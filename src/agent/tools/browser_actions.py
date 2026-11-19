"""Page-level helpers for the browser's press, select and download actions.

They take a Playwright page and run on the worker thread (browser_worker.py
calls them); the live test drives them on a real headless Chromium page.
"""

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import httpx

from src.agent.tools.url_safety import SSRFSafeTransport, validate_public_url
from src.utils.tls import shared_ssl_context

if TYPE_CHECKING:
    from playwright.sync_api import Cookie, Page

# A Playwright key name, optionally with modifiers: "Enter", "ArrowDown",
# "Control+A", "Shift+Tab", "a". Nothing that could smuggle in other text.
KEY_PATTERN = re.compile(r"^(?:(?:Control|Shift|Alt|Meta)\+){0,3}[A-Za-z0-9]{1,12}$")
_MAX_REDIRECTS = 5
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class DownloadTooLargeError(ValueError):
    """The downloaded file is over the size cap."""


def press_key(page: Page, key: str, selector: str | None) -> None:
    """Press `key` on the element `selector` (focused first), else on the page."""
    if selector:
        page.press(selector, key)
    else:
        page.keyboard.press(key)


def select_option(page: Page, selector: str, option: str) -> bool:
    """Choose `option` (an option's label, else its value) in a <select>.

    Returns only whether an option was chosen: the page's own option
    strings never go back to the model.
    """
    try:
        chosen = page.select_option(selector, label=option, timeout=2000)
    except Exception:  # noqa: BLE001 - no option with that label: try it as a value
        chosen = page.select_option(selector, value=option)
    return bool(chosen)


def _too_large(size: int, max_bytes: int) -> str:
    return f"The file is over the {max_bytes}-byte download limit ({size}+ bytes)."


def _jar(cookies: list[Cookie]) -> httpx.Cookies:
    """The page's cookies, each kept to its own domain and path (a redirect
    to another host must not carry them)."""
    jar = httpx.Cookies()
    for cookie in cookies:
        jar.set(
            cookie.get("name", ""),
            cookie.get("value", ""),
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return jar


def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise DownloadTooLargeError(_too_large(int(length), max_bytes))
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise DownloadTooLargeError(_too_large(len(body), max_bytes))
    return bytes(body)


def fetch_capped(url: str, cookies: list[Cookie], max_bytes: int, timeout_s: float) -> bytes:
    """GET `url` with the page's cookies: SSRF-checked on every redirect hop,
    the bytes that arrive counted against `max_bytes`, the whole fetch
    bounded by `timeout_s`."""
    with httpx.Client(
        timeout=timeout_s,
        follow_redirects=False,
        cookies=_jar(cookies),
        headers={"User-Agent": _USER_AGENT},
        transport=SSRFSafeTransport(verify=shared_ssl_context(), deadline_s=timeout_s),
    ) as client:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            if reason := validate_public_url(current):
                raise PermissionError(f"The download led to a blocked address. {reason}")
            with client.stream("GET", current) as response:
                if response.is_redirect and response.headers.get("location"):
                    current = urljoin(current, response.headers["location"])
                    continue
                response.raise_for_status()
                return _read_capped(response, max_bytes)
    raise ValueError(f"Too many redirects downloading {url}")


def download_file(page: Page, selector: str, max_bytes: int, timeout_ms: int) -> tuple[str, bytes]:
    """Click `selector`, catch the download it starts; its file name and bytes.

    Chromium's own copy is cancelled for an http(s) download and the file is
    fetched with fetch_capped instead: `download.path()` waits for the whole
    transfer with no timeout and no size limit, so a huge, endless or stalled
    file would fill the disk and hold the worker. A blob:/data: download is
    already in the page's memory and is checked once written.
    """
    with page.expect_download(timeout=timeout_ms) as info:
        page.click(selector, timeout=timeout_ms)
    download = info.value
    name = str(download.suggested_filename or "download")
    try:
        if download.url.startswith(("http://", "https://")):
            download.cancel()
            cookies = page.context.cookies(download.url)
            return name, fetch_capped(download.url, cookies, max_bytes, timeout_ms / 1000)
        path = Path(download.path())
        size = path.stat().st_size
        if size > max_bytes:
            raise DownloadTooLargeError(_too_large(size, max_bytes))
        return name, path.read_bytes()
    finally:
        with contextlib.suppress(Exception):  # a cancelled download has no file to delete
            download.delete()
