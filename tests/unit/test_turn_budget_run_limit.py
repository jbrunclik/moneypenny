"""A run's time budget can be capped below the turn default: the scheduler
pass caps it at the time left before systemd kills the pass, so the run
stops on time with its wrap-up instead of being killed and replayed
(docs/superpowers/specs/2026-11-15-run-resume-and-tick-deadline-design.md)."""

from __future__ import annotations

import time
from typing import Any

from src.agent import turn_budget
from src.agent.turn_budget import (
    budget_stop,
    initial_state,
    run_time_budget,
    stop_facts,
    time_budget_s,
    wrap_up_due,
)
from src.config import Config


def _started(state: dict[str, Any], seconds_ago: float) -> Any:
    return {**state, "turn_started_at": time.monotonic() - seconds_ago}


def test_a_turn_has_the_default_budget() -> None:
    state = initial_state([])
    assert state["turn_time_budget_s"] == Config.TURN_TIME_BUDGET_SECONDS
    assert time_budget_s(state) == Config.TURN_TIME_BUDGET_SECONDS


def test_inside_a_capped_run_the_turn_gets_the_cap() -> None:
    with run_time_budget(30):
        state = initial_state([])
    assert state["turn_time_budget_s"] == 30
    assert initial_state([])["turn_time_budget_s"] == Config.TURN_TIME_BUDGET_SECONDS


def test_the_cap_stops_the_turn_before_the_default_would() -> None:
    with run_time_budget(30):
        state = _started(dict(initial_state([])), 31)
    assert Config.TURN_TIME_BUDGET_SECONDS > 31
    assert budget_stop(state, tool_rounds=1) == "time"


def test_the_wrap_up_notice_follows_the_cap() -> None:
    with run_time_budget(30):
        state = _started(dict(initial_state([])), 30 * Config.TURN_WRAP_UP_FRACTION + 1)
    assert wrap_up_due(state) is True


def test_the_stop_names_the_capped_limit() -> None:
    with run_time_budget(30):
        state = _started(dict(initial_state([])), 31)
    assert "the 30 s time limit" in stop_facts("time", state, 1)


def test_a_state_without_the_key_uses_the_default() -> None:
    assert time_budget_s({"messages": []}) == Config.TURN_TIME_BUDGET_SECONDS  # type: ignore[typeddict-item]
    assert turn_budget.Config is Config
