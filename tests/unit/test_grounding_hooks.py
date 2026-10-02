"""ChatAgent applies the grounding check in both the batch and stream paths."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.agent import grounding_check
from src.agent.grounding_check import GroundingResult, apply_grounding
from src.config import Config

_USAGE = {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}
_ANSWER = "Buy it at VeloRama, it is a good shop."


@pytest.fixture
def flag(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(
        return_value=GroundingResult(
            items=["VeloRama"],
            kinds=["shop"],
            false_claims=["it is a good shop."],
            usage=_USAGE,
        )
    )
    monkeypatch.setattr(grounding_check, "find_unverified", fake)
    return fake


class TestApplyGrounding:
    def test_marks_in_place_and_records_usage(self, flag: MagicMock) -> None:
        usage_info: dict[str, Any] = {"input_tokens": 1}

        text = apply_grounding(_ANSWER, [], usage_info)

        assert text == "Buy it at VeloRama _(unverified)_, it is a good shop. _(unverified)_"
        assert usage_info["grounding_usage"] == _USAGE

    def test_nothing_flagged_leaves_text_and_usage(self, flag: MagicMock) -> None:
        flag.return_value = GroundingResult()
        usage_info: dict[str, Any] = {}

        assert apply_grounding("All supported.", [], usage_info) == "All supported."
        assert "grounding_usage" not in usage_info

    def test_passes_stop_reason_through(self, flag: MagicMock) -> None:
        apply_grounding("x", [], {}, stop_reason="user")

        assert flag.call_args.args[2] == "user"


class TestAgentHooks:
    @staticmethod
    def _agent() -> Any:
        from src.agent.agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent.model_name = "gemini-test"
        agent.graph = MagicMock()
        agent._build_messages = MagicMock(return_value=[])  # type: ignore[method-assign]
        return agent

    def test_batch_answer_carries_the_markers(self, flag: MagicMock) -> None:
        agent = self._agent()
        agent.graph.invoke.return_value = {
            "messages": [
                ToolMessage(content="Bike Prague", tool_call_id="1", name="research"),
                AIMessage(content=_ANSWER),
            ]
        }

        response, _tools, usage_info, _msgs = agent.chat_batch(text="where?")

        assert response.startswith("Buy it at VeloRama _(unverified)_,")
        assert usage_info["grounding_usage"] == _USAGE

    def test_stream_final_carries_the_markers(self, flag: MagicMock) -> None:
        agent = self._agent()
        events = [
            (
                ToolMessage(content="Bike Prague", tool_call_id="1", name="research"),
                {"langgraph_node": "tools"},
            ),
            (AIMessageChunk(content=_ANSWER), {"langgraph_node": "chat"}),
        ]
        agent.graph.stream.return_value = iter(("messages", e) for e in events)

        final = [e for e in agent.stream_chat_events(text="where?") if e["type"] == "final"][0]

        assert final["content"].startswith("Buy it at VeloRama _(unverified)_,")
        assert final["usage_info"]["grounding_usage"] == _USAGE
