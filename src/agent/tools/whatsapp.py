"""WhatsApp messaging tool for autonomous agents.

This tool allows autonomous agents to send WhatsApp messages to the user.
It uses Meta's WhatsApp Cloud API.

IMPORTANT: This tool should only be used when the agent is explicitly instructed
to send WhatsApp notifications in its system prompt. Do not send messages
unless the user has specifically requested WhatsApp notifications.
"""

import json

from langchain_core.tools import tool

from src.agent.tools.context import get_agent_name, get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.whatsapp_api import WhatsAppError, send_template_message
from src.agent.tools.whatsapp_format import format_agent_message
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _get_user_whatsapp_phone(user_id: str) -> str | None:
    """Get the user's WhatsApp phone number from the database.

    Args:
        user_id: The user ID

    Returns:
        The user's WhatsApp phone number, or None if not set
    """
    user = db.get_user_by_id(user_id)
    if not user:
        return None
    return user.whatsapp_phone


@tool
def whatsapp(
    message: str,
    include_conversation_link: bool = True,
) -> str:
    """Send a WhatsApp message to the user.

    IMPORTANT: Only use this tool when explicitly instructed to send WhatsApp
    notifications in your goals/system prompt. Do not send unsolicited messages.

    This tool sends a message to the user's configured WhatsApp number.
    Use it to notify the user of important results, completed tasks, or
    information that needs their attention.

    MESSAGE FORMATTING:
    WhatsApp template messages have strict formatting requirements. Your message
    will be automatically sanitized:
    - Newlines are converted to " | " separators
    - Multiple spaces are collapsed
    - Messages exceeding 1024 characters are truncated

    For best results, write CONCISE, SINGLE-PARAGRAPH messages. Avoid:
    - Bullet points or numbered lists (use comma-separated items instead)
    - Multiple paragraphs (summarize in one paragraph)
    - Long explanations (provide key points only)

    Good example: "Task completed successfully. Found 3 issues: missing auth,
    slow query, outdated dependency."

    NOTE: A link to this conversation is automatically appended to the message
    (unless include_conversation_link=False), so you don't need to tell the user
    where to find details - they can click the link.

    Bad example (will be mangled):
    "Results:
    - Item 1
    - Item 2"

    Args:
        message: The message content to send. Keep it concise and avoid
            newlines/bullet points. Will be truncated if too long.
        include_conversation_link: Whether to append a link to this conversation
            at the end of the message (default: True). Set to False if you want
            to send only the message content.

    Returns:
        JSON string with the result (success status and message ID, or error)

    Example usage in agent goals:
        "After completing the analysis, send the results via WhatsApp"
        "Notify me via WhatsApp when the scheduled task completes"
    """
    logger.info("whatsapp tool called", extra={"message_length": len(message)})

    config_error = _whatsapp_config_error()
    if config_error:
        return config_error

    # Check permission for autonomous agents
    check_autonomous_permission("whatsapp", {"action": "send_message"})

    # Get conversation context for the link and user ID
    conversation_id, user_id = get_conversation_context()

    # Get user's WhatsApp phone number
    if not user_id:
        return tool_error(
            "No user context",
            message="Cannot determine user. WhatsApp messages require a user context.",
        )

    recipient_phone = _get_user_whatsapp_phone(user_id)
    if not recipient_phone:
        return tool_error(
            "No WhatsApp phone configured",
            message="User has not configured their WhatsApp phone number in settings.",
        )

    conversation_url = _conversation_url(conversation_id) if include_conversation_link else None
    return _send_agent_message(recipient_phone, message, conversation_url)


def _whatsapp_config_error() -> str | None:
    """The tool error when WhatsApp isn't configured at app level, else None."""
    # Check if WhatsApp is configured at app level
    if not Config.WHATSAPP_PHONE_NUMBER_ID or not Config.WHATSAPP_ACCESS_TOKEN:
        return tool_error(
            "WhatsApp not configured",
            retriable=False,
            message="WhatsApp integration is not configured. "
            "Please set WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN.",
        )

    if not Config.WHATSAPP_TEMPLATE_NAME:
        return tool_error(
            "WhatsApp template not configured",
            retriable=False,
            message="WHATSAPP_TEMPLATE_NAME is required. "
            "Create a message template in Meta Business Suite and configure it.",
        )
    return None


def _conversation_url(conversation_id: str | None) -> str | None:
    """The conversation's clickable URL (only if APP_URL is configured)."""
    if not conversation_id or not Config.APP_URL:
        return None
    # Build full clickable URL using APP_URL (e.g., https://chat.example.com)
    # The fragment (#/conversations/...) is used for SPA routing
    base_url = Config.APP_URL.rstrip("/")
    return f"{base_url}/#/conversations/{conversation_id}"


def _send_agent_message(recipient_phone: str, message: str, conversation_url: str | None) -> str:
    """Format and send the message as the configured template; return the tool result."""
    try:
        # Format the message
        formatted_message, was_truncated = format_agent_message(message, conversation_url)

        # Send template message (required for business-initiated conversations)
        agent_name = get_agent_name() or Config.APP_NAME
        response = send_template_message(
            recipient_phone,
            Config.WHATSAPP_TEMPLATE_NAME,
            agent_name,
            formatted_message,
        )

        # Extract message ID from response
        messages = response.get("messages", [])
        message_id = messages[0].get("id") if messages else None

        return json.dumps(
            {
                "success": True,
                "message_id": message_id,
                "message_length": len(formatted_message),
                "truncated": was_truncated,
            }
        )

    except WhatsAppError as e:
        logger.exception(
            "WhatsApp tool error",
            extra={"error": str(e)},
        )
        return tool_error(str(e))
    except Exception as e:
        logger.exception(
            "Unexpected WhatsApp tool error",
            extra={"error": str(e)},
        )
        return tool_error(f"Unexpected error: {e}")


def is_whatsapp_available() -> bool:
    """Check if WhatsApp integration is configured at app level.

    Note: This only checks app-level configuration (API credentials + template).
    Individual users still need to configure their phone number in settings.
    """
    return bool(
        Config.WHATSAPP_PHONE_NUMBER_ID
        and Config.WHATSAPP_ACCESS_TOKEN
        and Config.WHATSAPP_TEMPLATE_NAME
    )
