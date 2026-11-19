"""Live test: press, select and download on a real headless Chromium page.

Skips where Playwright/Chromium is not installed, like the page-state test.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from src.agent.tools.browser import is_browser_available
from src.agent.tools.browser_actions import (
    DownloadTooLargeError,
    download_file,
    press_key,
    select_option,
)

pytestmark = pytest.mark.skipif(not is_browser_available(), reason="Chromium unavailable")

_HTML = """
<form onsubmit="document.title = 'sent:' + this.q.value; return false;">
  <input name="q">
</form>
<select id="size"><option value="s">Small</option><option value="l">Large</option></select>
<a id="csv" href="data:text/csv,name%2Cage%0Aana%2C9" download="kids.csv">Export</a>
"""


@pytest.fixture
def page() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_content(_HTML)
        yield page
        browser.close()


def test_enter_submits_the_focused_form(page: Any) -> None:
    page.fill("input[name=q]", "bike")
    press_key(page, "Enter", "input[name=q]")
    assert page.title() == "sent:bike"


def test_select_by_label_or_value(page: Any) -> None:
    assert select_option(page, "#size", "Large") == ["l"]
    assert page.eval_on_selector("#size", "el => el.value") == "l"
    assert select_option(page, "#size", "s") == ["s"]


def test_download_returns_the_file(page: Any) -> None:
    name, data = download_file(page, "#csv", max_bytes=1000, timeout_ms=10000)
    assert name == "kids.csv"
    assert data == b"name,age\nana,9"


def test_download_over_the_cap_is_refused(page: Any) -> None:
    with pytest.raises(DownloadTooLargeError):
        download_file(page, "#csv", max_bytes=5, timeout_ms=10000)
