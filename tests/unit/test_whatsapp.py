"""Unit tests for src/agent/tools/whatsapp module."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.agent.tools.whatsapp import (
    WhatsAppError,
    _format_agent_message,
    _markdown_to_whatsapp,
    _truncate_message,
    _whatsapp_api_request,
    is_whatsapp_available,
    whatsapp,
)


class TestTruncateMessage:
    """Tests for _truncate_message helper function."""

    def test_returns_short_message_unchanged(self) -> None:
        """Should return messages under max length unchanged."""
        message = "Hello world"
        result = _truncate_message(message, 100)
        assert result == message

    def test_truncates_long_message(self) -> None:
        """Should truncate messages over max length."""
        message = "a" * 100
        result = _truncate_message(message, 50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_truncates_at_word_boundary(self) -> None:
        """Should prefer truncating at word boundaries."""
        message = "Hello world this is a test message for truncation"
        result = _truncate_message(message, 30)
        # Should truncate at a space, not in the middle of a word
        assert result.endswith("...")
        # The text before ... should end with a complete word
        text_part = result[:-3]
        assert not text_part.endswith(" ")  # No trailing space before ...

    def test_handles_exact_max_length(self) -> None:
        """Should return message if exactly at max length."""
        message = "a" * 50
        result = _truncate_message(message, 50)
        assert result == message

    def test_handles_custom_suffix(self) -> None:
        """Should use custom suffix when provided."""
        message = "a" * 100
        result = _truncate_message(message, 50, suffix=" [truncated]")
        assert result.endswith(" [truncated]")
        assert len(result) == 50


class TestMarkdownToWhatsApp:
    """Tests for _markdown_to_whatsapp helper function."""

    def test_plain_text_unchanged(self) -> None:
        """Should return plain text unchanged."""
        text = "Hello world"
        assert _markdown_to_whatsapp(text) == "Hello world"

    def test_converts_markdown_bold_to_whatsapp_bold(self) -> None:
        """Should convert **bold** to *bold*."""
        text = "This is **bold** text"
        assert _markdown_to_whatsapp(text) == "This is *bold* text"

    def test_converts_headers_to_bold(self) -> None:
        """Should convert # headers to *bold*."""
        text = "# Main Title\n## Subtitle\nContent"
        result = _markdown_to_whatsapp(text)
        assert "*Main Title*" in result
        assert "*Subtitle*" in result
        assert "Content" in result

    def test_converts_links_to_text_and_url(self) -> None:
        """Should convert [text](url) to text (url)."""
        text = "Check out [Google](https://google.com) for more"
        assert _markdown_to_whatsapp(text) == "Check out Google (https://google.com) for more"

    def test_removes_inline_code_backticks(self) -> None:
        """Should remove backticks from inline code."""
        text = "Use the `print()` function"
        assert _markdown_to_whatsapp(text) == "Use the print() function"

    def test_removes_code_block_language_specifier(self) -> None:
        """Should remove language specifier from code blocks."""
        text = "```python\nprint('hello')\n```"
        result = _markdown_to_whatsapp(text)
        assert "python" not in result
        assert "```" in result  # Triple backticks preserved for WhatsApp monospace
        assert "print('hello')" in result

    def test_converts_images_to_alt_text(self) -> None:
        """Should convert image syntax to [Image: alt]."""
        text = "Here is an image: ![A cat](https://example.com/cat.jpg)"
        assert _markdown_to_whatsapp(text) == "Here is an image: [Image: A cat]"

    def test_converts_horizontal_rule(self) -> None:
        """Should convert --- to unicode line."""
        text = "Before\n---\nAfter"
        result = _markdown_to_whatsapp(text)
        assert "───" in result

    def test_cleans_up_excessive_newlines(self) -> None:
        """Should reduce more than 2 consecutive newlines to 2."""
        text = "First\n\n\n\n\nSecond"
        assert _markdown_to_whatsapp(text) == "First\n\nSecond"

    def test_complex_markdown_document(self) -> None:
        """Should handle a complex markdown document."""
        text = """# Summary

Here are the **key points**:

- First item with a [link](https://example.com)
- Second item with `code`

---

Check the image: ![chart](https://example.com/chart.png)
"""
        result = _markdown_to_whatsapp(text)
        assert "*Summary*" in result  # Header converted
        assert "*key points*" in result  # Bold converted
        assert "link (https://example.com)" in result  # Link converted
        assert "code" in result  # Backticks removed
        assert "`" not in result  # No remaining backticks
        assert "───" in result  # HR converted
        assert "[Image: chart]" in result  # Image converted


