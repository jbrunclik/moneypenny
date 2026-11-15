"""Read a page through Exa /contents when the direct fetch is refused.

Many shops, Wikipedia in bursts and manual sites answer the production host
with 403 or 429 whatever it sends; Exa reads them from its own network
(9 of 10 such pages, $0.009, measured Nov 15 2026 -
docs/superpowers/specs/2026-11-15-web-reading-design.md). The spend shares
Exa's search credit: billed into its usage counter by cost, stopped at
WEB_EXTRACT_QUOTA_SHARE of the quota, and an "out of credit" answer benches
Exa for search too. Other failures leave search alone.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.config import Config
from src.services.search_provider import bill_micro_usd, has_headroom, mark_out_of_credit
from src.utils.logging import get_logger
from src.utils.tls import shared_ssl_context

logger = get_logger(__name__)

_EXA_CONTENTS_ENDPOINT = "https://api.exa.ai/contents"
_MICRO = 1_000_000


def extract_available() -> bool:
    """Whether a refused page may be read through Exa now."""
    return has_headroom("exa", Config.WEB_EXTRACT_QUOTA_SHARE)


def record_extract_cost(cost_usd: float) -> None:
    """Bill an extract's cost into Exa's usage, in whole search units."""
    bill_micro_usd("exa", round(cost_usd * _MICRO), round(Config.EXA_SEARCH_UNIT_USD * _MICRO))


def extract_page(
    url: str, max_chars: int, direct_status: int | None = None
) -> tuple[str | None, str | None]:
    """The page's text as Exa reads it, cut at ``max_chars``; or the error.
    ``direct_status``: why the direct fetch was not used (403/429; None for
    a PDF), for the review's log line."""
    started = time.monotonic()
    text, error, cost = _read(url, max_chars)
    logger.info(
        "Page read via fallback",
        extra={
            "host": urlsplit(url).hostname,
            "via": "exa",
            "status": "ok" if text is not None else "failed",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "direct_status": direct_status,
            "cost_usd": cost,
            "error": error,
        },
    )
    return text, error


def _read(url: str, max_chars: int) -> tuple[str | None, str | None, float]:
    """(text, error, cost in USD)."""
    try:
        response = httpx.post(
            _EXA_CONTENTS_ENDPOINT,
            json={"urls": [url], "text": {"maxCharacters": max_chars}},
            headers={"x-api-key": Config.EXA_API_KEY, "Content-Type": "application/json"},
            timeout=Config.WEB_EXTRACT_TIMEOUT_SECONDS,
            verify=shared_ssl_context(),
        )
    except httpx.HTTPError as error:
        return None, f"reading service failed: {type(error).__name__}", 0.0
    if response.status_code == 402:
        mark_out_of_credit("exa")
        return None, "reading service is out of credit", 0.0
    if response.status_code != 200:
        return None, f"reading service answered HTTP {response.status_code}", 0.0
    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        return None, "reading service sent an unreadable answer", 0.0
    cost = float((body.get("costDollars") or {}).get("total") or 0)
    record_extract_cost(cost)
    return (*_page_text(body, max_chars), cost)


def _page_text(body: dict[str, Any], max_chars: int) -> tuple[str | None, str | None]:
    statuses = body.get("statuses") or []
    failed = next((s for s in statuses if s.get("status") != "success"), None)
    results = body.get("results") or []
    text = (results[0].get("text") or "").strip() if results else ""
    if failed is not None or not text:
        detail = (failed or {}).get("error") or {}
        code = detail.get("httpStatusCode") if isinstance(detail, dict) else None
        return None, f"reading service could not read it{f' (HTTP {code})' if code else ''}"
    return text[:max_chars], None
