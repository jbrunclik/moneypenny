"""Turn budgets: every turn is bounded by its cost, its time and loops, not a
round count (docs/superpowers/plans/2026-11-09-turn-budgets.md)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import chat_node as chat_node_module
from src.agent.chat_node import chat_node
from src.agent.turn_budget import call_cost_usd, initial_state
from src.config import Config
from src.services.costs import calculate_token_cost

FAST, ADVANCED = list(Config.MODELS)


def _reply(text: str = "ok", inp: int = 1000, out: int = 100) -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
    )


@pytest.fixture(autouse=True)
def _no_stream_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: MagicMock())


class TestTheTurnsBudget:
    def test_initial_state_starts_the_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.agent.turn_budget.time.monotonic", lambda: 123.0)
        messages = [HumanMessage(content="hi")]

        state = initial_state(messages)

        assert state["messages"] == messages
        assert (state["turn_started_at"], state["turn_cost_usd"], state["failed_calls"]) == (
            123.0,
            0.0,
            {},
        )

    def test_a_calls_cost_is_priced_with_cached_input(self) -> None:
        reply = AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": 1000,
                "output_tokens": 100,
                "total_tokens": 1100,
                "input_token_details": {"cache_read": 800},
            },
        )

        assert call_cost_usd(reply, FAST) == pytest.approx(
            calculate_token_cost(FAST, 1000, 100, cached_input_tokens=800)
        )

    def test_chat_node_adds_each_calls_cost(self) -> None:
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = _reply()
        state: Any = initial_state([HumanMessage(content="hi")])

        first = chat_node(state, model)
        second = chat_node({**state, **first}, model)

        one_call = calculate_token_cost(FAST, 1000, 100)
        assert first["turn_cost_usd"] == pytest.approx(one_call)
        assert second["turn_cost_usd"] == pytest.approx(2 * one_call)

    def test_cost_uses_the_answering_model(self) -> None:
        primary = MagicMock(model_name=FAST)
        backup = MagicMock(model_name=ADVANCED)
        backup.invoke.return_value = _reply()
        state: Any = {**initial_state([HumanMessage(content="hi")]), "model_fallback": ADVANCED}

        out = chat_node(state, primary, fallback=lambda: (ADVANCED, backup))

        assert out["turn_cost_usd"] == pytest.approx(calculate_token_cost(ADVANCED, 1000, 100))

    def test_nested_run_has_its_own_budget(self) -> None:
        """A subagent's graph run (delegate_task, deep research) starts its own
        budget and leaves the outer turn's untouched."""
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = _reply()
        outer: Any = {**initial_state([HumanMessage(content="hi")]), "turn_cost_usd": 0.05}

        inner = chat_node(initial_state([HumanMessage(content="sub-task")]), model)

        assert inner["turn_cost_usd"] == pytest.approx(calculate_token_cost(FAST, 1000, 100))
        assert outer["turn_cost_usd"] == 0.05
