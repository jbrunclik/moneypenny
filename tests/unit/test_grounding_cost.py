"""The grounding verifier's tokens are priced at its own model's rates."""

from unittest.mock import patch

import pytest

from src.api.utils import calculate_and_save_message_cost, calculate_grounding_cost
from src.utils.costs import calculate_token_cost

_USAGE = {
    "model": "gemini-3.5-flash-lite",
    "input_tokens": 10_000,
    "output_tokens": 50,
    "cached_input_tokens": 0,
}


def test_prices_at_the_verifier_model() -> None:
    expected = calculate_token_cost("gemini-3.5-flash-lite", 10_000, 50)

    assert calculate_grounding_cost({"grounding_usage": _USAGE}) == pytest.approx(expected)
    assert expected == pytest.approx(10_000 * 0.30 / 1e6 + 50 * 2.50 / 1e6)


def test_no_grounding_usage_costs_nothing() -> None:
    assert calculate_grounding_cost({}) == 0.0
    assert calculate_grounding_cost({"grounding_usage": "garbage"}) == 0.0


def test_message_cost_includes_grounding() -> None:
    with patch("src.api.utils.db") as db:
        calculate_and_save_message_cost(
            "msg",
            "conv",
            "user",
            "gemini-3.8-flash",
            {"input_tokens": 0, "output_tokens": 0, "grounding_usage": _USAGE},
            [],
            10,
        )

    saved_cost = db.save_message_cost.call_args.args[6]
    assert saved_cost == pytest.approx(calculate_grounding_cost({"grounding_usage": _USAGE}))
