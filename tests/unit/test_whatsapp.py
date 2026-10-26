"""Unit tests for src/agent/tools/whatsapp module."""

import json
from unittest.mock import MagicMock, patch

from src.agent.tools.whatsapp import is_whatsapp_available, whatsapp
from src.agent.tools.whatsapp_api import WhatsAppError


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

    @patch("src.agent.tools.whatsapp.send_template_message")
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

    @patch("src.agent.tools.whatsapp.send_template_message")
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

    @patch("src.agent.tools.whatsapp.send_template_message")
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

    @patch("src.agent.tools.whatsapp.send_template_message")
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

    @patch("src.agent.tools.whatsapp_format.Config.WHATSAPP_MAX_MESSAGE_LENGTH", 100)
    @patch("src.agent.tools.whatsapp.send_template_message")
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

    @patch("src.agent.tools.whatsapp.send_template_message")
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
        mock_config.APP_NAME = "Moneypenny"
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
        assert call_args[0][2] == "Moneypenny"  # default agent name (Config.APP_NAME)


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
