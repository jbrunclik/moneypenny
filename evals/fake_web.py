"""Canned web for eval cases: search results and pages from the case's YAML.

Nov 2026: the 14 live-web cases were 44% of a full run's spend and its
noisiest (ddgs throttles the laptop; results change daily). The fake
replaces the search and fetch SEAMS - not the tools - so research,
web_search, fetch_url and the freshness gate's prefetch still format,
wrap untrusted content and report errors exactly as in production.

Case shape (YAML):

    web:                      # absent: canned with no results (never live)
      results:                # returned for every search (first N per query)
        - {url: https://..., title: ..., snippet: ...}
      pages:                  # a fetch of one of these returns its text
        https://...: |
          ...realistic page text...

``web: live`` keeps the real (ddgs-only) path for that case.
"""

from __future__ import annotations

import contextlib
import html
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import httpx

LIVE = "live"


class FakeWeb:
    """Every search returns the canned results; a canned URL returns its page,
    any other URL the 404 a real fetch reports."""

    def __init__(self, spec: dict[str, Any] | None) -> None:
        spec = spec or {}
        self.results: list[dict[str, str]] = [
            {k: str(v) for k, v in r.items()} for r in spec.get("results") or []
        ]
        self.pages: dict[str, str] = {str(k): str(v) for k, v in (spec.get("pages") or {}).items()}
        self.queries: list[str] = []
        self.fetched: list[str] = []

    def search_web_detailed(self, query: str, num_results: int) -> tuple[list[dict[str, str]], str]:
        self.queries.append(query)
        return [dict(r) for r in self.results[:num_results]], "canned"

    def fetch_response(
        self, url: str, timeout: float | None = None
    ) -> tuple[httpx.Response | None, str | None, int | None]:
        """Same contract as src/agent/tools/web._fetch_response."""
        self.fetched.append(url)
        page = self.pages.get(url)
        if page is None:
            return None, f"HTTP 404 when fetching {url}", 404
        response = httpx.Response(
            200,
            text=_as_html(page),
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", url),
        )
        return response, None, None


def _as_html(text: str) -> str:
    """Plain page text as an HTML document, so the real extractor runs on it."""
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n\n") if p.strip())
    return f"<!doctype html><html><body><main>{paragraphs}</main></body></html>"


def _browser_unavailable() -> str:
    from src.agent.tools.errors import tool_error

    return tool_error("The browser is not available here.", retriable=False)


@contextlib.contextmanager
def canned_web(spec: dict[str, Any] | str | None) -> Iterator[FakeWeb | None]:
    """Install the canned web for a case (yields None for ``web: live``)."""
    if spec == LIVE:
        yield None
        return
    fake = FakeWeb(spec if isinstance(spec, dict) else None)
    with contextlib.ExitStack() as stack:
        for target in (
            "src.services.search_provider.search_web_detailed",
            "src.agent.tools.web.search_web_detailed",
        ):
            stack.enter_context(patch(target, fake.search_web_detailed))
        stack.enter_context(patch("src.agent.tools.web._fetch_response", fake.fetch_response))
        # A refused or PDF page must not fall back to the metered reader
        stack.enter_context(patch("src.agent.tools.web.extract_available", lambda: False))
        stack.enter_context(
            patch("src.agent.tools.browser._availability_error", _browser_unavailable)
        )
        yield fake
