"""Cost calculation utilities for tracking LLM usage costs."""

import json
from typing import Any

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_currency_rates() -> dict[str, float]:
    """Get currency exchange rates, preferring DB values over Config defaults.

    Returns:
        Dictionary of currency code to rate (USD base)
    """
    # Try to get rates from database first
    db_rates = db.get_currency_rates()
    if db_rates:
        return db_rates

    # Fall back to Config defaults
    return Config.CURRENCY_RATES.copy()


def get_model_pricing(model_name: str) -> dict[str, float]:
    """Get pricing for a model.

    Args:
        model_name: The model identifier

    Returns:
        Dict with 'input' and 'output' prices per million tokens
    """
    return Config.MODEL_PRICING.get(model_name, Config.MODEL_PRICING["gemini-3.8-flash"])


def calculate_token_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Calculate cost for token usage.

    Args:
        model_name: The model identifier
        input_tokens: Number of input tokens (INCLUDES any cached tokens,
            matching usage_metadata semantics)
        output_tokens: Number of output tokens
        cached_input_tokens: Subset of input_tokens served from the context
            cache (usage_metadata.input_token_details.cache_read), billed at
            the discounted cached_input rate

    Returns:
        Cost in USD
    """
    pricing = get_model_pricing(model_name)
    cached = min(max(cached_input_tokens, 0), input_tokens)
    uncached = input_tokens - cached
    input_cost = (uncached / 1_000_000) * pricing.get("input", 0.0)
    cached_cost = (cached / 1_000_000) * pricing.get("cached_input", pricing.get("input", 0.0))
    output_cost = (output_tokens / 1_000_000) * pricing.get("output", 0.0)
    return input_cost + cached_cost + output_cost


def calculate_image_generation_cost(usage_metadata: dict[str, Any]) -> float:
    """Calculate cost for image generation from API usage_metadata.

    Args:
        usage_metadata: Usage metadata dict with prompt_token_count, candidates_token_count,
            image_output_token_count (optional), thoughts_token_count

    Returns:
        Cost in USD
    """
    prompt_tokens = usage_metadata.get("prompt_token_count", 0)
    candidates_tokens = usage_metadata.get("candidates_token_count", 0)
    thoughts_tokens = usage_metadata.get("thoughts_token_count", 0)
    # Without a modality breakdown, treat all candidates as image output
    # (the tool requests IMAGE-only responses)
    image_tokens = min(
        usage_metadata.get("image_output_token_count", candidates_tokens), candidates_tokens
    )
    text_output_tokens = candidates_tokens - image_tokens + thoughts_tokens

    # Input (prompt) is charged at the input rate, image output at the image
    # rate, and text + thinking output at the (much lower) text output rate
    pricing = Config.MODEL_PRICING[Config.IMAGE_GENERATION_MODEL]
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    image_cost = (image_tokens / 1_000_000) * pricing["image_output"]
    text_output_cost = (text_output_tokens / 1_000_000) * pricing["output"]

    total_cost: float = float(input_cost + image_cost + text_output_cost)
    logger.debug(
        "Image generation cost calculated",
        extra={
            "prompt_tokens": prompt_tokens,
            "candidates_tokens": candidates_tokens,
            "image_tokens": image_tokens,
            "thoughts_tokens": thoughts_tokens,
            "total_cost_usd": total_cost,
        },
    )
    return total_cost


def calculate_total_cost(
    model_name: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_generation_cost: float = 0.0,
    cached_input_tokens: int = 0,
    tool_llm_cost: float = 0.0,
) -> float:
    """Calculate total cost for a message.

    Args:
        model_name: The model identifier
        input_tokens: Number of input tokens (from API usage_metadata)
        output_tokens: Number of output tokens (from API usage_metadata)
        image_generation_cost: Cost for image generation (if any images were generated)
        cached_input_tokens: Subset of input_tokens served from the context cache
        tool_llm_cost: LLM spend made inside tools (delegate_task subagent runs)

    Returns:
        Total cost in USD
    """
    token_cost = calculate_token_cost(
        model_name, input_tokens, output_tokens, cached_input_tokens=cached_input_tokens
    )
    total = token_cost + image_generation_cost + tool_llm_cost
    logger.debug(
        "Cost calculated",
        extra={
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "token_cost_usd": token_cost,
            "image_generation_cost_usd": image_generation_cost,
            "total_cost_usd": total,
        },
    )
    return total


def convert_currency(amount_usd: float, target_currency: str = "USD") -> float:
    """Convert USD amount to target currency.

    Args:
        amount_usd: Amount in USD
        target_currency: Target currency code (default: USD)

    Returns:
        Amount in target currency
    """
    if target_currency == "USD":
        return amount_usd

    rates = get_currency_rates()
    rate = rates.get(target_currency.upper(), 1.0)
    converted = amount_usd * rate
    logger.debug(
        "Currency converted",
        extra={
            "amount_usd": amount_usd,
            "target_currency": target_currency,
            "rate": rate,
            "converted": converted,
        },
    )
    return converted


def format_cost(amount: float, currency: str = "USD") -> str:
    """Format cost amount for display.

    Args:
        amount: Cost amount
        currency: Currency code

    Returns:
        Formatted string (e.g., "$0.05" or "1.15 Kč")
    """
    if currency == "USD":
        return f"${amount:.4f}"
    if currency == "CZK":
        return f"{amount:.2f} Kč"
    if currency == "EUR":
        return f"€{amount:.4f}"
    if currency == "GBP":
        return f"£{amount:.4f}"
    return f"{amount:.4f} {currency}"


def calculate_deep_research_cost(usage_info: dict[str, Any]) -> float:
    """USD of a deep-research run's subagents, each priced at its own model."""
    return float(
        sum(
            calculate_token_cost(
                str(u.get("model", "")),
                int(u.get("input_tokens", 0)),
                int(u.get("output_tokens", 0)),
                cached_input_tokens=int(u.get("cached_input_tokens", 0)),
            )
            for u in usage_info.get("deep_research_usage") or []
        )
    )


