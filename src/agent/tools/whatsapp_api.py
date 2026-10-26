"""Meta's WhatsApp Cloud API: sending a template message (see whatsapp.py)."""

import json
from typing import Any

import httpx

from src.agent.tools.whatsapp_format import sanitize_for_template
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class WhatsAppError(Exception):
    """Exception raised for WhatsApp API errors."""

    pass


def whatsapp_api_request(
    endpoint: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Make a request to the WhatsApp Cloud API.

    Args:
        endpoint: API endpoint path (e.g., "/messages")
        data: Request body

    Returns:
        JSON response

    Raises:
        WhatsAppError: On API errors
    """
    url = f"{Config.WHATSAPP_API_BASE_URL}/{Config.WHATSAPP_API_VERSION}/{Config.WHATSAPP_PHONE_NUMBER_ID}{endpoint}"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.post(
            url,
            headers=headers,
            json=data,
            timeout=Config.WHATSAPP_API_TIMEOUT_SECONDS,
        )

        if response.status_code >= 400:
            error_msg = response.text
            logger.warning(
                "WhatsApp API error",
                extra={
                    "status_code": response.status_code,
                    "error": error_msg,
                    "endpoint": endpoint,
                },
            )

            # Parse error response for better error messages
            try:
                error_data = response.json()
                error_detail = error_data.get("error", {})
                error_message = error_detail.get("message", error_msg)
                error_code = error_detail.get("code", response.status_code)

                # Handle common error codes
                if error_code == 190:  # Invalid OAuth access token
                    raise WhatsAppError(
                        "WhatsApp access token is invalid or expired. "
                        "Please update WHATSAPP_ACCESS_TOKEN in your configuration."
                    )
                if error_code == 131030:  # Recipient phone number not in allowed list
                    raise WhatsAppError(
                        "Recipient phone number is not in the allowed list. "
                        "Add the number to your test recipients in Meta Business Suite."
                    )
                if error_code == 131031:  # Recipient not registered on WhatsApp
                    raise WhatsAppError("The recipient phone number is not registered on WhatsApp.")
                raise WhatsAppError(f"WhatsApp API error ({error_code}): {error_message}")
            except json.JSONDecodeError:
                raise WhatsAppError(
                    f"WhatsApp API error ({response.status_code}): {error_msg}"
                ) from None

        result: dict[str, Any] = response.json()
        return result

    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error(  # noqa: TRY400 - network or JSON error, re-raised as WhatsAppError
            "WhatsApp API request failed",
            extra={"error": str(e), "endpoint": endpoint},
        )
        raise WhatsAppError(f"Failed to connect to WhatsApp API: {e}") from e


def send_template_message(
    phone_number: str,
    template_name: str,
    agent_name: str,
    message: str,
    language_code: str = "en",
) -> dict[str, Any]:
    """Send a template message via WhatsApp.

    Template messages are required for business-initiated conversations
    (when the user hasn't messaged you in the last 24 hours).

    The template must be pre-approved by Meta and should have a body
    with two variables:
    - {{1}} = agent name
    - {{2}} = message content

    Example template body: "{{1}}:\n\n{{2}}"

    Args:
        phone_number: Recipient phone number in E.164 format (e.g., +1234567890)
        template_name: Name of the approved message template
        agent_name: Name of the agent sending the message
        message: Message content to insert into the template variable
        language_code: Template language code (default: "en")

    Returns:
        API response with message ID

    Raises:
        WhatsAppError: On API errors
    """
    # Normalize phone number (remove + if present, API expects without it)
    normalized_phone = phone_number.lstrip("+")

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        # Sanitize EVERY parameter at the boundary - Meta
                        # rejects the whole send if any contains newlines,
                        # tabs or 4+ consecutive spaces (the user-defined
                        # agent name went in raw - R8)
                        {"type": "text", "text": sanitize_for_template(agent_name)},
                        {"type": "text", "text": sanitize_for_template(message)},
                    ],
                }
            ],
        },
    }

    response = whatsapp_api_request("/messages", data)

    logger.info(
        "WhatsApp template message sent",
        extra={
            "message_id": response.get("messages", [{}])[0].get("id"),
            "template_name": template_name,
            "agent_name": agent_name,
            "phone_number_masked": f"***{normalized_phone[-4:]}",
        },
    )

    return response
