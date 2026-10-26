"""The WhatsApp Cloud API client (src/agent/tools/whatsapp_api.py)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.agent.tools.whatsapp_api import WhatsAppError, send_template_message, whatsapp_api_request


class TestSendTemplateMessage:
    """Template parameters must be Meta-safe (R8)."""

    @patch("src.agent.tools.whatsapp_api.whatsapp_api_request")
    def test_sanitizes_agent_name_parameter(self, mock_request: MagicMock) -> None:
        """A user-defined agent name with newlines/tabs must not reach Meta
        raw - the whole send is rejected otherwise."""
        mock_request.return_value = {"messages": [{"id": "msg123"}]}

        send_template_message(
            "+1234567890",
            "agent_notification",
            "Daily\nBriefing\t    Agent",
            "hello",
        )

        params = mock_request.call_args.args[1]["template"]["components"][0]["parameters"]
        agent_name_param = params[0]["text"]
        assert "\n" not in agent_name_param
        assert "\t" not in agent_name_param
        assert "    " not in agent_name_param


class TestWhatsAppApiRequest:
    """Tests for whatsapp_api_request function."""

    @patch("src.agent.tools.whatsapp_api.httpx.post")
    @patch("src.agent.tools.whatsapp_api.Config")
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

        result = whatsapp_api_request("/messages", {"test": "data"})

        assert result == {"messages": [{"id": "msg123"}]}
        mock_post.assert_called_once()

    @patch("src.agent.tools.whatsapp_api.httpx.post")
    @patch("src.agent.tools.whatsapp_api.Config")
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
            whatsapp_api_request("/messages", {"test": "data"})

        assert "invalid or expired" in str(exc_info.value).lower()

    @patch("src.agent.tools.whatsapp_api.httpx.post")
    @patch("src.agent.tools.whatsapp_api.Config")
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
            whatsapp_api_request("/messages", {"test": "data"})

        assert "allowed list" in str(exc_info.value).lower()

    @patch("src.agent.tools.whatsapp_api.httpx.post")
    @patch("src.agent.tools.whatsapp_api.Config")
    def test_handles_network_error(self, mock_config: MagicMock, mock_post: MagicMock) -> None:
        """Should raise WhatsAppError on network failure."""
        mock_config.WHATSAPP_API_BASE_URL = "https://graph.facebook.com"
        mock_config.WHATSAPP_API_VERSION = "v18.0"
        mock_config.WHATSAPP_PHONE_NUMBER_ID = "123456"
        mock_config.WHATSAPP_ACCESS_TOKEN = "test_token"
        mock_config.WHATSAPP_API_TIMEOUT = 10

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        with pytest.raises(WhatsAppError) as exc_info:
            whatsapp_api_request("/messages", {"test": "data"})

        assert "Failed to connect" in str(exc_info.value)
