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


# --- Task 2: limits decide when the turn stops --------------------------------

from langchain_core.messages import ToolMessage  # noqa: E402

from src.agent.round_cap import round_cap_override  # noqa: E402
from src.agent.tool_round_check import check_tool_results  # noqa: E402


@pytest.fixture
def budgets(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(Config, "TURN_BUDGETS_ENABLED", True)
    monkeypatch.setattr(Config, "TURN_COST_LIMIT_USD", 0.15)
    monkeypatch.setattr(Config, "TURN_TIME_BUDGET_SECONDS", 240.0)
    monkeypatch.setattr(Config, "TURN_WRAP_UP_FRACTION", 0.8)
    monkeypatch.setattr(Config, "TURN_MAX_TOOL_ROUNDS", 20)
    monkeypatch.setattr("src.agent.tool_round_check.get_conversation_context", lambda: (None, None))
    return monkeypatch


def _after_tools(now: float = 0.0, **extra: Any) -> Any:
    """A state right after a tool round, `now` seconds into the turn."""
    return {
        "messages": [
            HumanMessage(content="find it"),
            AIMessage(
                content="",
                id="a1",
                tool_calls=[{"name": "web_search", "args": {"q": "x"}, "id": "c1"}],
            ),
            ToolMessage(content="result", tool_call_id="c1", name="web_search", id="t1"),
        ],
        "tool_retries": 0,
        "tool_rounds": 0,
        "turn_started_at": -now,
        "turn_cost_usd": 0.01,
        "failed_calls": {},
        **extra,
    }


def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.turn_budget.time.monotonic", lambda: 0.0)


class TestLimits:
    def test_cost_limit_stops_the_turn(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        out = check_tool_results(_after_tools(turn_cost_usd=0.16))
        assert out["final_answer"] == "cost"

    def test_time_limit_stops_the_turn(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        out = check_tool_results(_after_tools(now=241))
        assert out["final_answer"] == "time"

    def test_round_backstop_stops_the_turn(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        assert check_tool_results(_after_tools(tool_rounds=19))["final_answer"] == "rounds"
        assert "final_answer" not in check_tool_results(_after_tools(tool_rounds=18))
        with round_cap_override(4):
            assert check_tool_results(_after_tools(tool_rounds=3))["final_answer"] == "rounds"

    def test_no_limit_no_stop_and_no_nudge(self, budgets: pytest.MonkeyPatch) -> None:
        """The round-4 'answer within a round or two' nudge is gone."""
        _clock(budgets)
        out = check_tool_results(_after_tools(tool_rounds=3))
        assert "final_answer" not in out
        assert "messages" not in out

    def test_wrap_up_notice_once_on_the_tool_result(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        state = _after_tools(now=200)

        out = check_tool_results(state)

        assert out["wrap_up_noticed"] is True
        [notice] = out["messages"]
        assert isinstance(notice, ToolMessage) and notice.id == state["messages"][-1].id
        assert str(notice.content).endswith("finish with what you have in your next reply.]")
        again = check_tool_results({**_after_tools(now=210), "wrap_up_noticed": True})
        assert "messages" not in again

    def test_time_budget_past_due_stops_once(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        out = check_tool_results(_after_tools(now=900))
        assert out["final_answer"] == "time"
        assert not out.get("wrap_up_noticed")

    def test_interjection_after_stop_keeps_tools_off(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        budgets.setattr("src.agent.tool_round_check.get_conversation_context", lambda: ("c", "u"))
        budgets.setattr(
            "src.agent.tool_round_check.interjection.pop_interjection", lambda _u, _c: "use metric"
        )
        out = check_tool_results(_after_tools(final_answer="cost"))
        assert out["final_answer"] == "cost"
        assert "use metric" in str(out["messages"][-1].content)

    def test_a_stop_logs_its_reason(
        self, budgets: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _clock(budgets)
        with caplog.at_level("INFO"):
            check_tool_results(_after_tools(now=241, tool_rounds=4))
        [record] = [r for r in caplog.records if r.getMessage() == "Turn budget stop"]
        assert (record.reason, record.tool_rounds, record.elapsed_s) == ("time", 5, 241.0)
        assert record.cost_usd == pytest.approx(0.01)

    def test_budgets_off_keeps_the_old_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "TURN_BUDGETS_ENABLED", False)
        monkeypatch.setattr(
            "src.agent.tool_round_check.get_conversation_context", lambda: (None, None)
        )
        nudge = check_tool_results(
            _after_tools(tool_rounds=Config.AGENT_TOOL_ROUNDS_SOFT_NUDGE - 1)
        )
        capped = check_tool_results(_after_tools(tool_rounds=Config.AGENT_MAX_TOOL_ROUNDS - 1))
        assert "Be efficient" in str(nudge["messages"][0].content)
        assert "Stop calling tools now" in str(capped["messages"][0].content)
        assert "final_answer" not in capped
