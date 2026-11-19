"""Live test: press, select and download on a real headless Chromium page.

Skips where Playwright/Chromium is not installed, like the page-state test.
"""

import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.tools.browser import is_browser_available
from src.agent.tools.browser_actions import (
    DownloadTooLargeError,
    download_file,
    fetch_capped,
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
    """Only whether it matched comes back - never the page's own option strings."""
    assert select_option(page, "#size", "Large") is True
    assert page.eval_on_selector("#size", "el => el.value") == "l"
    assert select_option(page, "#size", "s") is True
    assert page.eval_on_selector("#size", "el => el.value") == "s"


def test_download_returns_the_file(page: Any) -> None:
    name, data = download_file(page, "#csv", max_bytes=1000, timeout_ms=10000)
    assert name == "kids.csv"
    assert data == b"name,age\nana,9"


def test_download_over_the_cap_is_refused(page: Any) -> None:
    with pytest.raises(DownloadTooLargeError):
        download_file(page, "#csv", max_bytes=5, timeout_ms=10000)


def _serve(handler: type, page: Any) -> Iterator[str]:
    import threading
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # The test server is on localhost, which the SSRF check refuses
        with (
            patch("src.agent.tools.browser_actions.validate_public_url", return_value=None),
            patch("src.agent.tools.url_safety.check_host", return_value=None),
        ):
            yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


def _download_link(page: Any, base: str, path: str = "/f") -> None:
    page.set_content(f'<a id="get" href="{base}{path}">Get</a>')


def test_an_http_download_is_fetched_and_named(page: Any) -> None:
    class Small(_Handler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="route.gpx"')
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"<gpx>")

    for base in _serve(Small, page):
        _download_link(page, base)
        assert download_file(page, "#get", max_bytes=1000, timeout_ms=10000) == (
            "route.gpx",
            b"<gpx>",
        )


def test_an_announced_size_over_the_cap_is_refused_before_the_body(page: Any) -> None:
    class Announced(_Handler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="big.bin"')
            self.send_header("Content-Length", str(50_000_000))
            self.end_headers()
            self.wfile.write(b"x" * 1024)
            self.wfile.flush()
            time.sleep(20)  # the stall under test: the body never completes in time

    for base in _serve(Announced, page):
        _download_link(page, base)
        started = time.monotonic()
        with pytest.raises(DownloadTooLargeError):
            download_file(page, "#get", max_bytes=1000, timeout_ms=10000)
        assert time.monotonic() - started < 10


def test_a_stream_without_a_length_is_cut_at_the_cap(page: Any) -> None:
    """No Content-Length (chunked, endless): the bytes that arrive are counted."""

    class Endless(_Handler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="log.txt"')
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for _ in range(100_000):
                    self.wfile.write(b"400\r\n" + b"y" * 1024 + b"\r\n")
            except BrokenPipeError, ConnectionResetError:
                pass

    for base in _serve(Endless, page):
        _download_link(page, base)
        started = time.monotonic()
        with pytest.raises(DownloadTooLargeError):
            download_file(page, "#get", max_bytes=10_000, timeout_ms=10000)
        assert time.monotonic() - started < 10


def test_a_redirect_to_a_blocked_address_is_refused(page: Any) -> None:
    """Every redirect hop of the fetch is re-validated, like fetch_url's."""

    class Redirect(_Handler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest")
            self.end_headers()

    for base in _serve(Redirect, page):
        with (
            patch(
                "src.agent.tools.browser_actions.validate_public_url",
                side_effect=lambda url: "blocked" if "169.254" in url else None,
            ),
            pytest.raises(PermissionError),
        ):
            fetch_capped(f"{base}/r", [], max_bytes=1000, timeout_s=10)
