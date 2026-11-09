"""Turn budgets' loop detector: an identical failing call is blocked after
it failed twice, A-B-A-B rounds get one warning, and a large byte-identical
repeat result becomes a back-reference."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.tool_loops import (
    BACK_REFERENCE,
    blocked_calls,
    call_signature,
    dedupe_results,
    is_ab_cycle,
    loop_state,
)
from src.agent.tool_round_check import check_tool_results
from src.agent.turn_budget import budget_stop, initial_state
from src.config import Config


@pytest.fixture(autouse=True)
def budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "TURN_BUDGETS_ENABLED", True)
    monkeypatch.setattr(Config, "TURN_LOOP_BLOCK_AFTER", 2)
    monkeypatch.setattr(Config, "TURN_DUPLICATE_RESULT_MIN_CHARS", 2000)
    monkeypatch.setattr("src.agent.tool_round_check.get_conversation_context", lambda: (None, None))


def _call(name: str = "web_search", cid: str = "c1", **args: Any) -> dict[str, Any]:
    return {"name": name, "args": args or {"query": "x"}, "id": cid}


def _round(calls: list[dict[str, Any]], results: list[ToolMessage], **extra: Any) -> Any:
    return {
        **initial_state(
            [HumanMessage(content="go"), AIMessage(content="", tool_calls=calls), *results]
        ),
        **extra,
    }


def _failed(cid: str = "c1", name: str = "web_search") -> ToolMessage:
    return ToolMessage(content='{"error": "no results"}', tool_call_id=cid, name=name)


def _ok(cid: str = "c1", name: str = "web_search", content: str = "found") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=cid, name=name)


def test_signature_ignores_arg_order() -> None:
    assert call_signature("t", {"a": 1, "b": 2}) == call_signature("t", {"b": 2, "a": 1})
    assert call_signature("t", {"a": 1}) != call_signature("u", {"a": 1})


def test_third_identical_failure_is_blocked() -> None:
    sig = call_signature("web_search", {"query": "x"})
    assert blocked_calls({sig: 1}, [_call()]) == set()
    assert blocked_calls({sig: 2}, [_call()]) == {"c1"}


def test_failures_are_counted_per_signature() -> None:
    state = _round([_call()], [_failed()])
    first, _ = loop_state(state)
    second, _ = loop_state({**state, **first})
    sig = call_signature("web_search", {"query": "x"})
    assert (first["failed_calls"][sig], second["failed_calls"][sig]) == (1, 2)


def test_a_successful_write_resets_the_count() -> None:
    sig = call_signature("web_search", {"query": "x"})
    state = _round(
        [_call("todoist", "w1", operation="add_task", content="Buy milk")],
        [_ok("w1", "todoist")],
        failed_calls={sig: 2},
    )
    loops, _ = loop_state(state)
    assert loops["failed_calls"] == {}


def test_ab_cycle_warns_once() -> None:
    a, b = "A", "B"
    assert is_ab_cycle([a, b, a, b])
    assert not is_ab_cycle([a, a, a, a])
    assert not is_ab_cycle([a, b, a])
    state = _round([_call(cid="c2", query="b")], [_ok("c2")])
    sig_a = call_signature("web_search", {"query": "a"})
    sig_b = call_signature("web_search", {"query": "b"})
    out = check_tool_results({**state, "recent_rounds": [sig_a, sig_b, sig_a]})
    assert "alternating" in str(out["messages"][-1].content)
    again = check_tool_results({**state, "recent_rounds": [sig_a, sig_b, sig_a], "ab_warned": True})
    assert "messages" not in again or "alternating" not in str(again["messages"][-1].content)


def test_identical_large_result_becomes_a_back_reference() -> None:
    big = "x" * 2500
    calls = [_call()]
    seen: dict[str, str] = {}
    first, seen = dedupe_results([_ok(content=big)], calls, seen)
    second, seen = dedupe_results([_ok(content=big)], calls, seen)
    assert first[0].content == big
    assert second[0].content == BACK_REFERENCE


def test_small_identical_result_is_kept() -> None:
    calls = [_call()]
    _first, seen = dedupe_results([_ok(content="tiny")], calls, {})
    second, _ = dedupe_results([_ok(content="tiny")], calls, seen)
    assert second[0].content == "tiny"


def test_loop_stop_after_repeated_blocks() -> None:
    sig = call_signature("web_search", {"query": "x"})
    assert budget_stop({**initial_state([]), "failed_calls": {sig: 3}}, 1) is None
    assert budget_stop({**initial_state([]), "failed_calls": {sig: 4}}, 1) == "loop"


def test_budgets_off_no_loop_state() -> None:
    Config.TURN_BUDGETS_ENABLED = False  # restored by the fixture's monkeypatch
    out = check_tool_results(_round([_call()], [_failed()]))
    assert "failed_calls" not in out


def test_the_tool_node_answers_a_blocked_call_without_running_it() -> None:
    from src.agent.tool_node import split_looping_calls

    sig = call_signature("web_search", {"query": "x"})
    calls = [_call(), _call(cid="c2", query="other")]
    state = {
        **initial_state([HumanMessage(content="go"), AIMessage(content="", tool_calls=calls)]),
        "failed_calls": {sig: 2},
    }

    blocked, exec_state = split_looping_calls(state)

    assert [m.tool_call_id for m in blocked] == ["c1"]
    assert "already failed twice" in str(blocked[0].content)
    assert exec_state is not None
    assert [c["id"] for c in exec_state["messages"][-1].tool_calls] == ["c2"]