class TestFormatAgentMessage:
    """Tests for _format_agent_message helper function."""

    def test_formats_simple_message(self) -> None:
        """Should return message content unchanged when no URL."""
        result, was_truncated = _format_agent_message("Hello from agent")
        assert result == "Hello from agent"
        assert was_truncated is False

    def test_appends_conversation_url(self) -> None:
        """Should append conversation URL when provided."""
        result, was_truncated = _format_agent_message("Hello", "#/conversations/abc123")
        assert "Hello" in result
        assert "#/conversations/abc123" in result
        assert "View conversation:" in result
        assert was_truncated is False

    def test_truncates_long_message_but_preserves_url(self) -> None:
        """Should truncate content but preserve the conversation URL."""
        long_content = "a" * 5000
        conversation_url = "#/conversations/abc123"
        with patch("src.agent.tools.whatsapp.Config") as mock_config:
            mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 150
            result, was_truncated = _format_agent_message(long_content, conversation_url)

        # URL must be preserved at the end
        assert result.endswith(conversation_url)
        assert "View conversation:" in result
        # Content should be truncated
        assert "..." in result
        # Total length should be within limit
        assert len(result) <= 150
        # Truncation flag should be True
        assert was_truncated is True


class TestWhatsAppApiRequest:
    """Tests for _whatsapp_api_request function."""

    @patch("src.agent.tools.whatsapp.requests.post")
    @patch("src.agent.tools.whatsapp.Config")
    def test_successful_request(self, mock_config: MagicMock, mock_post: MagicMock) -> None:
        """Should return JSON response on success."""
        mock_config.WHATSAPP_API_BASE_URL = "https://graph.facebook.com"
        mock_config.WHATSAPP_API_VERSION = "v18.0"
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "test_token"
        mock_config.WHATSAPP_API_TIMEOUT = 10

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "msg123"}]}
        mock_post.return_value = mock_response

        result = _whatsapp_api_request("/messages", {"test": "data"})

        assert result == {"messages": [{"id": "msg123"}]}
        mock_post.assert_called_once()

    @patch("src.agent.tools.whatsapp.requests.post")
    @patch("src.agent.tools.whatsapp.Config")
    def test_handles_invalid_token_error(
        self, mock_config: MagicMock, mock_post: MagicMock
    ) -> None:
        """Should raise WhatsAppError with helpful message for invalid token."""
        mock_config.WHATSAPP_API_BASE_URL = "https://graph.facebook.com"
        mock_config.WHATSAPP_API_VERSION = "v18.0"
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "invalid_token"
        mock_config.WHATSAPP_API_TIMEOUT = 10

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": {"code": 190, "message": "Invalid OAuth access token"}}'
        mock_response.json.return_value = {
            "error": {"code": 190, "message": "Invalid OAuth access token"}
        }
        mock_post.return_value = mock_response

        with pytest.raises(WhatsAppError) as exc_info:
            _whatsapp_api_request("/messages", {"test": "data"})

        assert "invalid or expired" in str(exc_info.value).lower()

    @patch("src.agent.tools.whatsapp.requests.post")
    @patch("src.agent.tools.whatsapp.Config")
    def test_handles_recipient_not_allowed_error(
        self, mock_config: MagicMock, mock_post: MagicMock
    ) -> None:
        """Should raise WhatsAppError for recipient not in allowed list."""
        mock_config.WHATSAPP_API_BASE_URL = "https://graph.facebook.com"
        mock_config.WHATSAPP_API_VERSION = "v18.0"
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "test_token"
        mock_config.WHATSAPP_API_TIMEOUT = 10

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = (
            '{"error": {"code": 131030, "message": "Recipient not in allowed list"}}'
        )
        mock_response.json.return_value = {
            "error": {"code": 131030, "message": "Recipient not in allowed list"}
        }
        mock_post.return_value = mock_response

        with pytest.raises(WhatsAppError) as exc_info:
            _whatsapp_api_request("/messages", {"test": "data"})

        assert "allowed list" in str(exc_info.value).lower()

    @patch("src.agent.tools.whatsapp.requests.post")
    @patch("src.agent.tools.whatsapp.Config")
    def test_handles_network_error(self, mock_config: MagicMock, mock_post: MagicMock) -> None:
        """Should raise WhatsAppError on network failure."""
        mock_config.WHATSAPP_API_BASE_URL = "https://graph.facebook.com"
        mock_config.WHATSAPP_API_VERSION = "v18.0"
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "test_token"
        mock_config.WHATSAPP_API_TIMEOUT = 10

        mock_post.side_effect = requests.RequestException("Connection failed")

        with pytest.raises(WhatsAppError) as exc_info:
            _whatsapp_api_request("/messages", {"test": "data"})

        assert "Failed to connect" in str(exc_info.value)


