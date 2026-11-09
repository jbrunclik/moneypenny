"""Turn budgets: every turn is bounded by its cost, its time and loops, not a
round count (docs/superpowers/plans/2026-11-09-turn-budgets.md)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from src.agent import chat_node as chat_node_module
from src.agent.chat_node import chat_node
from src.agent.content import extract_image_prompts_from_messages
from src.agent.turn_budget import (
    call_cost_usd,
    initial_state,
    model_view,
    with_note,
)
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

    def test_cost_uses_the_turn_model_by_name(self) -> None:
        """A real Gemini model has no model_name attribute: the graph passes the name."""
        model = MagicMock(spec=["invoke"])
        model.invoke.return_value = _reply()

        out = chat_node(initial_state([HumanMessage(content="hi")]), model, model_name=ADVANCED)

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
        assert notice.content == "result"  # the stored result stays parseable
        [seen] = model_view([notice])
        assert str(seen.content).endswith("finish with what you have in your next reply.]")
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


# --- Task 3: one tools-off final answer -----------------------------------------

from src.agent.graph import should_continue  # noqa: E402
from src.agent.turn_budget import FALLBACK_LINE  # noqa: E402


def _final_state(*history: Any) -> Any:
    return {
        **initial_state([HumanMessage(content="find it"), *history]),
        "final_answer": "time",
    }


class TestFinalAnswer:
    def test_final_answer_drops_tool_calls(self, caplog: pytest.LogCaptureFixture) -> None:
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = AIMessage(
            content="Here is what I found.",
            tool_calls=[{"name": "web_search", "args": {"q": "more"}, "id": "c9"}],
        )

        with caplog.at_level("INFO"):
            out = chat_node(_final_state(), model)

        [reply] = out["messages"]
        assert (reply.content, reply.tool_calls) == ("Here is what I found.", [])
        assert any(r.getMessage() == "Turn final answer dropped tool calls" for r in caplog.records)

    def test_final_answer_ends_the_turn(self) -> None:
        state = _final_state(
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c9"}])
        )
        assert should_continue(state) == "end"

    def test_empty_final_answer_gets_a_fallback_line(self) -> None:
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = AIMessage(content="")
        earlier = AIMessage(
            content="The CNB fixing is 24.31 CZK.",
            tool_calls=[{"name": "fetch_url", "args": {}, "id": "c2"}],
        )

        out = chat_node(_final_state(earlier), model)

        assert out["messages"][0].content == f"The CNB fixing is 24.31 CZK.\n\n{FALLBACK_LINE}"

    def test_empty_final_answer_without_earlier_text(self) -> None:
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = AIMessage(content="")

        out = chat_node(_final_state(), model)

        assert out["messages"][0].content == FALLBACK_LINE

    def test_without_a_stop_tool_calls_are_kept(self) -> None:
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = AIMessage(
            content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c9"}]
        )
        out = chat_node(initial_state([HumanMessage(content="find it")]), model)
        assert out["messages"][0].tool_calls


# --- Task 5: why the turn stopped -----------------------------------------------

from src.agent.stream_events import StreamEventProcessor  # noqa: E402
from src.agent.turn_usage import TokenTotals, build_usage_info  # noqa: E402


class TestStoppedBy:
    def test_the_final_reply_is_marked_and_announced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writer = MagicMock()
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: writer)
        model = MagicMock(model_name=FAST)
        model.invoke.return_value = AIMessage(content="Done.")

        out = chat_node(_final_state(), model)

        assert out["messages"][0].response_metadata["turn_stop"] == "time"
        writer.assert_any_call(
            {"type": "turn_stop", "reason": "time", "dropped": [], "fallback": None}
        )

    def test_batch_usage_carries_the_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reply = AIMessage(content="Done.", response_metadata={"turn_stop": "cost"})
        assert build_usage_info(TokenTotals(), [reply], 10)["stopped_by"] == "cost"

    def test_streaming_usage_carries_the_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        processor = StreamEventProcessor([HumanMessage(content="go")])
        list(processor.process("custom", {"type": "turn_stop", "reason": "loop"}))

        [final] = [e for e in processor.finish(0.0) if e.get("type") == "final"]

        assert final["usage_info"]["stopped_by"] == "loop"

    def test_no_stop_no_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert build_usage_info(TokenTotals(), [AIMessage(content="hi")], 10)["stopped_by"] is None


class TestBatchingHint:
    def test_batching_hint_once_at_round_three(self, budgets: pytest.MonkeyPatch) -> None:
        _clock(budgets)
        budgets.setattr(Config, "TURN_BATCHING_HINT_ROUND", 3)
        state = _after_tools(tool_rounds=2)

        out = check_tool_results(state)

        [hinted] = out["messages"]
        assert hinted.id == "t1" and hinted.content == "result"
        [seen] = model_view([hinted])
        assert "several queries in one call" in str(seen.content)
        assert "answer" not in str(seen.content).split("]")[-1]  # no pressure to finish
        assert out["batching_hinted"] is True
        later = check_tool_results({**_after_tools(tool_rounds=3), "batching_hinted": True})
        assert "messages" not in later


class TestNotesReachOnlyTheModel:
    def test_the_model_sees_the_note_the_state_keeps_the_result(self) -> None:
        result = ToolMessage(content='{"results": []}', tool_call_id="c1", id="t1")
        noted = with_note(with_note(result, "[one]"), "[two]")
        model = MagicMock(spec=["invoke"])
        model.invoke.return_value = AIMessage(content="ok")
        call = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c1"}])

        chat_node(initial_state([HumanMessage(content="hi"), call, noted]), model, model_name=FAST)

        sent = model.invoke.call_args.args[0][-1]
        assert sent.content == '{"results": []}[one][two]'
        assert noted.content == '{"results": []}'


class TestStreamedFinalReply:
    def _stream(self, *events: tuple[str, Any]) -> dict[str, Any]:
        processor = StreamEventProcessor([HumanMessage(content="go")])
        out: list[dict[str, Any]] = []
        for mode, event in events:
            out.extend(processor.process(mode, event))
        out.extend(processor.finish(0.0))
        return {"events": out, "final": out[-1]}

    def test_an_empty_final_reply_streams_the_fallback_line(self) -> None:
        chunk = AIMessageChunk(
            content="",
            tool_calls=[{"name": "generate_image", "args": {"prompt": "x"}, "id": "c9"}],
        )
        stop = {"type": "turn_stop", "reason": "time", "dropped": ["c9"], "fallback": FALLBACK_LINE}

        run = self._stream(("messages", (chunk, {"langgraph_node": "chat"})), ("custom", stop))

        assert run["final"]["content"] == FALLBACK_LINE
        assert {"type": "token", "text": FALLBACK_LINE} in run["events"]
        assert {"type": "tool_end", "tool": "generate_image"} in run["events"]
        assert extract_image_prompts_from_messages(run["final"]["result_messages"]) == []
        assert run["final"]["usage_info"]["stopped_by"] == "time"

    def test_the_fallback_follows_earlier_streamed_text(self) -> None:
        chunk = AIMessageChunk(content="Found two of three.")
        stop = {"type": "turn_stop", "reason": "cost", "dropped": [], "fallback": FALLBACK_LINE}

        run = self._stream(("messages", (chunk, {"langgraph_node": "chat"})), ("custom", stop))

        assert run["final"]["content"] == f"Found two of three.\n\n{FALLBACK_LINE}"

    def test_chat_node_tells_the_stream_what_it_dropped_and_added(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        writer = MagicMock()
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: writer)
        model = MagicMock(spec=["invoke"])
        model.invoke.return_value = AIMessage(
            content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c9"}]
        )

        chat_node(_final_state(), model, model_name=FAST)

        writer.assert_any_call(
            {"type": "turn_stop", "reason": "time", "dropped": ["c9"], "fallback": FALLBACK_LINE}
        )
