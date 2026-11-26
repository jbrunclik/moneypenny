"""A model that is down (503 UNAVAILABLE) fails fast and the turn falls back
to the other MODELS tier (Aug 27 2026: Flash 503'd for minutes while Pro was
up; stacked SDK + with_retry retries kept turns on "Thinking" ~3 min/call)."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import chat_model
from src.agent import chat_node as chat_node_module
from src.agent.chat_model import other_model_tier
from src.agent.chat_node import chat_node
from src.agent.retry import is_model_unavailable, is_model_unresponsive, with_retry
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


# Exactly as logged in prod on Nov 26 2026 (Carbon hung for 20+ minutes)
_PROD_504 = (
    "504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': 'Deadline expired "
    "before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}"
)


def _sdk_504() -> Exception:
    """What the SDK raises for it (a plain RuntimeError is not retried at all)."""
    from langchain_google_genai.chat_models import GoogleAPIError

    return GoogleAPIError(code=504, response_json={"error": {"status": "DEADLINE_EXCEEDED"}})


class TestUnresponsive:
    """Nov 26 2026: Carbon answered every call with a 504 or nothing for 180 s;
    three retries per call ran each turn into its 10-minute limit, no reply."""

    def test_the_logged_prod_504_is_unresponsive(self) -> None:
        assert is_model_unresponsive(RuntimeError(_PROD_504))

    def test_the_sdks_504_is_unresponsive(self) -> None:
        from langchain_google_genai.chat_models import GoogleAPIError

        err = GoogleAPIError(code=504, response_json={"error": {"status": "DEADLINE_EXCEEDED"}})
        assert is_model_unresponsive(err)

    def test_a_read_timeout_is_unresponsive(self) -> None:
        import httpx
        import httpx2

        assert is_model_unresponsive(httpx2.ReadTimeout("The read operation timed out"))
        assert is_model_unresponsive(httpx.ReadTimeout("The read operation timed out"))
        assert is_model_unresponsive(TimeoutError("The read operation timed out"))

    def test_a_wrapped_timeout_is_found_in_the_cause_chain(self) -> None:
        import httpx2

        try:
            try:
                raise httpx2.ReadTimeout("The read operation timed out")
            except httpx2.ReadTimeout as inner:
                raise RuntimeError("Error calling model") from inner
        except RuntimeError as outer:
            assert is_model_unresponsive(outer)

    def test_a_503_is_unresponsive_too(self) -> None:
        assert is_model_unresponsive(RuntimeError(_PROD_503))

    @pytest.mark.parametrize(
        "message", ["429 RESOURCE_EXHAUSTED. quota", "500 INTERNAL error", "400 INVALID_ARGUMENT"]
    )
    def test_other_errors_are_not(self, message: str) -> None:
        assert not is_model_unresponsive(RuntimeError(message))

    def test_a_connection_reset_is_not(self) -> None:
        """A dropped connection is retried on the same model, as before."""
        import httpx2

        assert not is_model_unresponsive(httpx2.ConnectError("[Errno 104] reset"))

    def test_a_failure_after_streamed_text_is_not(self) -> None:
        from src.agent.retry import PartialStreamError

        try:
            try:
                raise RuntimeError(_PROD_504)
            except RuntimeError as inner:
                raise PartialStreamError("after text") from inner
        except PartialStreamError as outer:
            assert not is_model_unresponsive(outer)

    def test_with_retry_still_retries_a_504_without_a_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        calls = MagicMock(side_effect=[_sdk_504(), "ok"])

        assert with_retry(calls, max_retries=3)() == "ok"

    def test_with_retry_gives_up_at_once_when_told_to(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        calls = MagicMock(side_effect=RuntimeError(_PROD_504))

        with pytest.raises(RuntimeError):
            with_retry(calls, max_retries=3, give_up=is_model_unresponsive)()

        assert calls.call_count == 1


class TestOtherTier:
    def test_hydrogen_falls_back_to_carbon(self) -> None:
        assert other_model_tier("gemini-4-hydrogen") == "gemini-4-carbon"

    def test_neon_and_carbon_fall_back_to_hydrogen(self) -> None:
        """Neon must not take Hydrogen's outage traffic (unmeasured, admin-only)."""
        assert other_model_tier("gemini-4-neon") == "gemini-4-hydrogen"
        assert other_model_tier("gemini-4-carbon") == "gemini-4-hydrogen"

    def test_every_fallback_is_another_configured_model(self) -> None:
        for name in Config.MODELS:
            fallback = other_model_tier(name)
            assert fallback in Config.MODELS and fallback != name, name

    def test_unknown_model_has_no_fallback(self) -> None:
        assert other_model_tier("some-other-model") is None


