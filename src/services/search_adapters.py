"""Web search provider adapters: each provider's API mapped to the router's
contract (src/services/search_provider.py) - [{title, url, snippet,
published?}], or SearchProviderError, whose `exhausted` flag marks a plan
out of credits.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from src.config import Config
from src.utils.tls import shared_ssl_context

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_EXA_ENDPOINT = "https://api.exa.ai/search"
_LINKUP_ENDPOINT = "https://api.linkup.so/v1/search"
_HTTP_TIMEOUT_SECONDS = 15


class SearchProviderError(Exception):
    """A search failure, with a retriable hint for agent self-correction.

    `exhausted` marks a TERMINAL failure - the provider is out of credits for
    the billing period, not merely busy. Credits do not come back mid-period,
    so an exhausted provider is benched at once and never probed again until
    the period rolls over. Conflating the two cost us 19 days of daily probes
    against a Tavily that had been dry since Sep 5 2026, each one charging a
    real user's search a failed round-trip before falling through.
    """

    def __init__(self, message: str, retriable: bool = True, exhausted: bool = False) -> None:
        super().__init__(message)
        self.retriable = retriable
        self.exhausted = exhausted


def _decoded_json(response: httpx.Response, provider: str) -> dict[str, Any]:
    """Decode a provider response body, or raise SearchProviderError.

    A malformed body (an upstream proxy's HTML error page served with a 200,
    say) raises ValueError from .json(), which is not an httpx.HTTPError and
    would otherwise escape the adapter uncaught instead of falling through
    to the next provider.
    """
    try:
        decoded: dict[str, Any] = response.json()
    except ValueError as e:
        raise SearchProviderError(f"{provider} returned an undecodable body", retriable=True) from e
    return decoded


def search_brave(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.get(
            _BRAVE_ENDPOINT,
            params={"q": query, "count": num_results},
            headers={
                "X-Subscription-Token": Config.BRAVE_SEARCH_API_KEY,
                "Accept": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
            verify=shared_ssl_context(),
        )
        if response.status_code == 402:
            raise SearchProviderError(
                "Brave Search usage limit exceeded for the period",
                retriable=True,
                exhausted=True,
            )
        if response.status_code == 429:
            raise SearchProviderError("Brave Search rate limited", retriable=True)
        response.raise_for_status()
        items = _decoded_json(response, "Brave Search").get("web", {}).get("results", [])
        return [
            _dated(
                {
                    "title": item.get("title", "No title"),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                },
                item.get("page_age"),
            )
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Brave Search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Brave Search failed: {e}") from e


def normalize_published(value: Any) -> str | None:
    """A provider's publish date as YYYY-MM-DD (ISO 8601 or RFC 2822), else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except TypeError, ValueError, IndexError:
        return None


def _dated(result: dict[str, str], published: Any) -> dict[str, str]:
    """The result plus its publish date, when the provider gave a usable one."""
    day = normalize_published(published)
    return {**result, "published": day} if day else result


def search_tavily(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            _TAVILY_ENDPOINT,
            json={"query": query, "max_results": num_results},
            headers={
                "Authorization": f"Bearer {Config.TAVILY_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
            verify=shared_ssl_context(),
        )
        if response.status_code == 432:  # Tavily's plan-limit code
            raise SearchProviderError(
                "Tavily plan usage limit exceeded for the period",
                retriable=True,
                exhausted=True,
            )
        if response.status_code == 429:
            raise SearchProviderError("Tavily rate limited", retriable=True)
        response.raise_for_status()
        items = _decoded_json(response, "Tavily").get("results", [])
        return [
            _dated(
                {
                    "title": item.get("title", "No title"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                },
                item.get("published_date"),
            )
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Tavily search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Tavily search failed: {e}") from e


def search_exa(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            _EXA_ENDPOINT,
            json={
                "query": query,
                "type": Config.EXA_SEARCH_TYPE,
                "numResults": num_results,
                # Short text excerpts double as snippets
                "contents": {"text": {"maxCharacters": 500}},
            },
            headers={
                "x-api-key": Config.EXA_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
            verify=shared_ssl_context(),
        )
        if response.status_code == 402:
            raise SearchProviderError(
                "Exa credits exhausted for the period", retriable=True, exhausted=True
            )
        if response.status_code == 429:
            raise SearchProviderError("Exa rate limited", retriable=True)
        response.raise_for_status()
        items = _decoded_json(response, "Exa").get("results", [])
        return [
            _dated(
                {
                    "title": item.get("title") or "No title",
                    "url": item.get("url", ""),
                    "snippet": item.get("text", ""),
                },
                item.get("publishedDate"),
            )
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Exa search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Exa search failed: {e}") from e


def search_linkup(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            _LINKUP_ENDPOINT,
            json={
                "q": query,
                "depth": Config.LINKUP_SEARCH_DEPTH,
                "outputType": "searchResults",
                "maxResults": num_results,
            },
            headers={
                "Authorization": f"Bearer {Config.LINKUP_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
            verify=shared_ssl_context(),
        )
        # Linkup returns 429 for rate limiting AND for exhausted credits with
        # nothing in the response distinguishing them, so this one genuinely
        # cannot be classified: it stays transient and the consecutive-failure
        # threshold is what benches a spent plan. Revisit if Linkup ever splits
        # the codes (the other three providers all do).
        if response.status_code == 429:
            raise SearchProviderError("Linkup rate limited or out of credits", retriable=True)
        response.raise_for_status()
        items = _decoded_json(response, "Linkup").get("results", [])
        return [
            {
                "title": item.get("name") or "No title",
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Linkup search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Linkup search failed: {e}") from e


def search_ddgs(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        return [
            {
                "title": r.get("title", "No title"),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]
    except RatelimitException as e:
        raise SearchProviderError(
            "Search rate limited. Please try again later.", retriable=True
        ) from e
    except TimeoutException as e:
        raise SearchProviderError("Search timed out. Please try again.", retriable=True) from e
    except DDGSException as e:
        raise SearchProviderError(str(e)) from e
