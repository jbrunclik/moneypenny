"""Gemini's Flex tier: half price for calls that can wait.

Flex is synchronous but queued: a tiny Hydrogen call took 48-84 s on Flex
against ~2 s standard, and Carbon timed out (504) after 3 min (probes, Nov
17 2026). Requests may be shed under load (503), and Flex never upgrades
itself to standard - so a call that Flex refuses or times out runs again on
the standard tier. Use it only where nobody waits for the answer.
"""

import time

import httpx
from google.genai import errors, types

from src.agent.gemini_clients import shared_genai_client
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Flex at capacity (503), rate-limited (429) or past its deadline (504)
_FALLBACK_CODES = frozenset({429, 503, 504})


def generate_on_flex(
    model: str, contents: str, config: types.GenerateContentConfig, *, feature: str
) -> types.GenerateContentResponse:
    """generate_content on the Flex tier, falling back to standard when Flex
    refuses or times out (logged "Flex call fell back"). The response's tier
    (src/utils/service_tier.py) says which one served it."""
    client = shared_genai_client()
    flex = config.model_copy(
        update={
            "service_tier": types.ServiceTier.FLEX,
            "http_options": types.HttpOptions(timeout=Config.FLEX_TIMEOUT_SECONDS * 1000),
        }
    )
    started = time.monotonic()
    try:
        return client.models.generate_content(model=model, contents=contents, config=flex)
    except errors.APIError as e:
        if e.code not in _FALLBACK_CODES:
            raise
        reason = str(e.code)
    except httpx.TimeoutException:
        reason = "timeout"
    logger.warning(
        "Flex call fell back",
        extra={
            "feature": feature,
            "model": model,
            "reason": reason,
            "waited_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return client.models.generate_content(model=model, contents=contents, config=config)
