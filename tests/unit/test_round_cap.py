"""A per-run round backstop (deep-research subagents get fewer rounds)."""

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.agent.graph_state import AgentState
from src.agent.round_cap import round_cap_override, tool_round_cap
from src.agent.tool_round_check import check_tool_results
from src.config import Config


def _state(rounds: int) -> AgentState:
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
            ToolMessage(content="ok", tool_call_id="1"),
        ],
        "tool_retries": 0,
        "tool_rounds": rounds,
    }


def test_override_applies_only_inside(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "TURN_MAX_TOOL_ROUNDS", 20)
    with round_cap_override(4):
        assert tool_round_cap() == 4
    assert tool_round_cap() == 20


def test_graph_stops_at_the_overridden_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "TURN_MAX_TOOL_ROUNDS", 20)
    with round_cap_override(4):
        result = check_tool_results(_state(3))
    assert result["final_answer"] == "rounds"
    assert isinstance(result["messages"][0], SystemMessage)
    assert "tools are off" in result["messages"][0].content.lower()
