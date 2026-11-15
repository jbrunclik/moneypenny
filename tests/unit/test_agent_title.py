"""Unit tests for generate_title in src/agent/title.py."""

from src.agent import gemini_clients


class TestGenerateTitle:
    """Tests for the conversation title generation contract.

    The contract: generate_title must NEVER raise. Any exception from the
    underlying LLM must be swallowed and surfaced as a None return so the
    caller leaves the default title in place for opportunistic retry on the
    next user message.
    """

    def test_returns_none_when_llm_raises_provider_error(self, monkeypatch) -> None:
        """ChatGoogleGenerativeAIError on rate-limit must not escape."""
        from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

        from src.agent import title as title_mod

        class _RaisingModel:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def invoke(self, *args, **kwargs):
                raise ChatGoogleGenerativeAIError(
                    "Error calling model 'gemini-3-flash-preview' (RESOURCE_EXHAUSTED): 429"
                )

        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", _RaisingModel)
        assert title_mod.generate_title("hello", "world") is None

    def test_returns_none_on_unexpected_exception(self, monkeypatch) -> None:
        """Any Exception subclass must be caught — not just GoogleAPIError."""
        from src.agent import title as title_mod

        class _RaisingModel:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def invoke(self, *args, **kwargs):
                raise RuntimeError("network blew up")

        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", _RaisingModel)
        assert title_mod.generate_title("hi", "there") is None

    def test_returns_title_on_success(self, monkeypatch) -> None:
        """Happy path: cleaned-up title returned to caller."""
        from src.agent import title as title_mod

        class _Resp:
            content = '"🐍 Python List Sorting"'

        class _StubModel:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def invoke(self, *args, **kwargs):
                return _Resp()

        monkeypatch.setattr(gemini_clients, "ChatGoogleGenerativeAI", _StubModel)
        assert title_mod.generate_title("how do I sort?", "use sorted()") == (
            "🐍 Python List Sorting"
        )


class TestTitleSpeed:
    """A new chat's `done` waits for its title: Flash-Lite, a short limit,
    no retries (docs/superpowers/specs/2026-11-15-title-speed-and-silence-design.md)."""

    def test_the_title_model_is_quick_and_not_retried(self, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from src.agent import title as title_mod
        from src.config import Config

        factory = MagicMock()
        factory.return_value.invoke.return_value.content = "🚲 Servis kola"
        monkeypatch.setattr(title_mod, "chat_model", factory)

        assert title_mod.generate_title("servis", "odpověď") == "🚲 Servis kola"
        assert Config.TITLE_GENERATION_MODEL == "gemini-3.5-flash-lite"
        factory.assert_called_once_with(
            Config.TITLE_GENERATION_MODEL,
            temperature=Config.TITLE_GENERATION_TEMPERATURE,
            timeout=Config.TITLE_GENERATION_TIMEOUT_SECONDS,
            max_retries=0,
        )
        assert Config.TITLE_GENERATION_TIMEOUT_SECONDS == 10

    def test_each_call_logs_its_time_and_outcome(self, monkeypatch) -> None:
        from unittest.mock import MagicMock, patch

        from src.agent import title as title_mod

        factory = MagicMock()
        factory.return_value.invoke.side_effect = [
            MagicMock(content="🚲 Servis kola"),
            TimeoutError("read timed out"),
        ]
        monkeypatch.setattr(title_mod, "chat_model", factory)

        with patch.object(title_mod.logger, "info") as info:
            title_mod.generate_title("a", "b")
            assert title_mod.generate_title("a", "b") is None

        lines = [
            c.kwargs["extra"]
            for c in info.call_args_list
            if c.args[0] == "Conversation title generated"
        ]
        assert [line["ok"] for line in lines] == [True, False]
        assert all(isinstance(line["elapsed_ms"], int) for line in lines)
