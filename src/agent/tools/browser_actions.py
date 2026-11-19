"""Page-level helpers for the browser's press, select and download actions.

They take a Playwright page and run on the worker thread (browser_worker.py
calls them); the live test drives them on a real headless Chromium page.
"""

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Response

# A Playwright key name, optionally with modifiers: "Enter", "ArrowDown",
# "Control+A", "Shift+Tab", "a". Nothing that could smuggle in other text.
KEY_PATTERN = re.compile(r"^(?:(?:Control|Shift|Alt|Meta)\+){0,3}[A-Za-z0-9]{1,12}$")


SELECTED_VALUE_MAX_CHARS = 80


class DownloadTooLargeError(ValueError):
    """The downloaded file is over the size cap."""


def press_key(page: Page, key: str, selector: str | None) -> None:
    """Press `key` on the element `selector` (focused first), else on the page."""
    if selector:
        page.press(selector, key)
    else:
        page.keyboard.press(key)


def select_option(page: Page, selector: str, option: str) -> list[str]:
    """Choose `option` (an option's label, else its value) in a <select>; the values chosen."""
    try:
        chosen: list[str] = page.select_option(selector, label=option, timeout=2000)
    except Exception:  # noqa: BLE001 - no option with that label: try it as a value
        chosen = page.select_option(selector, value=option)
    # Option values come from the page: short, like the element labels
    return [value[:SELECTED_VALUE_MAX_CHARS] for value in chosen[:10]]


def download_file(page: Page, selector: str, max_bytes: int, timeout_ms: int) -> tuple[str, bytes]:
    """Click `selector`, wait for the download it starts; its file name and bytes.

    A response announcing more than `max_bytes` (Content-Length) is refused
    before its body arrives: `download.path()` waits for the whole transfer
    with no timeout, so a huge or stalled file would fill the disk and hold
    the worker. A file without a Content-Length is checked once it is done.
    The temp file is always deleted.
    """
    announced: dict[str, int] = {}

    def remember_length(response: Response) -> None:
        length = response.headers.get("content-length", "")
        if length.isdigit():
            announced[response.url] = int(length)

    page.on("response", remember_length)
    try:
        with page.expect_download(timeout=timeout_ms) as info:
            page.click(selector, timeout=timeout_ms)
    finally:
        page.remove_listener("response", remember_length)
    download = info.value
    try:
        if announced.get(download.url, 0) > max_bytes:
            download.cancel()
            raise DownloadTooLargeError(_too_large(announced[download.url], max_bytes))
        path = download.path()
        size = Path(path).stat().st_size
        if size > max_bytes:
            raise DownloadTooLargeError(_too_large(size, max_bytes))
        data = Path(path).read_bytes()
    finally:
        with contextlib.suppress(Exception):  # a cancelled download has no file to delete
            download.delete()
    return str(download.suggested_filename or "download"), data


def _too_large(size: int, max_bytes: int) -> str:
    return f"The file is {size} bytes, over the {max_bytes}-byte download limit."
