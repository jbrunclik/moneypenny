"""Live test: PAGE_STATE_JS summarizes a real page with selectors that work.

Runs the script in real headless Chromium (skips where Playwright/Chromium
is not installed). The unit tests mock the worker, so this is the only check
that the JavaScript itself is correct and that every selector it emits
resolves to exactly the element it describes.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from src.agent.tools.browser import is_browser_available
from src.agent.tools.browser_steps import PAGE_STATE_JS

pytestmark = pytest.mark.skipif(not is_browser_available(), reason="Chromium unavailable")

_HTML = """
<form>
  <input id="user" placeholder="Username">
  <input type="password" name="pw" value="hunter2">
  <input type="hidden" name="csrf" value="x">
  <select name="lang"><option>en</option></select>
  <button type="submit">Sign   in</button>
  <button aria-label="Close dialog">x</button>
</form>
<a href="/inbox">Inbox</a>
<a href="/hidden" style="display:none">Hidden link</a>
<div role="button">Accept cookies</div>
<fieldset>
  <input type="radio" name="color" value="red">
  <input type="radio" name="color" value="blue">
</fieldset>
<button>Learn more</button>
<button>Learn more</button>
<button>Learn more about pricing</button>
<nav><a href="/login">Login</a></nav>
<footer><a href="/login">Login</a></footer>
"""


@pytest.fixture(scope="module")
def page() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(_HTML)
        yield page
        browser.close()


def test_lists_visible_interactive_elements(page: Any) -> None:
    labels = {e["label"] for e in page.evaluate(PAGE_STATE_JS, 40)}

    assert {
        "Username",
        "pw",
        "lang",
        "Sign in",
        "Close dialog",
        "Inbox",
        "Accept cookies",
    } <= labels
    assert "Hidden link" not in labels
    assert "csrf" not in labels


def test_never_reads_input_values(page: Any) -> None:
    assert "hunter2" not in str(page.evaluate(PAGE_STATE_JS, 40))


def test_every_selector_resolves_to_one_element(page: Any) -> None:
    for element in page.evaluate(PAGE_STATE_JS, 40):
        assert page.locator(element["selector"]).count() == 1, element


def test_respects_the_element_cap(page: Any) -> None:
    assert len(page.evaluate(PAGE_STATE_JS, 3)) == 3


def test_duplicate_elements_get_distinct_selectors(page: Any) -> None:
    selectors = [e["selector"] for e in page.evaluate(PAGE_STATE_JS, 40)]
    assert len(selectors) == len(set(selectors))
    assert sum("Learn more" in s for s in selectors) == 3