def calculate_and_save_message_cost(
    message_id: str,
    conversation_id: str,
    user_id: str,
    model: str,
    usage_info: dict[str, Any],
    tool_results: list[dict[str, Any]],
    response_length: int,
    mode: str = "batch",
) -> float:
    """Calculate and save cost for a message; returns the cost in USD.

    Args:
        message_id: The message ID
        conversation_id: The conversation ID
        user_id: The user ID
        model: The model used
        usage_info: Dict with 'input_tokens' and 'output_tokens'
        tool_results: List of tool result dicts
        response_length: Length of the response content (used for logging warnings when token metadata is missing)
        mode: 'batch' or 'stream' (for logging)
    """
    input_tokens = usage_info.get("input_tokens", 0)
    output_tokens = usage_info.get("output_tokens", 0)
    cached_input_tokens = usage_info.get("cached_input_tokens", 0)
    tool_rounds = usage_info.get("tool_rounds", 0)
    tool_call_count = usage_info.get("tool_call_count", 0)

    # Costs incurred inside tools: image generations + delegate subagent runs
    image_cost = calculate_image_generation_cost_from_tool_results(tool_results)
    delegate_cost = calculate_delegate_cost_from_tool_results(tool_results)

    # Log warning if no usage metadata (should be rare - indicates API issue)
    if input_tokens == 0 and output_tokens == 0:
        logger.warning(
            f"No token usage metadata found in {mode} mode",  # noqa: G004
            extra={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": model,
                "response_length": response_length,
            },
        )

    cost_usd = calculate_total_cost(
        model,
        input_tokens,
        output_tokens,
        image_generation_cost=image_cost,
        cached_input_tokens=cached_input_tokens,
        tool_llm_cost=delegate_cost
        + calculate_grounding_cost(usage_info)
        + calculate_freshness_cost(usage_info)
        + calculate_deep_research_cost(usage_info),
    )

    db.save_message_cost(
        message_id,
        conversation_id,
        user_id,
        model,
        input_tokens,
        output_tokens,
        cost_usd,
        image_generation_cost_usd=image_cost,
        cached_input_tokens=cached_input_tokens,
        tool_rounds=tool_rounds,
        tool_call_count=tool_call_count,
        duration_ms=usage_info.get("duration_ms"),
        tool_errors=usage_info.get("tool_errors", 0),
        tools_used=usage_info.get("tools_used"),
    )

    logger.info(
        f"{mode.capitalize()} chat cost saved",  # noqa: G004
        extra={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )
    return cost_usd


def calculate_image_generation_cost_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> float:
    """Calculate total cost for all image generations from tool_results.

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        Total cost in USD for all image generations (0.0 if no images or missing usage_metadata)
    """
    total_cost = 0.0

    for tool_result in tool_results:
        if not isinstance(tool_result, dict) or tool_result.get("type") != "tool":
            continue

        content = tool_result.get("content", "")
        if not content:
            continue

        try:
            content_data = json.loads(content) if isinstance(content, str) else {}
        except json.JSONDecodeError, TypeError:
            continue

        # Check if this is a generate_image result with usage_metadata
        # The image data is in _full_result.image (not sent to LLM), but usage_metadata is at top level
        if isinstance(content_data, dict) and "_full_result" in content_data:
            usage_metadata = content_data.get("usage_metadata")
            if usage_metadata:
                total_cost += calculate_image_generation_cost(usage_metadata)
            else:
                logger.warning(
                    "Image generation tool result missing usage_metadata",
                    extra={"tool_result_keys": list(content_data.keys())},
                )

    return total_cost


def calculate_delegate_cost_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> float:
    """Sum the token cost of delegate_task subagent runs in tool_results.

    delegate_task embeds its subagent's usage under a top-level
    _delegate_usage key in the tool result JSON (priced at the subagent's own
    model, which may differ from the conversation's).

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        Total cost in USD (0.0 when no delegate runs happened)
    """
    total_cost = 0.0

    for tool_result in tool_results:
        if not isinstance(tool_result, dict) or tool_result.get("type") != "tool":
            continue

        content = tool_result.get("content", "")
        if not content or not isinstance(content, str):
            continue

        try:
            content_data = json.loads(content)
        except json.JSONDecodeError, TypeError:
            continue

        if not isinstance(content_data, dict):
            continue
        usage = content_data.get("_delegate_usage")
        if not isinstance(usage, dict):
            continue

        total_cost += calculate_token_cost(
            str(usage.get("model", "")),
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        )

    return total_cost


def calculate_freshness_cost(usage_info: dict[str, Any]) -> float:
    """Cost of the freshness gate's call (src/agent/freshness.py), at its own model."""
    usage = usage_info.get("freshness_usage")
    if not isinstance(usage, dict):
        return 0.0
    return calculate_token_cost(
        str(usage.get("model", "")),
        int(usage.get("input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
    )


def calculate_grounding_cost(usage_info: dict[str, Any]) -> float:
    """Cost of the post-answer grounding check, priced at its own model.

    The verifier's usage rides in usage_info["grounding_usage"]
    (src/agent/grounding_check.py) - a different, cheaper model than the turn's.
    """
    usage = usage_info.get("grounding_usage")
    if not isinstance(usage, dict):
        return 0.0
    return calculate_token_cost(
        str(usage.get("model", "")),
        int(usage.get("input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
    )
