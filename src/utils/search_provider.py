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

import json
import time
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

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


def period_start(anchor_day: int, today: date) -> str:
    """Start of the billing period containing `today`, as a usage-key suffix.

    Quotas reset on the provider's billing day (typically the signup
    anniversary), not on calendar-month boundaries. Anchor day 1 keeps the
    plain YYYY-MM form (calendar month); other anchors produce the period's
    start date, clamped to the month length (anchor 31 in February -> 28th).
    """
    if anchor_day <= 1:
        return today.strftime("%Y-%m")
    year, month = today.year, today.month
    if today.day < anchor_day:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    day = min(anchor_day, monthrange(year, month)[1])
    return f"{year:04d}-{month:02d}-{day:02d}"


def _billing_anchor(provider: str) -> int:
    return {
        "brave": Config.SEARCH_BILLING_DAY_BRAVE,
        "tavily": Config.SEARCH_BILLING_DAY_TAVILY,
        "exa": Config.SEARCH_BILLING_DAY_EXA,
    }.get(provider, 1)


def usage_key(provider: str) -> str:
    """kv_store key for a provider's current billing-period usage counter."""
    return f"{provider}:{period_start(_billing_anchor(provider), date.today())}"


def get_monthly_usage(provider: str) -> int:
    """Searches billed to a provider this billing period (0 when never used)."""
    value = db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, usage_key(provider))
    return int(value) if value else 0


def _record_use(provider: str) -> None:
    used = db.kv_increment(_SYSTEM_USER_ID, USAGE_NAMESPACE, usage_key(provider))
    logger.debug("Search billed", extra={"provider": provider, "monthly_usage": used})


# ============ Circuit breaker ============
#
# Usage counters bill on success only, so they undercount a provider's real
# spend (Brave counts requests we timed out on or got errors from; we don't).
# That drift lets the router keep sending to a provider that's actually out of
# credits. The breaker trips on consecutive failures instead of relying on the
# counter, and is period-scoped so it clears automatically when credits reset.


def breaker_key(provider: str) -> str:
    """kv_store key for a provider's breaker state this billing period.

    Shares the usage counter's period suffix, so a trip clears exactly when
    the provider's quota resets.
    """
    return f"breaker:{provider}:{period_start(_billing_anchor(provider), date.today())}"


def _now() -> float:
    """Epoch seconds - a seam so tests can control the breaker clock without
    patching the global time.time (which also drives date.today())."""
    return time.time()


def _breaker_state(provider: str) -> tuple[int, float]:
    """(consecutive failures, epoch of the last failure); (0, 0.0) when clear."""
    raw = db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider))
    if not raw:
        return 0, 0.0
    try:
        data = json.loads(raw)
        return int(data.get("fails", 0)), float(data.get("last", 0.0))
    except (ValueError, TypeError):
        return 0, 0.0


def _breaker_tripped(provider: str) -> bool:
    """Whether the provider should be skipped right now.

    Tripped once failures reach the threshold, EXCEPT for a single half-open
    probe allowed once the probe interval has elapsed since the last failure -
    so a transient (non-exhaustion) outage recovers within a day instead of
    staying down until the billing period rolls over.
    """
    fails, last = _breaker_state(provider)
    if fails < Config.SEARCH_BREAKER_THRESHOLD:
        return False
    return _now() - last < Config.SEARCH_BREAKER_PROBE_SECONDS


def _record_breaker_failure(provider: str) -> None:
    fails, _ = _breaker_state(provider)
    payload = json.dumps({"fails": fails + 1, "last": _now()})
    db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider), payload)
    logger.debug(
        "Search breaker failure recorded", extra={"provider": provider, "fails": fails + 1}
    )


def _reset_breaker(provider: str) -> None:
    """Clear the breaker after a success (no-op when already clear)."""
    fails, _ = _breaker_state(provider)
    if fails:
        db.kv_delete(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider))
        logger.info("Search breaker reset after success", extra={"provider": provider})


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
    if _breaker_tripped(provider.name):
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
        metered = provider.monthly_quota() is not None
        try:
            results = _search_with_quote_retry(provider, query, num_results)
        except SearchProviderError as error:
            logger.warning(
                "Search provider failed, trying next",
                extra={"provider": provider.name, "error": str(error)},
            )
            # Breaker only guards metered providers; ddgs is the terminal
            # fallback with nowhere to fail over to.
            if metered:
                _record_breaker_failure(provider.name)
            last_error = error
            continue
        if metered:
            _reset_breaker(provider.name)
        _notify_if_degraded(provider.name)
        return results

    raise last_error or SearchProviderError("No search provider available", retriable=True)


def _notify_if_degraded(served_by: str) -> None:
    """Alert the operator (once per day) when ddgs serves despite paid
    providers being configured - otherwise quality degrades silently when
    quotas run out mid-period. Never breaks the search that triggered it."""
    if served_by != "ddgs":
        return
    try:
        metered = [p for p in _PROVIDERS if p.monthly_quota() is not None and p.api_key()]
        if not metered:
            return  # dev setup without keys - ddgs IS the intended provider

        dedupe_key = f"degraded-alert:{date.today().isoformat()}"
        if db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, dedupe_key):
            return
        db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, dedupe_key, "1")

        exhausted = all(get_monthly_usage(p.name) >= (p.monthly_quota() or 0) for p in metered)
        reason = "quotas exhausted" if exhausted else "providers failing"
        logger.warning(
            "Web search degraded to DuckDuckGo fallback",
            extra={"reason": reason, "metered_providers": [p.name for p in metered]},
        )

        if not Config.ALLOWED_EMAILS:
            return
        operator = db.get_user_by_email(Config.ALLOWED_EMAILS[0])
        if operator is None:
            return
        # Imported here to avoid a module-load cycle (push imports db/config)
        from src.utils.push import send_push_to_user

        send_push_to_user(
            operator.id,
            "Web search degraded",
            f"Searches are falling back to DuckDuckGo ({reason}). "
            "Results will be weaker until quotas reset.",
            tag="search-degraded",
        )
    except Exception:
        logger.exception("Failed to send search degradation alert")


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
