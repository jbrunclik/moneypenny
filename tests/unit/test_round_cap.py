"""A per-run tool-round cap (deep-research subagents get fewer rounds)."""

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.agent.graph import AgentState, check_tool_results
from src.agent.round_cap import round_cap_override, tool_round_cap
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
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 6)
    with round_cap_override(4):
        assert tool_round_cap() == 4
    assert tool_round_cap() == 6


def test_graph_nudges_at_the_overridden_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 6)
    with round_cap_override(4):
        result = check_tool_results(_state(3))
    assert isinstance(result["messages"][0], SystemMessage)
    assert "stop calling tools" in result["messages"][0].content.lower()
