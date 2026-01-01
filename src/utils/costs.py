"""Cost calculation utilities for tracking LLM usage costs."""

from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_currency_rates() -> dict[str, float]:
    """Get currency exchange rates, preferring DB values over Config defaults.

    Returns:
        Dictionary of currency code to rate (USD base)
    """
    # Import here to avoid circular dependency
    from src.db.models import db

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
    return Config.MODEL_PRICING.get(model_name, Config.MODEL_PRICING["gemini-3-flash-preview"])


def calculate_token_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost for token usage.

    Args:
        model_name: The model identifier
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Cost in USD
    """
    pricing = get_model_pricing(model_name)
    input_cost = (input_tokens / 1_000_000) * pricing.get("input", 0.0)
    output_cost = (output_tokens / 1_000_000) * pricing.get("output", 0.0)
    return input_cost + output_cost


def calculate_image_generation_cost(usage_metadata: dict[str, Any]) -> float:
    """Calculate cost for image generation from API usage_metadata.

    Args:
        usage_metadata: Usage metadata dict with prompt_token_count, candidates_token_count, thoughts_token_count

    Returns:
        Cost in USD
    """
    prompt_tokens = usage_metadata.get("prompt_token_count", 0)
    candidates_tokens = usage_metadata.get("candidates_token_count", 0)
    thoughts_tokens = usage_metadata.get("thoughts_token_count", 0)

    # Calculate cost using image generation model pricing
    # Input tokens (prompt) are charged at input rate
    # Output tokens (candidates + thoughts) are charged at output rate
    image_model_pricing = Config.MODEL_PRICING["gemini-3-pro-image-preview"]
    input_cost = (prompt_tokens / 1_000_000) * image_model_pricing["input"]
    output_cost = ((candidates_tokens + thoughts_tokens) / 1_000_000) * image_model_pricing[
        "output"
    ]

    total_cost: float = float(input_cost + output_cost)
    logger.debug(
        "Image generation cost calculated",
        extra={
            "prompt_tokens": prompt_tokens,
            "candidates_tokens": candidates_tokens,
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
) -> float:
    """Calculate total cost for a message.

    Args:
        model_name: The model identifier
        input_tokens: Number of input tokens (from API usage_metadata)
        output_tokens: Number of output tokens (from API usage_metadata)
        image_generation_cost: Cost for image generation (if any images were generated)

    Returns:
        Total cost in USD
    """
    token_cost = calculate_token_cost(model_name, input_tokens, output_tokens)
    total = token_cost + image_generation_cost
    logger.debug(
        "Cost calculated",
        extra={
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
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
    elif currency == "CZK":
        return f"{amount:.2f} Kč"
    elif currency == "EUR":
        return f"€{amount:.4f}"
    elif currency == "GBP":
        return f"£{amount:.4f}"
    else:
        return f"{amount:.4f} {currency}"
