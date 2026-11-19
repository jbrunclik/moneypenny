"""Page-level helpers for the browser's press, select and download actions.

They take a Playwright page and run on the worker thread (browser_worker.py
calls them); the live test drives them on a real headless Chromium page.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

# A Playwright key name, optionally with modifiers: "Enter", "ArrowDown",
# "Control+A", "Shift+Tab", "a". Nothing that could smuggle in other text.
KEY_PATTERN = re.compile(r"^(?:(?:Control|Shift|Alt|Meta)\+){0,3}[A-Za-z0-9]{1,12}$")


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
    return chosen


def download_file(page: Page, selector: str, max_bytes: int, timeout_ms: int) -> tuple[str, bytes]:
    """Click `selector`, wait for the download it starts; its file name and bytes."""
    with page.expect_download(timeout=timeout_ms) as info:
        page.click(selector, timeout=timeout_ms)
    download = info.value
    path = download.path()
    size = Path(path).stat().st_size
    if size > max_bytes:
        download.delete()
        raise DownloadTooLargeError(
            f"The file is {size} bytes, over the {max_bytes}-byte download limit."
        )
    data = Path(path).read_bytes()
    download.delete()
    return str(download.suggested_filename or "download"), data
