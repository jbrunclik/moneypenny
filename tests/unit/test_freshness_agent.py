"""The freshness gate inside a turn: research runs before the chat model, the
client sees it like any tool, and the gate's call is priced with the turn."""

from typing import Any
from unittest.mock import MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.agent import freshness
from src.agent.agent import ChatAgent

_USAGE = {
    "model": "gemini-3.5-flash-lite",
    "input_tokens": 300,
    "output_tokens": 20,
    "cached_input_tokens": 0,
}
_BUILT = [SystemMessage(content="system"), HumanMessage(content="Jaký externí modely maj?")]
_PREFETCHED = [
    AIMessage(content="", tool_calls=[{"name": "research", "args": {"question": "q"}, "id": "f1"}]),
    ToolMessage(content='{"sources": []}', tool_call_id="f1", name="research"),
]


def _agent(gate: bool = True) -> ChatAgent:
    agent = ChatAgent.__new__(ChatAgent)
    agent.graph = MagicMock()
    agent.light_graph = MagicMock()
    agent.deep_graph = MagicMock()
    agent.freshness_gate = gate
    agent.model_name = "gemini-4-hydrogen"
    agent._build_messages = MagicMock(return_value=list(_BUILT))  # type: ignore[method-assign]
    return agent


def _decision(lookup: bool, thinking: str | None = None) -> freshness.FreshnessDecision:
    return freshness.FreshnessDecision(
        lookup=lookup,
        queries=["Apple září 2026"] if lookup else [],
        usage=_USAGE,
        thinking=thinking,
    )


def _patched(lookup: bool, thinking: str | None = None) -> Any:
    return (
        patch.object(freshness, "decide_freshness", return_value=_decision(lookup, thinking)),
        patch.object(freshness, "prefetch_messages", return_value=list(_PREFETCHED)),
        patch("src.agent.agent.grounding_check.should_check", return_value=False),
        patch("src.agent.agent.grounding_check.apply_grounding"),
    )


class TestStream:
    def test_research_is_announced_and_runs_before_the_answer(self) -> None:
        agent = _agent()
        agent.graph.stream.return_value = iter(
            [("messages", (AIMessageChunk(content="Answer"), {"langgraph_node": "chat"}))]
        )
        decide, prefetch, should, apply = _patched(lookup=True)
        with decide, prefetch as prefetched, should, apply:
            events = list(agent.stream_chat_events(text="Jaký externí modely maj?"))

        types = [e["type"] for e in events]
        assert types.index("tool_start") < types.index("tool_end") < types.index("token")
        start = next(e for e in events if e["type"] == "tool_start")
        assert start["tool"] == "research" and "metadata" in start
        prefetched.assert_called_once()
        sent = agent.graph.stream.call_args.args[0]["messages"]
        assert sent[-2:] == _PREFETCHED
        final = events[-1]
        assert final["usage_info"]["freshness_usage"] == _USAGE
        assert any(
            isinstance(m, ToolMessage) and m.name == "research" for m in final["result_messages"]
        )

    def test_no_lookup_means_no_tool_events_but_the_gate_is_priced(self) -> None:
        agent = _agent()
        agent.graph.stream.return_value = iter(
            [("messages", (AIMessageChunk(content="Ahoj"), {"langgraph_node": "chat"}))]
        )
        decide, prefetch, should, apply = _patched(lookup=False)
        with decide, prefetch as prefetched, should, apply:
            events = list(agent.stream_chat_events(text="Díky"))
        assert "tool_start" not in [e["type"] for e in events]
        prefetched.assert_not_called()
        assert events[-1]["usage_info"]["freshness_usage"] == _USAGE

    def test_gate_off_makes_no_decision(self) -> None:
        agent = _agent(gate=False)
        agent.graph.stream.return_value = iter([])
        decide, prefetch, should, apply = _patched(lookup=True)
        with decide as decided, prefetch, should, apply:
            list(agent.stream_chat_events(text="hi"))
        decided.assert_not_called()


