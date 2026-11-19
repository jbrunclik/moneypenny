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
import re
import unicodedata
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

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
        self.pages: dict[str, str] = {
            _normalized(str(k)): str(v) for k, v in (spec.get("pages") or {}).items()
        }
        self.queries: list[str] = []
        self.fetched: list[str] = []

    def search_web_detailed(self, query: str, num_results: int) -> tuple[list[dict[str, str]], str]:
        """The canned results, best matches for this query first (stable: ties
        keep the canned order) - real search answers each query with its own
        pages, which a question about several places depends on."""
        self.queries.append(query)
        words = _words(query)
        ranked = sorted(
            self.results,
            key=lambda r: (
                -len(words & _words(f"{r.get('title')} {r.get('snippet')} {r.get('url')}"))
            ),
        )
        return [dict(r) for r in ranked[:num_results]], "canned"

    def fetch_response(
        self, url: str, timeout: float | None = None
    ) -> tuple[httpx.Response | None, str | None, int | None]:
        """Same contract as src/agent/tools/web._fetch_response."""
        self.fetched.append(url)
        page = self.pages.get(_normalized(url))
        if page is None:
            return None, f"HTTP 404 when fetching {url}", 404
        response = httpx.Response(
            200,
            text=_as_html(page),
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", url),
        )
        return response, None, None

    def summary(self) -> dict[str, Any]:
        """What the turn did on the canned web - to tell a failure caused by
        missing pages from a model failure."""
        return {
            "searches": len(self.queries),
            "fetched": list(self.fetched),
            "missing": [u for u in self.fetched if _normalized(u) not in self.pages],
        }


def _words(text: str) -> set[str]:
    """Rough word stems without accents, so Czech inflection still matches
    ("Brno" / "v Brně", "Plzeň" / "v Plzni"): the last two letters dropped,
    at least three kept."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return {w[: max(3, len(w) - 2)] for w in re.split(r"[^a-z0-9]+", plain) if len(w) >= 3}


def _normalized(url: str) -> str:
    """A URL as a model may write it: http or https, any host case, a
    fragment or a trailing slash all reach the same canned page."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, parts.query, ""))


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
