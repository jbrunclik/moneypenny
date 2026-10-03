"""A model that is down (503 UNAVAILABLE) fails fast and the turn falls back
to the other MODELS tier (Aug 27 2026: Flash 503'd for minutes while Pro was
up; stacked SDK + with_retry retries kept turns on "Thinking" ~3 min/call)."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import graph
from src.agent.graph import chat_node, other_model_tier
from src.agent.retry import is_model_unavailable, with_retry
from src.agent.turn_usage import batch_usage_info
from src.config import Config

# Exactly as logged in prod on Aug 27 2026
_PROD_503 = (
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
    "experiencing high demand. Spikes in demand are usually temporary. Please try "
    "again later.', 'status': 'UNAVAILABLE'}}"
)


class TestDetection:
    def test_the_logged_prod_error_is_model_unavailable(self) -> None:
        assert is_model_unavailable(RuntimeError(_PROD_503))

    def test_a_wrapped_503_is_found_in_the_cause_chain(self) -> None:
        try:
            try:
                raise RuntimeError(_PROD_503)
            except RuntimeError as inner:
                raise ValueError("ChatGoogleGenerativeAIError: invoke failed") from inner
        except ValueError as outer:
            assert is_model_unavailable(outer)

    @pytest.mark.parametrize(
        "message", ["429 RESOURCE_EXHAUSTED. quota", "timeout", "500 INTERNAL error"]
    )
    def test_other_errors_are_not(self, message: str) -> None:
        assert not is_model_unavailable(RuntimeError(message))

    def test_with_retry_does_not_retry_a_model_that_is_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        calls = MagicMock(side_effect=RuntimeError(_PROD_503))

        with pytest.raises(RuntimeError):
            with_retry(calls, max_retries=3)()

        assert calls.call_count == 1


class TestOtherTier:
    def test_each_model_falls_back_to_the_other_one(self) -> None:
        fast, advanced = list(Config.MODELS)
        assert other_model_tier(fast) == advanced
        assert other_model_tier(advanced) == fast

    def test_unknown_model_has_no_fallback(self) -> None:
        assert other_model_tier("some-other-model") is None


def _state() -> Any:
    return {"messages": [HumanMessage(content="hi")], "tool_retries": 0, "tool_rounds": 0}


class TestChatNodeFallback:
    def test_falls_back_and_marks_the_reply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph, "get_stream_writer", lambda: MagicMock())
        primary = MagicMock(model_name="gemini-fast")
        primary.invoke.side_effect = RuntimeError(_PROD_503)
        backup = MagicMock(model_name="gemini-pro")
        backup.invoke.return_value = AIMessage(content="answer")

        out = chat_node(_state(), primary, fallback=lambda: ("gemini-pro", backup))

        assert out["messages"][0].content == "answer"
        assert out["messages"][0].response_metadata["model_fallback"] == "gemini-pro"
        assert out["model_fallback"] == "gemini-pro"
        assert primary.invoke.call_count == 1

    def test_later_rounds_of_the_turn_stay_on_the_fallback(self) -> None:
        primary = MagicMock(model_name="gemini-fast")
        backup = MagicMock(model_name="gemini-pro")
        backup.invoke.return_value = AIMessage(content="again")
        state = {**_state(), "model_fallback": "gemini-pro"}

        out = chat_node(state, primary, fallback=lambda: ("gemini-pro", backup))

        primary.invoke.assert_not_called()
        assert out["messages"][0].response_metadata["model_fallback"] == "gemini-pro"

    def test_without_a_fallback_the_error_surfaces(self) -> None:
        primary = MagicMock(model_name="gemini-fast")
        primary.invoke.side_effect = RuntimeError(_PROD_503)

        with pytest.raises(RuntimeError):
            chat_node(_state(), primary, fallback=None)


def test_chat_model_sdk_retries_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_cls = MagicMock()
    monkeypatch.setattr(graph, "ChatGoogleGenerativeAI", llm_cls)

    graph.create_chat_model("gemini-fast", with_tools=False)

    assert llm_cls.call_args.kwargs["max_retries"] == Config.AGENT_MODEL_SDK_MAX_RETRIES


def test_usage_names_the_fallback_model() -> None:
    reply = AIMessage(content="x", response_metadata={"model_fallback": "gemini-pro"})
    reply.usage_metadata = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}

    assert batch_usage_info([reply], 10)["model_fallback"] == "gemini-pro"
    assert "model_fallback" not in batch_usage_info([AIMessage(content="y")], 10)


def test_stream_forwards_the_fallback_note() -> None:
    from src.agent.stream_events import StreamEventProcessor

    processor = StreamEventProcessor([])
    events = list(
        processor.process("custom", {"type": "model_fallback", "from": "a", "to": "gemini-pro"})
    )

    assert events == [{"type": "model_fallback", "to": "gemini-pro"}]


def test_cost_is_priced_at_the_model_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.helpers import chat_save

    priced = MagicMock()
    monkeypatch.setattr(chat_save, "calculate_and_save_message_cost", priced)
    monkeypatch.setattr(
        chat_save, "_persist_assistant_message", MagicMock(return_value=MagicMock(id="m1"))
    )
    monkeypatch.setattr(chat_save, "_resolve_title_update", MagicMock(return_value=None))
    monkeypatch.setattr(chat_save, "_collect_generated_files", MagicMock(return_value=([], [])))

    chat_save.save_message_to_db(
        "answer",
        [],
        [],
        {"model_fallback": "gemini-pro"},
        "c1",
        "u1",
        "gemini-fast",
        "q",
        "r1",
        True,
    )

    assert priced.call_args.args[3] == "gemini-pro"
