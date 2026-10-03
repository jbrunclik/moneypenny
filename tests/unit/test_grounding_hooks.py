"""ChatAgent applies the grounding check in both the batch and stream paths."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.agent import grounding_check
from src.agent.grounding_check import GroundingOutcome, apply_grounding
from src.config import Config

_USAGE = {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}
_ANSWER = "Buy it at VeloRama, it is a good shop."


_ANNS = [{"type": "claim", "verdict": "not_found", "quote": "VeloRama", "prefix": "Buy it at "}]
_SUMMARY = {"checked": True, "source_count": 2}


@pytest.fixture
def flag(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(
        return_value=GroundingOutcome(annotations=_ANNS, summary=_SUMMARY, usage=_USAGE)
    )
    monkeypatch.setattr(grounding_check, "check_grounding", fake)
    monkeypatch.setattr(grounding_check, "should_check", MagicMock(return_value=True))
    return fake


class TestApplyGrounding:
    def test_records_annotations_and_usage_without_touching_text(self, flag: MagicMock) -> None:
        usage_info: dict[str, Any] = {"input_tokens": 1}

        assert apply_grounding(_ANSWER, [], usage_info) is None
        assert usage_info["grounding"] == {"annotations": _ANNS, "summary": _SUMMARY}
        assert usage_info["grounding_usage"] == _USAGE

    def test_no_claims_records_nothing(self, flag: MagicMock) -> None:
        flag.return_value = GroundingOutcome(annotations=[], summary=None, usage=None)
        usage_info: dict[str, Any] = {}

        apply_grounding("All supported.", [], usage_info)

        assert usage_info == {}

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

    def test_batch_answer_is_unchanged_and_carries_annotations(self, flag: MagicMock) -> None:
        agent = self._agent()
        agent.graph.invoke.return_value = {
            "messages": [
                ToolMessage(content="Bike Prague", tool_call_id="1", name="research"),
                AIMessage(content=_ANSWER),
            ]
        }

        response, _tools, usage_info, _msgs = agent.chat_batch(text="where?")

        assert response == _ANSWER
        assert usage_info["grounding"]["annotations"] == _ANNS
        assert usage_info["grounding_usage"] == _USAGE

    def test_stream_announces_the_check_and_final_carries_annotations(
        self, flag: MagicMock
    ) -> None:
        agent = self._agent()
        events = [
            (
                ToolMessage(content="Bike Prague", tool_call_id="1", name="research"),
                {"langgraph_node": "tools"},
            ),
            (AIMessageChunk(content=_ANSWER), {"langgraph_node": "chat"}),
        ]
        agent.graph.stream.return_value = iter(("messages", e) for e in events)

        yielded = list(agent.stream_chat_events(text="where?"))
        types = [e["type"] for e in yielded]
        final = yielded[types.index("final")]

        assert types.index("grounding_started") < types.index("final")
        assert final["content"] == _ANSWER
        assert final["usage_info"]["grounding"]["annotations"] == _ANNS
        assert final["usage_info"]["grounding_usage"] == _USAGE
