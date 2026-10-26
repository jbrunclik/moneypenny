"""Quota-aware search provider router.

Providers are tried in priority order — Brave, Tavily, Exa, Linkup, then
DuckDuckGo (ddgs) as the unmetered terminal fallback. A provider is skipped when its
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

import time
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.config import Config
from src.db.models import db
from src.services import search_adapters
from src.services.push import send_push_to_user
from src.services.search_adapters import SearchProviderError
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Usage counters are global app state, not per-user data - stored under a
# sentinel user id in the per-user kv_store table
_SYSTEM_USER_ID = "__system__"
USAGE_NAMESPACE = "search-usage"


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
        "linkup": Config.SEARCH_BILLING_DAY_LINKUP,
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
    """kv_store key for a provider's consecutive-failure count this period.

    Shares the usage counter's period suffix, so a trip clears exactly when
    the provider's quota resets.
    """
    return f"breaker:{provider}:{period_start(_billing_anchor(provider), date.today())}"


def breaker_last_key(provider: str) -> str:
    """kv_store key for the epoch of a provider's last failure this period.

    Split from the count so the count can use an atomic increment: failures
    arrive simultaneously across gunicorn workers, and a read-modify-write
    counter loses exactly the updates that matter. Last-write-wins is fine
    for this timestamp - it only paces the half-open probe.
    """
    return f"breaker-last:{breaker_key(provider)}"


def breaker_exhausted_key(provider: str) -> str:
    """kv_store key marking a provider as out of credits for this period."""
    return f"breaker-exhausted:{breaker_key(provider)}"


def _now() -> float:
    """Epoch seconds - a seam so tests can control the breaker clock without
    patching the global time.time (which also drives date.today())."""
    return time.time()


def _breaker_state(provider: str) -> tuple[int, float]:
    """(consecutive failures, epoch of the last failure); (0, 0.0) when clear.

    Unparseable values read as clear. That covers the legacy {"fails": N}
    blobs this counter replaced: they are period-scoped and expire on their
    own, so treating them as clear costs at most one billing period of
    breaker history rather than wedging a provider off.
    """
    raw = db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider))
    if not raw:
        return 0, 0.0
    try:
        fails = int(raw)
    except ValueError, TypeError:
        return 0, 0.0
    last_raw = db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_last_key(provider))
    try:
        last = float(last_raw) if last_raw else 0.0
    except ValueError, TypeError:
        last = 0.0
    return fails, last


def _breaker_tripped(provider: str) -> bool:
    """Whether the provider should be skipped right now.

    Tripped once failures reach the threshold, EXCEPT for a single half-open
    probe allowed once the probe interval has elapsed since the last failure -
    so a transient (non-exhaustion) outage recovers within a day instead of
    staying down until the billing period rolls over.
    """
    if db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_exhausted_key(provider)):
        return True  # terminal for the period; the probe would only re-confirm
    fails, last = _breaker_state(provider)
    if fails < Config.SEARCH_BREAKER_THRESHOLD:
        return False
    return _now() - last < Config.SEARCH_BREAKER_PROBE_SECONDS


def _record_breaker_failure(provider: str, exhausted: bool = False) -> None:
    fails = db.kv_increment(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider))
    db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_last_key(provider), str(_now()))
    if exhausted:
        # One authoritative "out of credits" beats counting to the threshold
        db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_exhausted_key(provider), "1")
        logger.info("Search provider out of credits for the period", extra={"provider": provider})
    logger.debug("Search breaker failure recorded", extra={"provider": provider, "fails": fails})


def _reset_breaker(provider: str) -> None:
    """Clear the breaker after a success (no-op when already clear)."""
    fails, _ = _breaker_state(provider)
    # Unconditional: a pre-migration JSON blob reads as 0 fails, so guarding
    # the delete on `fails` would leave that row orphaned until the billing
    # period rolls the key name over. kv_delete is idempotent.
    deleted = db.kv_delete(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_key(provider))
    db.kv_delete(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_last_key(provider))
    db.kv_delete(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_exhausted_key(provider))
    if fails or deleted:
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
    for provider in _ordered_providers():
        if _provider_available(provider):
            return provider.name
    return "ddgs"


def _configured_metered() -> list[_Provider]:
    """Metered providers with a key set (i.e. ones we expect to serve)."""
    return [p for p in _ordered_providers() if p.monthly_quota() is not None and p.api_key()]


def has_metered_providers() -> bool:
    """Whether any metered provider is configured at all.

    A box with no keys is not "degraded" when ddgs serves - there, ddgs is
    the intended provider rather than a fallback.
    """
    return bool(_configured_metered())


def is_degraded() -> bool:
    """Whether searches are running on the unmetered ddgs fallback.

    True only when every configured metered provider is unavailable - spent,
    breaker-tripped, or keyless. A provider erroring on one call is NOT
    degradation: search_web falls through and the next search uses it again.

    A box with no metered keys at all is not degraded either: there, ddgs is
    the intended provider, not a fallback.
    """
    return bool(_configured_metered()) and active_provider() == "ddgs"


def search_web(query: str, num_results: int) -> list[dict[str, str]]:
    """Run one web search; returns [{title, url, snippet}].

    Thin wrapper over search_web_detailed for callers that don't care which
    provider served.
    """
    return search_web_detailed(query, num_results)[0]


def search_web_detailed(query: str, num_results: int) -> tuple[list[dict[str, str]], str]:
    """Run one web search; returns ([{title, url, snippet}], served_by).

    Routing: first configured provider with quota remaining; a provider
    error falls through to the next. Zero results for a query containing
    quote operators triggers ONE retry with the operators stripped on the
    same provider: models write Google-style exact-match queries that
    return nothing, then burn whole LLM rounds rephrasing.

    `served_by` names the provider that actually answered. Callers need it
    because availability checked BEFORE a search does not describe it: a
    provider can look available, fail, and fall through to ddgs inside this
    very call. Anything that reports on the results themselves must use
    this, not a pre-call is_degraded() snapshot.

    Raises SearchProviderError when every available provider failed.
    """
    last_error: SearchProviderError | None = None

    for provider in _ordered_providers():
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
                _record_breaker_failure(provider.name, exhausted=error.exhausted)
            last_error = error
            continue
        if metered:
            _reset_breaker(provider.name)
        _notify_if_degraded(provider.name)
        return results, provider.name

    raise last_error or SearchProviderError("No search provider available", retriable=True)


def _out_of_credits(provider: _Provider) -> bool:
    """Used up by our count, or the provider said so (our count can lag it)."""
    if db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, breaker_exhausted_key(provider.name)):
        return True
    return get_monthly_usage(provider.name) >= (provider.monthly_quota() or 0)


def _notify_if_degraded(served_by: str) -> None:
    """Alert the operator (once per day) when every metered provider is
    unavailable and ddgs is all that's left - otherwise quality degrades
    silently when quotas run out mid-period. Never breaks the search that
    triggered it.

    A single provider erroring is NOT degradation: search_web falls through
    to the next provider, and the next search will use the erroring one
    again once it recovers. Alerting on that both cries wolf and consumes
    the daily dedupe slot a genuine exhaustion would need later that day -
    so the check is "nothing metered is available", not "ddgs served".
    """
    if served_by != "ddgs":
        return
    try:
        metered = _configured_metered()
        if not is_degraded():
            # Either no metered keys (ddgs IS the intent here) or one is still
            # available and this was just a blip on the way through.
            return

        dedupe_key = f"degraded-alert:{date.today().isoformat()}"
        if db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, dedupe_key):
            return
        db.kv_set(_SYSTEM_USER_ID, USAGE_NAMESPACE, dedupe_key, "1")

        exhausted = all(_out_of_credits(p) for p in metered)
        reason = "quotas exhausted" if exhausted else "providers unavailable"
        logger.warning(
            "Web search degraded to DuckDuckGo fallback",
            extra={"reason": reason, "metered_providers": [p.name for p in metered]},
        )

        if not Config.ALLOWED_EMAILS:
            return
        operator = db.get_user_by_email(Config.ALLOWED_EMAILS[0])
        if operator is None:
            return
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


# Priority order: quality-per-free-search first, unmetered fallback last.
# The search callables resolve the adapters at CALL time (late binding) so
# tests can patch search_adapters.search_* like any module attribute.
_PROVIDERS: tuple[_Provider, ...] = (
    _Provider(
        "brave",
        lambda: Config.BRAVE_SEARCH_API_KEY,
        lambda: Config.SEARCH_QUOTA_BRAVE_MONTHLY,
        lambda q, n: search_adapters.search_brave(q, n),
    ),
    _Provider(
        "tavily",
        lambda: Config.TAVILY_API_KEY,
        lambda: Config.SEARCH_QUOTA_TAVILY_MONTHLY,
        lambda q, n: search_adapters.search_tavily(q, n),
    ),
    _Provider(
        "exa",
        lambda: Config.EXA_API_KEY,
        lambda: Config.SEARCH_QUOTA_EXA_MONTHLY,
        lambda q, n: search_adapters.search_exa(q, n),
    ),
    _Provider(
        "linkup",
        lambda: Config.LINKUP_API_KEY,
        lambda: Config.SEARCH_QUOTA_LINKUP_MONTHLY,
        lambda q, n: search_adapters.search_linkup(q, n),
    ),
    _Provider("ddgs", lambda: "", lambda: None, lambda q, n: search_adapters.search_ddgs(q, n)),
)


def _ordered_providers() -> list[_Provider]:
    """Providers in SEARCH_PROVIDER_ORDER, the rest in default order, ddgs last."""
    metered = {p.name: p for p in _PROVIDERS if p.monthly_quota() is not None}
    ordered: list[_Provider] = []
    for name in (n.strip() for n in Config.SEARCH_PROVIDER_ORDER.split(",")):
        if name in metered and metered[name] not in ordered:
            ordered.append(metered[name])
        elif name and name != "ddgs":
            logger.warning("Unknown provider in SEARCH_PROVIDER_ORDER", extra={"provider": name})
    ordered += [p for p in metered.values() if p not in ordered]
    return ordered + [p for p in _PROVIDERS if p.monthly_quota() is None]


def quota_status() -> list[dict[str, Any]]:
    """Each provider this billing period, in priority order (the admin page).

    `available` is whether search_web() would try it right now: a key is set,
    the breaker isn't tripped and the quota isn't used up.
    """
    return [
        {
            "provider": provider.name,
            "configured": provider.monthly_quota() is None or bool(provider.api_key()),
            "used": get_monthly_usage(provider.name),
            "quota": provider.monthly_quota(),
            "available": _provider_available(provider),
        }
        for provider in _ordered_providers()
    ]


def degraded_today() -> bool:
    """Whether search fell back to the free provider at some point today."""
    key = f"degraded-alert:{date.today().isoformat()}"
    return bool(db.kv_get(_SYSTEM_USER_ID, USAGE_NAMESPACE, key))
