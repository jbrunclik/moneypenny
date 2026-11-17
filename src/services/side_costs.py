"""Record what a side call cost (Nov 15 2026 audit: titles, reviews, AI
assist, compaction and memory review never reached message_costs, so the
admin page understated the bill; docs/superpowers/specs/2026-11-15-cost-telemetry-design.md).

Takes a LangChain reply (its ``usage_metadata`` dict) or a google-genai
response (its ``usage_metadata`` object). Never raises into the side call.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.config import Config
from src.db.models import db
from src.services.costs import calculate_token_cost
from src.utils.logging import get_logger
from src.utils.service_tier import FLEX, served_tier

logger = get_logger(__name__)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _tokens(usage: object) -> tuple[int, int, int] | None:
    """(input, cached input, output) from either SDK's usage, or None."""
    metadata = getattr(usage, "usage_metadata", None)
    if isinstance(metadata, Mapping):  # LangChain
        details = metadata.get("input_token_details")
        cached = details.get("cache_read") if isinstance(details, Mapping) else 0
        return _int(metadata.get("input_tokens")), _int(cached), _int(metadata.get("output_tokens"))
    if metadata is not None:  # google-genai
        output = _int(getattr(metadata, "candidates_token_count", 0)) + _int(
            getattr(metadata, "thoughts_token_count", 0)
        )
        return (
            _int(getattr(metadata, "prompt_token_count", 0)),
            _int(getattr(metadata, "cached_content_token_count", 0)),
            output,
        )
    return None


def record_side_cost(feature: str, model: str, usage: object, user_id: str | None = None) -> None:
    """Record one side call's tokens and cost; logged, never raised, on failure."""
    tokens = _tokens(usage)
    if tokens is None or not any(tokens):
        logger.warning("Side call without usage", extra={"feature": feature, "model": model})
        return
    try:
        cost = calculate_token_cost(model, tokens[0], tokens[2], tokens[1])
        tier = served_tier(usage)
        if tier == FLEX:
            cost *= Config.FLEX_PRICE_RATIO
        db.add_side_cost(feature, model, tokens, cost, user_id=user_id, service_tier=tier)
    except Exception:  # telemetry must not break the call it measures
        logger.exception("Side cost not recorded", extra={"feature": feature})
