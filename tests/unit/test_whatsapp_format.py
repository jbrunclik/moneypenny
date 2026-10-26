"""Formatting an agent message for a WhatsApp template (src/agent/tools/whatsapp_format.py)."""

from unittest.mock import patch

from src.agent.tools.whatsapp_format import (
    format_agent_message,
    markdown_to_whatsapp,
    truncate_message,
)


class TestTruncateMessage:
    """Tests for truncate_message helper function."""

    def test_returns_short_message_unchanged(self) -> None:
        """Should return messages under max length unchanged."""
        message = "Hello world"
        result = truncate_message(message, 100)
        assert result == message

    def test_truncates_long_message(self) -> None:
        """Should truncate messages over max length."""
        message = "a" * 100
        result = truncate_message(message, 50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_truncates_at_word_boundary(self) -> None:
        """Should prefer truncating at word boundaries."""
        message = "Hello world this is a test message for truncation"
        result = truncate_message(message, 30)
        # Should truncate at a space, not in the middle of a word
        assert result.endswith("...")
        # The text before ... should end with a complete word
        text_part = result[:-3]
        assert not text_part.endswith(" ")  # No trailing space before ...

    def test_handles_exact_max_length(self) -> None:
        """Should return message if exactly at max length."""
        message = "a" * 50
        result = truncate_message(message, 50)
        assert result == message

    def test_handles_custom_suffix(self) -> None:
        """Should use custom suffix when provided."""
        message = "a" * 100
        result = truncate_message(message, 50, suffix=" [truncated]")
        assert result.endswith(" [truncated]")
        assert len(result) == 50


class TestMarkdownToWhatsApp:
    """Tests for markdown_to_whatsapp helper function."""

    def test_plain_text_unchanged(self) -> None:
        """Should return plain text unchanged."""
        text = "Hello world"
        assert markdown_to_whatsapp(text) == "Hello world"

    def test_converts_markdown_bold_to_whatsapp_bold(self) -> None:
        """Should convert **bold** to *bold*."""
        text = "This is **bold** text"
        assert markdown_to_whatsapp(text) == "This is *bold* text"

    def test_converts_headers_to_bold(self) -> None:
        """Should convert # headers to *bold*."""
        text = "# Main Title\n## Subtitle\nContent"
        result = markdown_to_whatsapp(text)
        assert "*Main Title*" in result
        assert "*Subtitle*" in result
        assert "Content" in result

    def test_converts_links_to_text_and_url(self) -> None:
        """Should convert [text](url) to text (url)."""
        text = "Check out [Google](https://google.com) for more"
        assert markdown_to_whatsapp(text) == "Check out Google (https://google.com) for more"

    def test_removes_inline_code_backticks(self) -> None:
        """Should remove backticks from inline code."""
        text = "Use the `print()` function"
        assert markdown_to_whatsapp(text) == "Use the print() function"

    def test_removes_code_block_language_specifier(self) -> None:
        """Should remove language specifier from code blocks."""
        text = "```python\nprint('hello')\n```"
        result = markdown_to_whatsapp(text)
        assert "python" not in result
        assert "```" in result  # Triple backticks preserved for WhatsApp monospace
        assert "print('hello')" in result

    def test_converts_images_to_alt_text(self) -> None:
        """Should convert image syntax to [Image: alt]."""
        text = "Here is an image: ![A cat](https://example.com/cat.jpg)"
        assert markdown_to_whatsapp(text) == "Here is an image: [Image: A cat]"

    def test_converts_horizontal_rule(self) -> None:
        """Should convert --- to unicode line."""
        text = "Before\n---\nAfter"
        result = markdown_to_whatsapp(text)
        assert "───" in result

    def test_cleans_up_excessive_newlines(self) -> None:
        """Should reduce more than 2 consecutive newlines to 2."""
        text = "First\n\n\n\n\nSecond"
        assert markdown_to_whatsapp(text) == "First\n\nSecond"

    def test_complex_markdown_document(self) -> None:
        """Should handle a complex markdown document."""
        text = """# Summary

Here are the **key points**:

- First item with a [link](https://example.com)
- Second item with `code`

---

Check the image: ![chart](https://example.com/chart.png)
"""
        result = markdown_to_whatsapp(text)
        assert "*Summary*" in result  # Header converted
        assert "*key points*" in result  # Bold converted
        assert "link (https://example.com)" in result  # Link converted
        assert "code" in result  # Backticks removed
        assert "`" not in result  # No remaining backticks
        assert "───" in result  # HR converted
        assert "[Image: chart]" in result  # Image converted


class TestFormatAgentMessage:
    """Tests for format_agent_message helper function."""

    def test_formats_simple_message(self) -> None:
        """Should return message content unchanged when no URL."""
        result, was_truncated = format_agent_message("Hello from agent")
        assert result == "Hello from agent"
        assert was_truncated is False

    def test_appends_conversation_url(self) -> None:
        """Should append conversation URL when provided."""
        result, was_truncated = format_agent_message("Hello", "#/conversations/abc123")
        assert "Hello" in result
        assert "#/conversations/abc123" in result
        assert "View:" in result
        assert was_truncated is False

    def test_truncates_long_message_but_preserves_url(self) -> None:
        """Should truncate content but preserve the conversation URL."""
        long_content = "a" * 5000
        conversation_url = "#/conversations/abc123"
        with patch("src.agent.tools.whatsapp_format.Config") as mock_config:
            mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 150
            result, was_truncated = format_agent_message(long_content, conversation_url)

        # URL must be preserved at the end
        assert result.endswith(conversation_url)
        assert "View:" in result
        # Content should be truncated
        assert "..." in result
        # Total length should be within limit
        assert len(result) <= 150
        # Truncation flag should be True
        assert was_truncated is True
