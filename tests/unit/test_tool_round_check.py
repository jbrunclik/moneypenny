"""Characterization of check_tool_results: every branch, both guidance modes.

Pins the exact state update (message type, guidance text, counters) so the
self-correction node keeps sending the model the same words.
"""

import contextvars
import json
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.graph_state import AgentState
from src.agent.tool_round_check import check_tool_results
from src.agent.tools.context import set_conversation_context
from src.config import Config

_INTERJECTION = (
    '[USER INTERJECTION] The user just sent this while you were working: "use 2025"\n'
    "Adjust course immediately: incorporate this guidance into the current task, "
    "drop work it makes irrelevant, and acknowledge the change in your final answer."
)
_CAP = (
    "You have run 6 rounds of tool calls for this request. Stop calling tools now "
    "and answer the user with the information you already have. If you searched for "
    "something you could not find, say so and give your best answer with what is "
    "available. Do not issue more tool calls unless absolutely essential."
)
_NUDGE = (
    "You have used 4 tool rounds. Be efficient from here: consolidate remaining "
    "lookups (batch queries, prefer the research tool over separate fetches) and "
    "aim to answer within the next round or two."
)
_RETRY = (
    "The tool call failed with the following error. Analyze the error and try a "
    "different approach or different arguments. Do not repeat the same failing call."
    "\n\nError: {errors}"
)
_GIVE_UP = (
    "The tool has failed after multiple retries. Respond to the user explaining what "
    "happened and offer alternatives. Do not attempt to call the same tool again."
)


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 6)
    monkeypatch.setattr(Config, "AGENT_TOOL_ROUNDS_SOFT_NUDGE", 4)
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_RETRIES", 2)


def _state(results: list[ToolMessage], rounds: int = 0, retries: int = 0) -> AgentState:
    calls = [{"name": "web_search", "args": {}, "id": m.tool_call_id} for m in results]
    messages: list[BaseMessage] = [
        ToolMessage(content='{"error": "older round"}', tool_call_id="old"),
        AIMessage(content="", tool_calls=calls),
        *results,
    ]
    return {"messages": messages, "tool_retries": retries, "tool_rounds": rounds}


def _ok() -> ToolMessage:
    return ToolMessage(content='{"results": []}', tool_call_id="1")


def _error(text: str, retriable: bool = True, call_id: str = "1") -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"error": text, "retriable": retriable}), tool_call_id=call_id
    )


def _guidance(text: str, use_cache: bool) -> BaseMessage:
    if use_cache:
        return HumanMessage(content=f"[SYSTEM GUIDANCE]\n{text}\n[/SYSTEM GUIDANCE]")
    return SystemMessage(content=text)


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    if "messages" in out:
        out["messages"] = [(type(m).__name__, m.content) for m in out["messages"]]
    return out


def _expected(text: str, use_cache: bool, retries: int, rounds: int) -> dict[str, Any]:
    message = _guidance(text, use_cache)
    return {
        "tool_retries": retries,
        "tool_rounds": rounds,
        "messages": [(type(message).__name__, message.content)],
    }


@pytest.mark.parametrize("use_cache", [False, True])
class TestCheckToolResultsBranches:
    def test_clean_round_resets_retries(self, use_cache: bool) -> None:
        result = check_tool_results(_state([_ok()], retries=2), use_cache=use_cache)
        assert result == {"tool_retries": 0, "tool_rounds": 1}

    def test_interjection_keeps_retries_and_beats_the_cap(self, use_cache: bool) -> None:
        def run() -> dict[str, Any]:
            set_conversation_context("conv-1", "user-1")
            state = _state([_error("boom")], rounds=9, retries=1)
            return check_tool_results(state, use_cache=use_cache)

        with patch("src.agent.interjection.pop_interjection", return_value="use 2025") as pop:
            result = contextvars.copy_context().run(run)

        pop.assert_called_once_with("user-1", "conv-1")
        assert _summary(result) == _expected(_INTERJECTION, use_cache, retries=1, rounds=10)

    def test_round_cap(self, use_cache: bool) -> None:
        result = check_tool_results(_state([_error("boom")], rounds=5, retries=1), use_cache)
        assert _summary(result) == _expected(_CAP, use_cache, retries=0, rounds=6)

    def test_soft_nudge(self, use_cache: bool) -> None:
        result = check_tool_results(_state([_error("boom")], rounds=3, retries=1), use_cache)
        assert _summary(result) == _expected(_NUDGE, use_cache, retries=0, rounds=4)

    def test_retriable_error_asks_for_a_retry(self, use_cache: bool) -> None:
        errors = [_error("first", call_id="1"), _error("second", call_id="2")]
        result = check_tool_results(_state(errors, retries=1), use_cache=use_cache)
        retry = _RETRY.format(errors="second; first")
        assert _summary(result) == _expected(retry, use_cache, retries=2, rounds=1)

    def test_error_summary_keeps_three(self, use_cache: bool) -> None:
        errors = [_error(f"e{i}", call_id=str(i)) for i in range(4)]
        result = check_tool_results(_state(errors), use_cache=use_cache)
        retry = _RETRY.format(errors="e3; e2; e1")
        assert _summary(result) == _expected(retry, use_cache, retries=1, rounds=1)

    def test_status_error_counts_as_retriable(self, use_cache: bool) -> None:
        failed = ToolMessage(content="Error: x" * 50, tool_call_id="1", status="error")
        result = check_tool_results(_state([failed]), use_cache=use_cache)
        retry = _RETRY.format(errors=("Error: x" * 50)[:200])
        assert _summary(result) == _expected(retry, use_cache, retries=1, rounds=1)

    def test_retries_exhausted_gives_up(self, use_cache: bool) -> None:
        result = check_tool_results(_state([_error("boom")], retries=2), use_cache=use_cache)
        assert _summary(result) == _expected(_GIVE_UP, use_cache, retries=3, rounds=1)

    def test_permanent_error_gives_up_at_once(self, use_cache: bool) -> None:
        state = _state([_error("not configured", retriable=False)])
        result = check_tool_results(state, use_cache=use_cache)
        assert _summary(result) == _expected(_GIVE_UP, use_cache, retries=3, rounds=1)

    def test_one_retriable_error_keeps_retrying(self, use_cache: bool) -> None:
        errors = [_error("permanent", retriable=False, call_id="1"), _error("flaky", call_id="2")]
        result = check_tool_results(_state(errors), use_cache=use_cache)
        retry = _RETRY.format(errors="flaky; permanent")
        assert _summary(result) == _expected(retry, use_cache, retries=1, rounds=1)


def test_disabled_cap_and_nudge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 0)
    monkeypatch.setattr(Config, "AGENT_TOOL_ROUNDS_SOFT_NUDGE", 0)
    result = check_tool_results(_state([_ok()], rounds=40))
    assert result == {"tool_retries": 0, "tool_rounds": 41}