class TestWhatsAppTool:
    """Tests for the whatsapp tool function."""

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_error_when_not_configured(self, mock_config: MagicMock) -> None:
        """Should return error JSON when WhatsApp is not configured."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = ""
        mock_config.WHATSAPP_ACCESS_TOKEN = ""

        result = whatsapp.invoke({"message": "Hello"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not configured" in parsed["error"].lower()

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_error_when_template_not_configured(self, mock_config: MagicMock) -> None:
        """Should return error JSON when template name is not configured."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = ""

        result = whatsapp.invoke({"message": "Hello"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "template" in parsed["error"].lower()

    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_error_when_no_user_context(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
    ) -> None:
        """Should return error JSON when no user context available."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_context.return_value = ("conv123", None)  # No user ID

        result = whatsapp.invoke({"message": "Hello"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "user context" in parsed["message"].lower()

    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_error_when_user_has_no_phone(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
    ) -> None:
        """Should return error JSON when user has no WhatsApp phone configured."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = None  # User has no phone

        result = whatsapp.invoke({"message": "Hello"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not configured" in parsed["message"].lower()

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_sends_message_successfully(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        """Should send message and return success response."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 4096
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = "+1234567890"
        mock_send.return_value = {"messages": [{"id": "msg789"}]}

        result = whatsapp.invoke({"message": "Task completed!"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["message_id"] == "msg789"
        mock_permission.assert_called_once_with("whatsapp", {"action": "send_message"})

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_includes_conversation_link_by_default(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        """Should include conversation link in message by default."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 4096
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = "+1234567890"
        mock_send.return_value = {"messages": [{"id": "msg789"}]}

        whatsapp.invoke({"message": "Hello"})

        # Check the message sent includes the conversation link
        call_args = mock_send.call_args
        # Template message: (phone, template_name, agent_name, message)
        sent_message = call_args[0][3]
        assert "#/conversations/conv123" in sent_message

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_excludes_conversation_link_when_disabled(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        """Should not include conversation link when include_conversation_link=False."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 4096
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = "+1234567890"
        mock_send.return_value = {"messages": [{"id": "msg789"}]}

        whatsapp.invoke({"message": "Hello", "include_conversation_link": False})

        # Check the message sent does NOT include the conversation link
        call_args = mock_send.call_args
        # Template message: (phone, template_name, agent_name, message)
        sent_message = call_args[0][3]
        assert "#/conversations/" not in sent_message

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_handles_api_error(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        """Should return error JSON when API call fails."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 4096
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = "+1234567890"
        mock_send.side_effect = WhatsAppError("API rate limit exceeded")

        result = whatsapp.invoke({"message": "Hello"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "rate limit" in parsed["error"].lower()

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_reports_truncation(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send: MagicMock,
    ) -> None:
        """Should report in response when message was truncated."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 100
        mock_context.return_value = (None, "user456")  # No conversation ID
        mock_get_phone.return_value = "+1234567890"
        mock_send.return_value = {"messages": [{"id": "msg789"}]}

        # Send a message longer than the limit
        long_message = "a" * 500
        result = whatsapp.invoke({"message": long_message, "include_conversation_link": False})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["truncated"] is True
        assert parsed["message_length"] == 100

    @patch("src.agent.tools.whatsapp._send_template_message")
    @patch("src.agent.tools.whatsapp._get_user_whatsapp_phone")
    @patch("src.agent.tools.whatsapp.check_autonomous_permission")
    @patch("src.agent.tools.whatsapp.get_conversation_context")
    @patch("src.agent.tools.whatsapp.Config")
    def test_passes_agent_name_to_template(
        self,
        mock_config: MagicMock,
        mock_context: MagicMock,
        mock_permission: MagicMock,
        mock_get_phone: MagicMock,
        mock_send_template: MagicMock,
    ) -> None:
        """Should pass agent name to template message."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"
        mock_config.WHATSAPP_MAX_MESSAGE_LENGTH = 4096
        mock_context.return_value = ("conv123", "user456")
        mock_get_phone.return_value = "+1234567890"
        mock_send_template.return_value = {"messages": [{"id": "msg789"}]}

        result = whatsapp.invoke({"message": "Task completed!"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["message_id"] == "msg789"
        mock_send_template.assert_called_once()
        # Verify template name and agent name were passed
        call_args = mock_send_template.call_args
        assert call_args[0][1] == "agent_notification"  # template name
        assert call_args[0][2] == "AI Chatbot"  # default agent name


class TestIsWhatsAppAvailable:
    """Tests for is_whatsapp_available function.

    Note: is_whatsapp_available checks app-level config (API credentials + template).
    User phone numbers are stored per-user in the database.
    """

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_true_when_configured(self, mock_config: MagicMock) -> None:
        """Should return True when API credentials and template are configured."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"

        assert is_whatsapp_available() is True

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_false_when_phone_id_missing(self, mock_config: MagicMock) -> None:
        """Should return False when phone number ID is not set."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = ""
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"

        assert is_whatsapp_available() is False

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_false_when_token_missing(self, mock_config: MagicMock) -> None:
        """Should return False when access token is not set."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = ""
        mock_config.WHATSAPP_TEMPLATE_NAME = "agent_notification"

        assert is_whatsapp_available() is False

    @patch("src.agent.tools.whatsapp.Config")
    def test_returns_false_when_template_missing(self, mock_config: MagicMock) -> None:
        """Should return False when template name is not set."""
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "token"
        mock_config.WHATSAPP_TEMPLATE_NAME = ""

        assert is_whatsapp_available() is False
