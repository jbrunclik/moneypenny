"""Deep-research cost and time estimate, from config constants only.

The model never states a price: the offer shows this estimate, the client
recomputes it live from the same rates while the plan is edited, and the
server recomputes it when the run starts.
"""

import math

from src.config import Config
from src.utils.costs import convert_currency


def estimate_rates() -> dict[str, float]:
    """Everything the client needs to recompute the estimate live."""
    return {
        "base_minutes": Config.DEEP_RESEARCH_EST_BASE_MINUTES,
        "per_wave_minutes": Config.DEEP_RESEARCH_EST_PER_WAVE_MINUTES,
        "parallelism": float(Config.DEEP_RESEARCH_PARALLELISM),
        "base_czk": convert_currency(Config.DEEP_RESEARCH_EST_BASE_USD, Config.COST_CURRENCY),
        "per_item_czk": convert_currency(
            Config.DEEP_RESEARCH_EST_PER_ITEM_USD, Config.COST_CURRENCY
        ),
    }


def estimate(n_items: int, rates: dict[str, float] | None = None) -> dict[str, int]:
    """{"minutes", "cost_czk"} for a plan of n_items sub-questions.

    Minutes round up (a wave of parallel subagents is the unit); cost rounds
    to the nearest unit of the display currency.
    """
    r = rates or estimate_rates()
    waves = math.ceil(max(n_items, 1) / max(r["parallelism"], 1))
    return {
        "minutes": math.ceil(r["base_minutes"] + waves * r["per_wave_minutes"]),
        "cost_czk": int(r["base_czk"] + n_items * r["per_item_czk"] + 0.5),
    }
