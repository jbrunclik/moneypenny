"""Formatting an agent's message for a WhatsApp template parameter.

WhatsApp supports only a little formatting, and template parameters can't
hold newlines, tabs or long runs of spaces: Markdown is converted, the text
truncated to the configured length and sanitized (see whatsapp.py).
"""

import re

from src.config import Config


def markdown_to_whatsapp(text: str) -> str:
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


def truncate_message(message: str, max_length: int, suffix: str = "...") -> str:
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


def sanitize_for_template(text: str) -> str:
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


def format_agent_message(
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
    whatsapp_content = markdown_to_whatsapp(content)

    # Build the URL suffix if provided
    url_suffix = ""
    if conversation_url:
        url_suffix = f" | View: {conversation_url}"

    # Reserve space for URL suffix and truncate content first
    available_for_content = max_length - len(url_suffix)
    truncated_content = truncate_message(whatsapp_content, available_for_content)

    # Detect if truncation occurred by comparing converted content length
    was_truncated = len(whatsapp_content) > available_for_content

    # Combine content and URL suffix, then sanitize for template parameters
    combined = truncated_content + url_suffix
    return sanitize_for_template(combined), was_truncated
