"""Search provider abstraction: Brave Search API with DDGS fallback.

DuckDuckGo (ddgs) is free but its relevance is noticeably weaker than paid
APIs - and the agent pays for weak results in extra tool rounds, each of
which re-bills the whole accumulated conversation. Setting
BRAVE_SEARCH_API_KEY switches all web searches (web_search tool, research
tool) to Brave; leaving it empty keeps the free DDGS behavior.

Contract: search_web() returns [{title, url, snippet}] or raises
SearchProviderError (retriable flag drives the agent's self-correction).
"""

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_TIMEOUT_SECONDS = 15


class SearchProviderError(Exception):
    """A search failure, with a retriable hint for agent self-correction."""

    def __init__(self, message: str, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


def active_provider() -> str:
    """Name of the provider that search_web() will use ("brave" | "ddgs")."""
    return "brave" if Config.BRAVE_SEARCH_API_KEY else "ddgs"


def search_web(query: str, num_results: int) -> list[dict[str, str]]:
    """Run one web search; returns [{title, url, snippet}].

    Raises SearchProviderError on failure (retriable=True for rate limits
    and timeouts).
    """
    if active_provider() == "brave":
        return _search_brave(query, num_results)
    return _search_ddgs(query, num_results)


def _search_brave(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.get(
            _BRAVE_ENDPOINT,
            params={"q": query, "count": num_results},
            headers={
                "X-Subscription-Token": Config.BRAVE_SEARCH_API_KEY,
                "Accept": "application/json",
            },
            timeout=_BRAVE_TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            raise SearchProviderError("Brave Search rate limited", retriable=True)
        response.raise_for_status()
        items = response.json().get("web", {}).get("results", [])
        return [
            {
                "title": item.get("title", "No title"),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            }
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Brave Search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Brave Search failed: {e}") from e


def _search_ddgs(query: str, num_results: int) -> list[dict[str, str]]:
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
