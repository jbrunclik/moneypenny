"""WhatsApp messaging tool for autonomous agents.

This tool allows autonomous agents to send WhatsApp messages to the user.
It uses Meta's WhatsApp Cloud API.

IMPORTANT: This tool should only be used when the agent is explicitly instructed
to send WhatsApp notifications in its system prompt. Do not send messages
unless the user has specifically requested WhatsApp notifications.
"""

import json
import re
from typing import Any

import requests
from langchain_core.tools import tool

from src.agent.tools.context import get_agent_name, get_conversation_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _markdown_to_whatsapp(text: str) -> str:
    """Convert Markdown formatting to WhatsApp-compatible formatting.

    WhatsApp supports limited formatting:
    - *bold* (same as Markdown **)
    - _italic_ (same as Markdown *)
    - ~strikethrough~
    - ```monospace```

    This function converts common Markdown to WhatsApp format and strips
    unsupported syntax.
    """
    # IMPORTANT: Process images BEFORE links since ![alt](url) contains [alt](url)
    # Remove image syntax ![alt](url) - just show the alt text
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"[Image: \1]", text)

    # Convert Markdown links [text](url) to "text (url)"
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Convert Markdown bold **text** to WhatsApp bold *text*
    text = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", text)

    # Convert Markdown headers to bold (# Title -> *Title*)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Convert Markdown code blocks - remove language specifiers like ```python
    # Replace opening ``` with optional language to just ```
    text = re.sub(r"```[a-zA-Z]*\n?", "```\n", text)

    # Convert inline code `code` - WhatsApp doesn't have inline code,
    # so we'll just remove the backticks (but not triple backticks)
    text = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"\1", text)

    # Convert Markdown horizontal rules to simple line
    text = re.sub(r"^[-*_]{3,}$", "───", text, flags=re.MULTILINE)

    # Clean up excessive newlines (more than 2 consecutive)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


class WhatsAppError(Exception):
    """Exception raised for WhatsApp API errors."""

    pass


