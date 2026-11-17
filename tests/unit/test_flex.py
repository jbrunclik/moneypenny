"""The Flex tier: half price, queued, and refused under load (src/agent/flex.py).

Nov 17 2026 probes: a tiny Hydrogen call took 48-84 s on Flex and Carbon hit a
504 after 3 min; Flex never upgrades itself, so the code falls back to
standard, and the tier that served a call (a response header) sets its price.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from google.genai import errors, types

from src.agent import flex
from src.config import Config
from src.db.models import use_database
from src.services.costs import calculate_token_cost
from src.services.side_costs import record_side_cost
from src.utils.service_tier import served_tier

if TYPE_CHECKING:
    from src.db.models import Database


def _response(tier: str | None) -> SimpleNamespace:
    headers = {"x-gemini-service-tier": tier} if tier else {}
    return SimpleNamespace(
        text="ok",
        sdk_http_response=SimpleNamespace(headers=headers),
        usage_metadata=SimpleNamespace(
            prompt_token_count=1000,
            cached_content_token_count=0,
            candidates_token_count=100,
            thoughts_token_count=0,
        ),
    )


class _Models:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.tiers: list[object] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.tiers.append(config.service_tier)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _run(monkeypatch: pytest.MonkeyPatch, models: _Models) -> Any:
    monkeypatch.setattr(flex, "shared_genai_client", lambda: SimpleNamespace(models=models))
    config = types.GenerateContentConfig(temperature=0.2)
    return flex.generate_on_flex("gemini-4-hydrogen", "hi", config, feature="memory_review")


def _api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_asks_for_flex(monkeypatch: pytest.MonkeyPatch) -> None:
    models = _Models(_response("flex"))
    assert served_tier(_run(monkeypatch, models)) == "flex"
    assert models.tiers == [types.ServiceTier.FLEX]


@pytest.mark.parametrize(
    "refusal", [_api_error(503), _api_error(504), _api_error(429), httpx.ReadTimeout("slow")]
)
def test_falls_back_to_standard_when_flex_refuses(
    monkeypatch: pytest.MonkeyPatch, refusal: Exception
) -> None:
    models = _Models(refusal, _response(None))
    assert served_tier(_run(monkeypatch, models)) == "standard"
    assert models.tiers == [types.ServiceTier.FLEX, None]


def test_other_errors_are_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(errors.APIError):
        _run(monkeypatch, _Models(_api_error(400)))


def test_a_flex_call_is_priced_at_the_flex_rate(test_database: Database) -> None:
    with use_database(test_database):
        record_side_cost("memory_review", "gemini-4-hydrogen", _response("flex"))
        record_side_cost("memory_review", "gemini-4-hydrogen", _response(None))
        with test_database._pool.get_connection() as conn:
            rows = conn.execute(
                "SELECT cost_usd, service_tier FROM side_costs ORDER BY id"
            ).fetchall()

    full = calculate_token_cost("gemini-4-hydrogen", 1000, 100, 0)
    assert [tuple(r) for r in rows] == [
        (pytest.approx(full * Config.FLEX_PRICE_RATIO), "flex"),
        (pytest.approx(full), None),
    ]
