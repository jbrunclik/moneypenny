"""Short-lived httpx clients share one TLS context.

A client made per call loads its own copy of the CA bundle (~0.8 MB of native
memory); after a request the client sits in a reference cycle, so that memory
waited for a full garbage collection that busy workers almost never ran
(Oct 16 2026: a research burst raised a worker's floor by 30-90 MB).
"""

import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import httpx

from src.agent.tools import web
from src.config import Config
from src.services import search_adapters


@contextmanager
def _ca_bundle_loads() -> Iterator[list[None]]:
    """Count CA-bundle loads while every HTTP request is answered locally."""
    loads: list[None] = []
    real_load = ssl.SSLContext.load_verify_locations

    def counting_load(self: ssl.SSLContext, *args: object, **kwargs: object) -> None:
        loads.append(None)
        real_load(self, *args, **kwargs)  # type: ignore[arg-type]

    def answer(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}}, request=request)

    with (
        patch.object(ssl.SSLContext, "load_verify_locations", counting_load),
        patch.object(httpx.HTTPTransport, "handle_request", answer),
    ):
        yield loads


def test_page_fetches_load_the_ca_bundle_at_most_once() -> None:
    with (
        _ca_bundle_loads() as loads,
        patch.object(web, "validate_public_url", return_value=None),
        patch.object(web, "check_host", return_value=None),
    ):
        for _ in range(3):
            response, error = web._fetch_response("https://example.com/")
            assert error is None and response is not None
    assert len(loads) <= 1


def test_search_calls_load_the_ca_bundle_at_most_once() -> None:
    with _ca_bundle_loads() as loads, patch.object(Config, "BRAVE_SEARCH_API_KEY", "key"):
        for _ in range(3):
            search_adapters.search_brave("query", 3)
    assert len(loads) <= 1
