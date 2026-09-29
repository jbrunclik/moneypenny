"""Unit tests for metadata extraction helpers in src/agent/content.py."""

from src.agent.content import (
    detect_response_language,
    extract_conversation_title,
    extract_image_prompts_from_messages,
)


class TestDetectResponseLanguage:
    """Tests for detect_response_language function."""

    def test_detects_english(self) -> None:
        """Should detect English text."""
        result = detect_response_language("Hello, this is a test response in English.")
        assert result == "en"

    def test_detects_czech(self) -> None:
        """Should detect Czech text."""
        result = detect_response_language("Ahoj, toto je testovací odpověď v češtině.")
        assert result == "cs"

    def test_returns_none_for_short_text(self) -> None:
        """Should return None for text shorter than 10 chars."""
        assert detect_response_language("Hi") is None
        assert detect_response_language("") is None

    def test_returns_none_for_empty_text(self) -> None:
        """Should return None for None-like inputs."""
        assert detect_response_language("") is None

    def test_normalizes_to_two_char_code(self) -> None:
        """Should return 2-char ISO 639-1 code."""
        result = detect_response_language(
            "This is a longer English sentence for language detection."
        )
        assert result is not None
        assert len(result) == 2


class TestExtractImagePromptsFromMessages:
    """Tests for extract_image_prompts_from_messages function."""

    def test_extracts_from_generate_image_tool_call(self) -> None:
        """Should extract prompts from generate_image tool calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's the image.",
                tool_calls=[
                    {
                        "name": "generate_image",
                        "args": {"prompt": "a sunset over mountains"},
                        "id": "1",
                    }
                ],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 1
        assert result[0]["prompt"] == "a sunset over mountains"

    def test_ignores_non_image_tool_calls(self) -> None:
        """Should ignore non-generate_image tool calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's what I found.",
                tool_calls=[{"name": "web_search", "args": {"query": "test"}, "id": "1"}],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert result == []

    def test_empty_messages(self) -> None:
        """Should return empty list for no messages."""
        assert extract_image_prompts_from_messages([]) == []

    def test_multiple_images(self) -> None:
        """Should extract prompts from multiple generate_image calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="First image",
                tool_calls=[{"name": "generate_image", "args": {"prompt": "a cat"}, "id": "1"}],
            ),
            AIMessage(
                content="Second image",
                tool_calls=[{"name": "generate_image", "args": {"prompt": "a dog"}, "id": "2"}],
            ),
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 2
        assert result[0]["prompt"] == "a cat"
        assert result[1]["prompt"] == "a dog"


class TestExtractConversationTitle:
    """Tests for extract_conversation_title function."""

    def test_extracts_title_from_tool_call(self) -> None:
        """Should extract the title arg from a set_conversation_title call."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Sure, let's talk about Rust instead.",
                tool_calls=[
                    {
                        "name": "set_conversation_title",
                        "args": {"title": "🦀 Rust Ownership Basics"},
                        "id": "1",
                    }
                ],
            )
        ]
        assert extract_conversation_title(messages) == "🦀 Rust Ownership Basics"

    def test_last_call_wins(self) -> None:
        """A multi-step turn may retitle more than once; the final call wins."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "set_conversation_title", "args": {"title": "🐍 First"}, "id": "1"}
                ],
            ),
            AIMessage(
                content="Done.",
                tool_calls=[
                    {"name": "set_conversation_title", "args": {"title": "🦀 Second"}, "id": "2"}
                ],
            ),
        ]
        assert extract_conversation_title(messages) == "🦀 Second"

    def test_returns_none_when_not_called(self) -> None:
        """Should return None when the tool was never called."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "t"},
                        "id": "1",
                    }
                ],
            )
        ]
        assert extract_conversation_title(messages) is None
        assert extract_conversation_title([]) is None

    def test_strips_whitespace_and_quotes(self) -> None:
        """Should clean up stray quotes/whitespace like generate_title does."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_conversation_title",
                        "args": {"title": '  "📚 Book Recommendations"  '},
                        "id": "1",
                    }
                ],
            )
        ]
        assert extract_conversation_title(messages) == "📚 Book Recommendations"

    def test_empty_or_missing_title_returns_none(self) -> None:
        """A blank title must be ignored rather than wiping the current one."""
        from langchain_core.messages import AIMessage

        def msg(args: dict) -> list:
            return [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "set_conversation_title", "args": args, "id": "1"}],
                )
            ]

        assert extract_conversation_title(msg({"title": "   "})) is None
        assert extract_conversation_title(msg({})) is None

    def test_truncates_overlong_title(self) -> None:
        """Should clamp titles beyond TITLE_MAX_LENGTH like generate_title."""
        from langchain_core.messages import AIMessage

        from src.config import Config

        long_title = "🔥 " + "x" * (Config.TITLE_MAX_LENGTH * 2)
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "set_conversation_title", "args": {"title": long_title}, "id": "1"}
                ],
            )
        ]
        result = extract_conversation_title(messages)
        assert result is not None
        assert result.endswith("...")
        assert len(result) == Config.TITLE_TRUNCATE_LENGTH + 3


class TestMetadataToolEdgeCases:
    """Edge case tests for metadata extraction functions.

    Regression tests for malformed tool calls, missing args, and boundary conditions
    that could cause extraction failures.
    """

    def test_extract_image_prompts_missing_prompt_arg(self) -> None:
        """generate_image without 'prompt' arg should be skipped."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Image",
                tool_calls=[
                    {"name": "generate_image", "args": {}, "id": "1"},
                    {"name": "generate_image", "args": {"prompt": "a cat"}, "id": "2"},
                ],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 1
        assert result[0]["prompt"] == "a cat"

    def test_extract_image_prompts_with_non_ai_messages(self) -> None:
        """Should safely skip non-AIMessage objects."""
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content="Generate a cat")]
        result = extract_image_prompts_from_messages(messages)
        assert result == []

    def test_detect_language_handles_whitespace_only(self) -> None:
        """Language detection should return None for whitespace-only text."""
        assert detect_response_language("   \n\t  ") is None

    def test_detect_language_handles_special_characters(self) -> None:
        """Language detection should handle text with special characters."""
        # Enough chars for detection, but mostly symbols
        result = detect_response_language("!@#$%^&*()_+!@#$%^&*()")
        # Should either detect something or return None, not crash
        assert result is None or (isinstance(result, str) and len(result) == 2)
