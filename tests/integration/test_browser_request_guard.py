"""Live test: the browser tool guards every request, not just the first URL.

The navigate action used to validate only the URL it was given, so a public
page could redirect, embed or fetch() into the production host's private
services and the page text went back to the model. A real Chromium proves
subresources and script requests are blocked, and that a redirect landing
(which routes never see) is caught before any content is returned.

`public.test` stands in for a public site: Chromium resolves it to a local
server, and check_host is patched to treat that name as public while the
real loopback address stays blocked.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from src.agent.tools import browser_worker
from src.agent.tools.browser import is_browser_available

pytestmark = pytest.mark.skipif(not is_browser_available(), reason="Chromium unavailable")


class _Server:
    def __init__(self) -> None:
        self.secret_hits: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.startswith("/secret"):
                    server.secret_hits.append(self.path)
                    self._send(200, "secret")
                elif self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{server.port}/secret-redirect")
                    self.end_headers()
                elif self.path == "/embeds":
                    self._send(
                        200,
                        f'<img src="http://127.0.0.1:{server.port}/secret-img">'
                        f"<script>fetch('http://127.0.0.1:{server.port}/secret-fetch')"
                        ".catch(() => {});"
                        f"new WebSocket('ws://127.0.0.1:{server.port}/secret-ws')</script>",
                    )
                else:
                    self._send(200, "<p>public</p>")

            def _send(self, status: int, body: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server() -> Iterator[_Server]:
    srv = _Server()
    yield srv
    srv.httpd.shutdown()


@pytest.fixture
def guarded_page(server: _Server, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    real_check = browser_worker.check_host
    monkeypatch.setattr(
        browser_worker,
        "check_host",
        lambda host, port=None: None if host == "public.test" else real_check(host, port),
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[f"--host-resolver-rules=MAP public.test 127.0.0.1:{server.port}"],
        )
        context = browser.new_context()
        browser_worker.install_request_guard(context)
        page = context.new_page()
        yield page
        browser.close()


def test_a_public_page_loads(guarded_page: Any) -> None:
    guarded_page.goto("http://public.test/")
    assert "public" in guarded_page.content()


def test_a_redirect_to_a_private_address_is_caught(guarded_page: Any) -> None:
    """Routes never see redirect hops: the GET goes out, but the landing is caught."""
    guarded_page.goto("http://public.test/redirect")
    assert browser_worker.blocked_frame_reason(guarded_page) is not None


def test_a_public_landing_is_not_flagged(guarded_page: Any) -> None:
    guarded_page.goto("http://public.test/")
    assert browser_worker.blocked_frame_reason(guarded_page) is None


def test_the_worker_refuses_a_private_landing() -> None:
    """The action fails and the page is cleared, so no content reaches the model."""
    from unittest.mock import MagicMock

    page = MagicMock()
    page.frames = [MagicMock(url="http://127.0.0.1:8000/admin")]
    worker = object.__new__(browser_worker.BrowserWorker)
    worker._sessions = {"c1": MagicMock(page=page)}

    with pytest.raises(PermissionError, match="blocked address"):
        worker._refuse_private_landing("c1")
    page.goto.assert_called_once_with("about:blank")


def test_subresources_fetch_and_websockets_to_a_private_address_are_blocked(
    guarded_page: Any, server: _Server
) -> None:
    guarded_page.goto("http://public.test/embeds")
    guarded_page.wait_for_load_state("networkidle")
    assert server.secret_hits == []


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("http://127.0.0.1/", True),
        ("http://localhost:8000/api", True),
        ("file:///etc/passwd", True),
        ("chrome://settings", True),
        ("data:text/html,hi", False),
        ("about:blank", False),
    ],
)
def test_block_reason(url: str, blocked: bool) -> None:
    assert (browser_worker.request_block_reason(url, {}) is not None) is blocked
