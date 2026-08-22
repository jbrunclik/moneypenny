"""Quota-aware search provider router.

Providers are tried in priority order — Brave, Tavily, Exa, then DuckDuckGo
(ddgs) as the unmetered terminal fallback. A provider is skipped when its
API key is empty or its monthly quota (Config.SEARCH_QUOTA_*) is used up,
and a failing provider falls through to the next one, so a mid-month quota
exhaustion degrades gracefully instead of breaking web search.

Usage counters are persisted in kv_store (SQLite) under a system sentinel
user, one key per provider+month ("brave:2026-08"), incremented atomically
so gunicorn workers can't lose updates. Metered calls are billed on success
only — provider dashboards stay authoritative.

Contract: search_web() returns [{title, url, snippet}] or raises
SearchProviderError (retriable flag drives the agent's self-correction).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_EXA_ENDPOINT = "https://api.exa.ai/search"
_HTTP_TIMEOUT_SECONDS = 15

# Usage counters are global app state, not per-user data - stored under a
# sentinel user id in the per-user kv_store table
_SYSTEM_USER_ID = "__system__"
USAGE_NAMESPACE = "search-usage"


class SearchProviderError(Exception):
    """A search failure, with a retriable hint for agent self-correction."""

    def __init__(self, message: str, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


# ============ Usage accounting ============


def usage_key(provider: str) -> str:
    """kv_store key for a provider's current-month usage counter."""
    return f"{provider}:{datetime.now().strftime('%Y-%m')}"


def get_monthly_usage(provider: str) -> int:
    """Searches billed to a provider this month (0 when never used)."""
    value = db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, usage_key(provider))
    return int(value) if value else 0


def _record_use(provider: str) -> None:
    used = db.kv_increment(_SYSTEM_USER_ID, USAGE_NAMESPACE, usage_key(provider))
    logger.debug("Search billed", extra={"provider": provider, "monthly_usage": used})


# ============ Router ============


@dataclass(frozen=True)
class _Provider:
    name: str
    api_key: Callable[[], str]
    monthly_quota: Callable[[], int | None]  # None = unmetered
    search: Callable[[str, int], list[dict[str, str]]]


def _provider_available(provider: _Provider) -> bool:
    if provider.monthly_quota() is None:
        return True  # ddgs: always available, needs no key
    if not provider.api_key():
        return False
    quota = provider.monthly_quota()
    return quota is None or get_monthly_usage(provider.name) < quota


def active_provider() -> str:
    """Name of the provider that search_web() will try first."""
    for provider in _PROVIDERS:
        if _provider_available(provider):
            return provider.name
    return "ddgs"


def search_web(query: str, num_results: int) -> list[dict[str, str]]:
    """Run one web search; returns [{title, url, snippet}].

    Routing: first configured provider with quota remaining; a provider
    error falls through to the next. Zero results for a query containing
    quote operators triggers ONE retry with the operators stripped on the
    same provider: models write Google-style exact-match queries that
    return nothing, then burn whole LLM rounds rephrasing.

    Raises SearchProviderError when every available provider failed.
    """
    last_error: SearchProviderError | None = None

    for provider in _PROVIDERS:
        if not _provider_available(provider):
            continue
        try:
            results = _search_with_quote_retry(provider, query, num_results)
        except SearchProviderError as error:
            logger.warning(
                "Search provider failed, trying next",
                extra={"provider": provider.name, "error": str(error)},
            )
            last_error = error
            continue
        return results

    raise last_error or SearchProviderError("No search provider available", retriable=True)


def _search_with_quote_retry(
    provider: _Provider, query: str, num_results: int
) -> list[dict[str, str]]:
    results = _billed_search(provider, query, num_results)
    if not results and '"' in query:
        unquoted = query.replace('"', " ").strip()
        logger.info("Zero results for quoted query, retrying unquoted", extra={"query": query})
        results = _billed_search(provider, unquoted, num_results)
    return results


def _billed_search(provider: _Provider, query: str, num_results: int) -> list[dict[str, str]]:
    results = provider.search(query, num_results)
    if provider.monthly_quota() is not None:
        _record_use(provider.name)
    return results


# ============ Provider adapters ============


def _search_brave(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.get(
            _BRAVE_ENDPOINT,
            params={"q": query, "count": num_results},
            headers={
                "X-Subscription-Token": Config.BRAVE_SEARCH_API_KEY,
                "Accept": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
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


def _search_tavily(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            _TAVILY_ENDPOINT,
            json={"query": query, "max_results": num_results},
            headers={
                "Authorization": f"Bearer {Config.TAVILY_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code in (429, 432):  # 432 = Tavily plan limit
            raise SearchProviderError("Tavily rate/plan limited", retriable=True)
        response.raise_for_status()
        items = response.json().get("results", [])
        return [
            {
                "title": item.get("title", "No title"),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Tavily search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Tavily search failed: {e}") from e


def _search_exa(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.post(
            _EXA_ENDPOINT,
            json={
                "query": query,
                "numResults": num_results,
                # Short text excerpts double as snippets
                "contents": {"text": {"maxCharacters": 500}},
            },
            headers={
                "x-api-key": Config.EXA_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code in (402, 429):  # 402 = out of credits
            raise SearchProviderError("Exa credits exhausted or rate limited", retriable=True)
        response.raise_for_status()
        items = response.json().get("results", [])
        return [
            {
                "title": item.get("title") or "No title",
                "url": item.get("url", ""),
                "snippet": item.get("text", ""),
            }
            for item in items[:num_results]
        ]
    except httpx.TimeoutException as e:
        raise SearchProviderError("Exa search timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Exa search failed: {e}") from e


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


# Priority order: quality-per-free-search first, unmetered fallback last.
# The search callables resolve the module-level functions at CALL time
# (late binding) so tests can patch _search_* like any module attribute.
_PROVIDERS: tuple[_Provider, ...] = (
    _Provider(
        "brave",
        lambda: Config.BRAVE_SEARCH_API_KEY,
        lambda: Config.SEARCH_QUOTA_BRAVE_MONTHLY,
        lambda q, n: _search_brave(q, n),
    ),
    _Provider(
        "tavily",
        lambda: Config.TAVILY_API_KEY,
        lambda: Config.SEARCH_QUOTA_TAVILY_MONTHLY,
        lambda q, n: _search_tavily(q, n),
    ),
    _Provider(
        "exa",
        lambda: Config.EXA_API_KEY,
        lambda: Config.SEARCH_QUOTA_EXA_MONTHLY,
        lambda q, n: _search_exa(q, n),
    ),
    _Provider("ddgs", lambda: "", lambda: None, lambda q, n: _search_ddgs(q, n)),
)