class TestBatch:
    def test_the_graph_starts_from_the_prefetched_research(self) -> None:
        agent = _agent()
        agent.graph.invoke.return_value = {
            "messages": [*_BUILT, *_PREFETCHED, AIMessage(content="Answer")]
        }
        decide, prefetch, should, apply = _patched(lookup=True)
        with decide, prefetch, should, apply:
            text, _tools, usage, _messages = agent.chat_batch(text="Jaký externí modely maj?")
        assert agent.graph.invoke.call_args.args[0]["messages"][-2:] == _PREFETCHED
        assert text == "Answer"
        assert usage["freshness_usage"] == _USAGE


class TestThinkingLevel:
    """low runs the light graph, high the deep one; medium, or a failed gate
    (thinking None), runs the model's own default (medium on Hydrogen)."""

    def _stream(self, agent: ChatAgent, thinking: str | None) -> None:
        for graph in (agent.graph, agent.light_graph, agent.deep_graph):
            if graph is None:
                continue
            graph.stream.return_value = iter(
                [("messages", (AIMessageChunk(content="Ahoj"), {"langgraph_node": "chat"}))]
            )
        decide, prefetch, should, apply = _patched(lookup=False, thinking=thinking)
        with decide, prefetch, should, apply:
            list(agent.stream_chat_events(text="Díky"))

    def _ran(self, agent: ChatAgent) -> list[str]:
        graphs = {"default": agent.graph, "light": agent.light_graph, "deep": agent.deep_graph}
        return [name for name, graph in graphs.items() if graph is not None and graph.stream.called]

    def test_a_low_turn_runs_light(self) -> None:
        agent = _agent()
        self._stream(agent, thinking="low")
        assert self._ran(agent) == ["light"]

    def test_a_medium_turn_runs_the_model_default(self) -> None:
        agent = _agent()
        self._stream(agent, thinking="medium")
        assert self._ran(agent) == ["default"]

    def test_a_high_turn_runs_deep(self) -> None:
        agent = _agent()
        self._stream(agent, thinking="high")
        assert self._ran(agent) == ["deep"]

    def test_a_failed_gate_runs_the_model_default(self) -> None:
        agent = _agent()
        self._stream(agent, thinking=None)
        assert self._ran(agent) == ["default"]

    def test_missing_graphs_fall_back_to_the_default(self) -> None:
        agent = _agent()
        agent.light_graph = None
        agent.deep_graph = None
        self._stream(agent, thinking="low")
        assert self._ran(agent) == ["default"]

    def test_an_easy_batch_turn_runs_light(self) -> None:
        agent = _agent()
        agent.light_graph.invoke.return_value = {  # type: ignore[union-attr]
            "messages": [*_BUILT, AIMessage(content="Ahoj")]
        }
        decide, prefetch, should, apply = _patched(lookup=False, thinking="low")
        with decide, prefetch, should, apply:
            text, _tools, _usage, _messages = agent.chat_batch(text="Díky")
        assert text == "Ahoj"
        agent.graph.invoke.assert_not_called()


def test_the_turn_usage_carries_the_thinking_level() -> None:
    """For the regular review: the saved-turn log line joins it to the cost row."""
    agent = _agent()
    agent.light_graph.invoke.return_value = {  # type: ignore[union-attr]
        "messages": [*_BUILT, AIMessage(content="Ahoj")]
    }
    decide, prefetch, should, apply = _patched(lookup=False, thinking="low")
    with decide, prefetch, should, apply:
        _text, _tools, usage, _messages = agent.chat_batch(text="Díky")
    assert usage["thinking"] == "low"


def test_the_gate_call_is_part_of_the_message_cost() -> None:
    from src.services.costs import calculate_freshness_cost

    assert calculate_freshness_cost({"freshness_usage": _USAGE}) > 0
    assert calculate_freshness_cost({}) == 0.0