def _state() -> Any:
    return {"messages": [HumanMessage(content="hi")], "tool_retries": 0, "tool_rounds": 0}


class TestChatNodeFallback:
    def test_falls_back_and_marks_the_reply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: MagicMock())
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

    @pytest.mark.parametrize("error", [RuntimeError(_PROD_504), TimeoutError("timed out")])
    def test_a_504_or_a_timeout_falls_back_after_one_try(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception
    ) -> None:
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: MagicMock())
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        primary = MagicMock(model_name="gemini-4-carbon")
        primary.invoke.side_effect = error
        backup = MagicMock(model_name="gemini-4-hydrogen")
        backup.invoke.return_value = AIMessage(content="answer")

        out = chat_node(_state(), primary, fallback=lambda: ("gemini-4-hydrogen", backup))

        assert out["model_fallback"] == "gemini-4-hydrogen"
        assert primary.invoke.call_count == 1

    def test_the_fallback_itself_is_still_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: MagicMock())
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        primary = MagicMock(model_name="gemini-4-carbon")
        primary.invoke.side_effect = RuntimeError(_PROD_504)
        backup = MagicMock(model_name="gemini-4-hydrogen")
        backup.invoke.side_effect = [_sdk_504(), AIMessage(content="answer")]

        out = chat_node(_state(), primary, fallback=lambda: ("gemini-4-hydrogen", backup))

        assert out["messages"][0].content == "answer"
        assert backup.invoke.call_count == 2

    def test_without_a_fallback_a_504_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_node_module, "get_stream_writer", lambda: MagicMock())
        monkeypatch.setattr("src.agent.retry.time.sleep", lambda _s: None)
        primary = MagicMock(model_name="gemini-4-carbon")
        primary.invoke.side_effect = [_sdk_504(), AIMessage(content="answer")]

        out = chat_node(_state(), primary, fallback=None)

        assert out["messages"][0].content == "answer"
        assert primary.invoke.call_count == 2

    def test_without_a_fallback_the_error_surfaces(self) -> None:
        primary = MagicMock(model_name="gemini-fast")
        primary.invoke.side_effect = RuntimeError(_PROD_503)

        with pytest.raises(RuntimeError):
            chat_node(_state(), primary, fallback=None)


def test_chat_model_sdk_retries_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_cls = MagicMock()
    monkeypatch.setattr(chat_model, "ChatGoogleGenerativeAI", llm_cls)

    chat_model.create_chat_model("gemini-fast", with_tools=False)

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
    monkeypatch.setattr(chat_save, "resolve_title_update", MagicMock(return_value=None))
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


def test_fallback_model_is_built_once_with_the_same_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fast, advanced = "gemini-4-hydrogen", "gemini-4-carbon"
    built = MagicMock(return_value="backup-model")
    monkeypatch.setattr(chat_model, "create_chat_model", built)
    tools = [MagicMock(name="tool")]

    factory = chat_model.fallback_model_factory(fast, True, False, tools)
    assert factory is not None
    built.assert_not_called()  # built lazily, on the first fallback

    assert factory() == (advanced, "backup-model")
    assert factory() == (advanced, "backup-model")
    built.assert_called_once_with(advanced, with_tools=True, include_thoughts=False, tools=tools)


def test_unknown_model_gets_no_fallback_factory() -> None:
    assert chat_model.fallback_model_factory("some-other-model", True, False, []) is None