def _whatsapp_api_request(
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
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=Config.WHATSAPP_API_TIMEOUT,
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
                elif error_code == 131030:  # Recipient phone number not in allowed list
                    raise WhatsAppError(
                        "Recipient phone number is not in the allowed list. "
                        "Add the number to your test recipients in Meta Business Suite."
                    )
                elif error_code == 131031:  # Recipient not registered on WhatsApp
                    raise WhatsAppError("The recipient phone number is not registered on WhatsApp.")
                else:
                    raise WhatsAppError(f"WhatsApp API error ({error_code}): {error_message}")
            except json.JSONDecodeError:
                raise WhatsAppError(
                    f"WhatsApp API error ({response.status_code}): {error_msg}"
                ) from None

        result: dict[str, Any] = response.json()
        return result

    except requests.RequestException as e:
        logger.error(
            "WhatsApp API request failed",
            extra={"error": str(e), "endpoint": endpoint},
        )
        raise WhatsAppError(f"Failed to connect to WhatsApp API: {e}") from e


def _truncate_message(message: str, max_length: int, suffix: str = "...") -> str:
    """Truncate a message to fit within the maximum length.

    Args:
        message: The message to truncate
        max_length: Maximum allowed length
        suffix: Suffix to append when truncating (default: "...")

    Returns:
        Truncated message with suffix if it exceeded max_length
    """
    if len(message) <= max_length:
        return message

    # Account for suffix length
    truncate_at = max_length - len(suffix)
    if truncate_at <= 0:
        return suffix[:max_length]

    # Try to truncate at a word boundary
    truncated = message[:truncate_at]
    last_space = truncated.rfind(" ")

    # Only use word boundary if it's not too far back (at least 80% of truncate_at)
    if last_space > truncate_at * 0.8:
        truncated = truncated[:last_space]

    return truncated + suffix


def _sanitize_for_template(text: str) -> str:
    """Sanitize text for WhatsApp template parameters.

    WhatsApp template body parameters cannot contain:
    - Newline characters
    - Tab characters
    - More than 4 consecutive spaces

    This function replaces these with allowed alternatives.
    """
    # Replace newlines with " | " separator
    text = re.sub(r"\n+", " | ", text)

    # Replace tabs with single space
    text = text.replace("\t", " ")

    # Replace 4+ consecutive spaces with 3 spaces (max allowed)
    text = re.sub(r" {4,}", "   ", text)

    return text.strip()


def _format_agent_message(
    content: str,
    conversation_url: str | None = None,
) -> tuple[str, bool]:
    """Format an agent message for WhatsApp.

    Converts Markdown to WhatsApp-compatible formatting, truncates if needed,
    and appends conversation URL if provided.

    Args:
        content: The message content from the agent (may contain Markdown)
        conversation_url: Optional URL to the conversation

    Returns:
        Tuple of (formatted message, was_truncated)
    """
    max_length = Config.WHATSAPP_MAX_MESSAGE_LENGTH

    # Convert Markdown to WhatsApp-compatible formatting
    whatsapp_content = _markdown_to_whatsapp(content)

    # Build the URL suffix if provided
    url_suffix = ""
    if conversation_url:
        url_suffix = f" | View: {conversation_url}"

    # Reserve space for URL suffix and truncate content first
    available_for_content = max_length - len(url_suffix)
    truncated_content = _truncate_message(whatsapp_content, available_for_content)

    # Detect if truncation occurred by comparing converted content length
    was_truncated = len(whatsapp_content) > available_for_content

    # Combine content and URL suffix, then sanitize for template parameters
    combined = truncated_content + url_suffix
    return _sanitize_for_template(combined), was_truncated


def _send_text_message(
    phone_number: str,
    message: str,
) -> dict[str, Any]:
    """Send a text message via WhatsApp.

    NOTE: Free-form text messages only work within 24 hours after the user
    messages you first. For business-initiated conversations (first contact),
    use _send_template_message instead.

    Args:
        phone_number: Recipient phone number in E.164 format (e.g., +1234567890)
        message: Message text to send

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
        "type": "text",
        "text": {"body": message},
    }

    response = _whatsapp_api_request("/messages", data)

    logger.info(
        "WhatsApp text message sent",
        extra={
            "message_id": response.get("messages", [{}])[0].get("id"),
            "phone_number_masked": f"***{normalized_phone[-4:]}",
        },
    )

    return response


def _send_template_message(
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
                        {"type": "text", "text": agent_name},
                        {"type": "text", "text": message},
                    ],
                }
            ],
        },
    }

    response = _whatsapp_api_request("/messages", data)

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


def _get_user_whatsapp_phone(user_id: str) -> str | None:
    """Get the user's WhatsApp phone number from the database.

    Args:
        user_id: The user ID

    Returns:
        The user's WhatsApp phone number, or None if not set
    """
    from src.db.models import db

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

    # Check if WhatsApp is configured at app level
    if not Config.WHATSAPP_PHONE_NUMBER_ID or not Config.WHATSAPP_ACCESS_TOKEN:
        return json.dumps(
            {
                "error": "WhatsApp not configured",
                "message": "WhatsApp integration is not configured. "
                "Please set WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN.",
            }
        )

    if not Config.WHATSAPP_TEMPLATE_NAME:
        return json.dumps(
            {
                "error": "WhatsApp template not configured",
                "message": "WHATSAPP_TEMPLATE_NAME is required. "
                "Create a message template in Meta Business Suite and configure it.",
            }
        )

    # Check permission for autonomous agents
    check_autonomous_permission("whatsapp", {"action": "send_message"})

    # Get conversation context for the link and user ID
    conversation_id, user_id = get_conversation_context()

    # Get user's WhatsApp phone number
    if not user_id:
        return json.dumps(
            {
                "error": "No user context",
                "message": "Cannot determine user. WhatsApp messages require a user context.",
            }
        )

    recipient_phone = _get_user_whatsapp_phone(user_id)
    if not recipient_phone:
        return json.dumps(
            {
                "error": "No WhatsApp phone configured",
                "message": "User has not configured their WhatsApp phone number in settings.",
            }
        )

    # Build conversation URL (only if APP_URL is configured)
    conversation_url = None
    if include_conversation_link and conversation_id and Config.APP_URL:
        # Build full clickable URL using APP_URL (e.g., https://chat.example.com)
        # The fragment (#/conversations/...) is used for SPA routing
        base_url = Config.APP_URL.rstrip("/")
        conversation_url = f"{base_url}/#/conversations/{conversation_id}"

    try:
        # Format the message
        formatted_message, was_truncated = _format_agent_message(message, conversation_url)

        # Send template message (required for business-initiated conversations)
        agent_name = get_agent_name() or "AI Chatbot"
        response = _send_template_message(
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
        logger.error(
            "WhatsApp tool error",
            extra={"error": str(e)},
            exc_info=True,
        )
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(
            "Unexpected WhatsApp tool error",
            extra={"error": str(e)},
            exc_info=True,
        )
        return json.dumps({"error": f"Unexpected error: {e}"})


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
