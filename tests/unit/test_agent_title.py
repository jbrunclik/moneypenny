"""Unit tests for generate_title in src/agent/title.py."""


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

        monkeypatch.setattr(title_mod, "ChatGoogleGenerativeAI", _RaisingModel)
        assert title_mod.generate_title("hello", "world") is None

    def test_returns_none_on_unexpected_exception(self, monkeypatch) -> None:
        """Any Exception subclass must be caught — not just GoogleAPIError."""
        from src.agent import title as title_mod

        class _RaisingModel:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def invoke(self, *args, **kwargs):
                raise RuntimeError("network blew up")

        monkeypatch.setattr(title_mod, "ChatGoogleGenerativeAI", _RaisingModel)
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

        monkeypatch.setattr(title_mod, "ChatGoogleGenerativeAI", _StubModel)
        assert title_mod.generate_title("how do I sort?", "use sorted()") == (
            "🐍 Python List Sorting"
        )
