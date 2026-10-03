"""The deep-research estimate (src/agent/deep_research/estimate.py)."""

import pytest

from src.agent.deep_research.estimate import estimate, estimate_rates
from src.config import Config


@pytest.fixture(autouse=True)
def _rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_EST_BASE_USD", 0.12)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_EST_PER_ITEM_USD", 0.08)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_EST_BASE_MINUTES", 2.0)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_EST_PER_WAVE_MINUTES", 2.5)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 4)
    monkeypatch.setattr(
        "src.agent.deep_research.estimate.convert_currency", lambda usd, _c: usd * 23
    )


def test_cost_grows_per_item_and_minutes_per_wave() -> None:
    assert estimate(4) == {
        "minutes": 5,
        "cost_czk": 10,
    }  # 2 + 1 wave * 2.5 -> 4.5 -> 5; (0.12+0.32)*23
    assert estimate(5) == {"minutes": 7, "cost_czk": 12}  # 2 waves


def test_rates_reproduce_the_estimate_on_the_client() -> None:
    rates = estimate_rates()
    assert set(rates) == {
        "base_minutes",
        "per_wave_minutes",
        "parallelism",
        "base_czk",
        "per_item_czk",
    }
    assert estimate(3, rates) == estimate(3)
