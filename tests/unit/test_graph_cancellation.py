"""Cancellation checkpoints in the agent graph and the token stream."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage

from src.agent import cancellation
from src.agent.cancellation import TurnCancelled
from src.agent.graph import _handle_tool_errors, chat_node, check_tool_results
from src.agent.tool_results import set_current_request_id


@pytest.fixture
def token():
    set_current_request_id("req-graph")
    token = cancellation.register_token("req-graph")
    yield token
    cancellation.unregister_token("req-graph")
    set_current_request_id(None)


def test_chat_node_raises_before_calling_the_model(token: cancellation.CancelToken) -> None:
    model = MagicMock()
    token.cancel()
    with pytest.raises(TurnCancelled):
        chat_node({"messages": [HumanMessage(content="hi")]}, model)  # type: ignore[typeddict-item]
    model.invoke.assert_not_called()


def test_check_tool_results_raises_when_cancelled(token: cancellation.CancelToken) -> None:
    token.cancel()
    with pytest.raises(TurnCancelled):
        check_tool_results({"messages": [HumanMessage(content="hi")]})  # type: ignore[typeddict-item]


def test_tool_error_handler_reraises_turn_cancelled() -> None:
    with pytest.raises(TurnCancelled):
        _handle_tool_errors(TurnCancelled())


def test_ordinary_tool_errors_still_become_messages() -> None:
    assert "Please fix your mistakes" in _handle_tool_errors(ValueError("bad"))


def _fake_graph_stream(chunks: list[str], on_chunk: Any = None) -> Any:
    def stream(*_args: Any, **_kwargs: Any) -> Any:
        for i, text in enumerate(chunks):
            if on_chunk:
                on_chunk(i)
            yield ("messages", (AIMessageChunk(content=text), {"langgraph_node": "chat"}))

    return stream


def test_stream_stops_at_the_next_chunk_and_keeps_the_partial(
    token: cancellation.CancelToken,
) -> None:
    from src.agent.agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = _fake_graph_stream(
        ["Hello", " world", " never"], on_chunk=lambda i: token.cancel() if i == 2 else None
    )

    events = list(agent.stream_chat_events("hi"))

    final = events[-1]
    assert final["type"] == "final"
    assert final["stop_reason"] == "user"
    assert final["content"] == "Hello world"


def test_uncancelled_final_has_no_stop_reason() -> None:
    from src.agent.agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = _fake_graph_stream(["Hello"])

    final = list(agent.stream_chat_events("hi"))[-1]
    assert "stop_reason" not in final


def test_turn_cancelled_raised_inside_the_graph_ends_the_stream(
    token: cancellation.CancelToken,
) -> None:
    from src.agent.agent import ChatAgent

    def stream(*_args: Any, **_kwargs: Any) -> Any:
        yield ("messages", (AIMessageChunk(content="Partial"), {"langgraph_node": "chat"}))
        raise TurnCancelled

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = stream

    final = list(agent.stream_chat_events("hi"))[-1]
    assert final["stop_reason"] == "user"
    assert final["content"] == "Partial"


def test_delegate_subagent_stop_propagates(token: cancellation.CancelToken) -> None:
    from unittest.mock import patch

    from src.agent.tools.delegate import delegate_task

    def cancelled_batch(*_args: Any, **_kwargs: Any) -> Any:
        token.cancel()
        cancellation.raise_if_cancelled()  # what the subagent's chat_node does

    with (
        patch("src.agent.agent.ChatAgent.chat_batch", cancelled_batch),
        patch("src.agent.tools.delegate.check_autonomous_permission"),
    ):
        with pytest.raises(TurnCancelled):
            delegate_task.invoke({"task": "Compare three laptops"})
