"""Transient-error retries are surfaced to the stream as `retry` events.

A Gemini 503/429 blip used to be a silent multi-second stall that looked like a
hang (up to ~70 s of backoff per model call). The chat node now writes a
status through LangGraph's custom stream, and the streaming layer forwards it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from src.agent import graph


class TestRetryStatus:
    def test_emits_attempt_through_the_stream_writer(self) -> None:
        writer = MagicMock()
        with patch.object(graph, "get_stream_writer", return_value=writer):
            graph._emit_retry_status(RuntimeError("503"), 0)

        writer.assert_called_once()
        payload = writer.call_args.args[0]
        assert payload["type"] == "retry"
        assert payload["attempt"] == 1

    def test_no_stream_context_is_harmless(self) -> None:
        """Outside a graph run (batch paths, tests) there is no writer."""
        with patch.object(graph, "get_stream_writer", side_effect=RuntimeError("no context")):
            graph._emit_retry_status(RuntimeError("503"), 1)  # must not raise


class TestStreamForwarding:
    def _run(self, events: list[Any]) -> list[dict[str, Any]]:
        from src.agent.agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent.graph = MagicMock()
        agent.graph.stream.return_value = iter(events)
        agent._build_messages = MagicMock(return_value=[])  # type: ignore[method-assign]
        return list(agent.stream_chat_events(text="hi"))

    def test_custom_retry_event_is_yielded(self) -> None:
        yielded = self._run([("custom", {"type": "retry", "attempt": 2, "max_retries": 3})])
        assert {"type": "retry", "attempt": 2, "max_retries": 3} in yielded

    def test_unknown_custom_payloads_are_ignored(self) -> None:
        yielded = self._run([("custom", {"type": "something-else"}), ("custom", "junk")])
        assert all(e.get("type") != "something-else" for e in yielded)


class TestRealGraph:
    def test_status_crosses_a_real_compiled_graph(self) -> None:
        """Framework boundary: the writer must work inside a real LangGraph node
        and arrive as a ("custom", payload) pair with the stream modes the
        agent uses - a mocked node would not prove that."""
        from typing import TypedDict

        from langgraph.graph import END, StateGraph

        class State(TypedDict):
            n: int

        def node(state: State) -> State:
            graph._emit_retry_status(RuntimeError("503"), 0)
            return {"n": state["n"] + 1}

        builder = StateGraph(State)
        builder.add_node("chat", node)
        builder.set_entry_point("chat")
        builder.add_edge("chat", END)
        compiled = builder.compile()

        events = list(compiled.stream({"n": 0}, stream_mode=["messages", "custom"]))

        assert (
            "custom",
            {"type": "retry", "attempt": 1, "max_retries": graph.Config.AGENT_MAX_RETRIES},
        ) in events
