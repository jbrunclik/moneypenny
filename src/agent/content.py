"""Content extraction utilities for chat agent responses.

This module handles extracting text, thinking content, and metadata
from various response formats (strings, dicts, lists).
"""

import json
import re
from typing import Any


def extract_text_content(content: str | list[Any] | dict[str, Any]) -> str:
    """Extract text from message content, handling various formats from Gemini."""
    if isinstance(content, str):
        return content

    # Handle dict format (e.g., {'type': 'text', 'text': '...'})
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        # If it has a 'text' key directly, use that
        if "text" in content:
            return str(content["text"])
        # Otherwise skip non-text content
        return ""

    # Handle list format from Gemini (e.g., [{'type': 'text', 'text': '...'}])
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                # Extract text from dict, skip 'extras' and other metadata
                if part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif "text" in part and "type" not in part:
                    text_parts.append(str(part["text"]))
                # Skip parts with 'extras', 'signature', etc.
            elif isinstance(part, str):
                text_parts.append(part)
        return "".join(text_parts)

    return str(content)


def extract_thinking_and_text(
    content: str | list[Any] | dict[str, Any],
) -> tuple[str | None, str]:
    """Extract thinking content and regular text from message content.

    Gemini thinking models return content with parts that have 'thought': true.

    Args:
        content: The message content (string, dict, or list of parts)

    Returns:
        Tuple of (thinking_text, regular_text)
        - thinking_text: The model's reasoning/thinking (None if not present)
        - regular_text: The regular response text
    """
    if isinstance(content, str):
        return None, content

    # Handle dict format
    if isinstance(content, dict):
        # Check if this is a thought part (old format: {'thought': true, 'text': '...'})
        if content.get("thought"):
            return str(content.get("text", "")), ""
        # Check for thinking content (Gemini format: {'type': 'thinking', 'thinking': '...'})
        if content.get("type") == "thinking":
            return str(content.get("thinking", "")), ""
        if content.get("type") == "text":
            return None, str(content.get("text", ""))
        if "text" in content:
            return None, str(content["text"])
        return None, ""

    # Handle list format - separate thought parts from regular text parts
    if isinstance(content, list):
        thinking_parts = []
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                # Check for thought content (old format: {'thought': true, 'text': '...'})
                if part.get("thought"):
                    thinking_parts.append(str(part.get("text", "")))
                # Check for thinking content (Gemini format: {'type': 'thinking', 'thinking': '...'})
                elif part.get("type") == "thinking":
                    thinking_parts.append(str(part.get("thinking", "")))
                elif part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif "text" in part and "type" not in part:
                    text_parts.append(str(part["text"]))
                # Skip parts with 'extras', 'signature', etc.
            elif isinstance(part, str):
                text_parts.append(part)

        thinking = "".join(thinking_parts) if thinking_parts else None
        text = "".join(text_parts)
        return thinking, text

    return None, str(content)


# Pattern to match metadata block: <!-- METADATA:\n{...}\n-->
METADATA_PATTERN = re.compile(
    r"<!--\s*METADATA:\s*\n(.*?)\n\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# Pattern to match malformed METADATA at start (no proper closing)
# This catches cases where LLM outputs <!-- METADATA: {...} immediately followed by content
# without proper newlines and closing -->
# Uses negative lookahead to avoid matching valid METADATA blocks that have proper closing
MALFORMED_METADATA_START_PATTERN = re.compile(
    r"^<!--\s*METADATA:\s*\{[^}]*\}(?!\s*\n\s*-->)(?!\s*-->)",
    re.IGNORECASE,
)


# Pattern to match Gemini's tool call JSON format that sometimes leaks into response text
# This happens when the model outputs the tool call description as text alongside the actual tool call
# Format: {"action": "tool_name", "action_input": "..."} or {"action": "tool_name", "action_input": {...}}
# Note: Properly handles escaped quotes in string values. For object values, matches balanced braces
# up to 2 levels deep (sufficient for typical tool call artifacts like {"prompt": "..."}).
# The pattern is specific enough (requires "action" and "action_input" keys) to avoid false matches.
TOOL_CALL_JSON_PATTERN = re.compile(
    r'\n*\{\s*"action":\s*"(?:[^"\\]|\\.)+"\s*,\s*"action_input":\s*(?:"(?:[^"\\]|\\.)*"|\{(?:[^{}]|\{[^}]*\})*\})\s*\}',
    re.DOTALL,
)


def clean_tool_call_json(response: str) -> str:
    """Remove tool call JSON artifacts that sometimes leak into LLM response text.

    Gemini may output tool call descriptions as text alongside actual function calls.
    This removes those JSON blocks to keep only natural language content.

    Args:
        response: The LLM response text

    Returns:
        Response with tool call JSON removed
    """
    return TOOL_CALL_JSON_PATTERN.sub("", response).strip()


def _find_json_object_end(text: str, start_pos: int) -> int | None:
    """Find the end position of a complete JSON object starting at start_pos.

    Returns the position after the closing brace, or None if not found.
    """
    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start_pos, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                return i + 1

    return None


def _extract_html_comment_metadata(content: str) -> tuple[str, dict[str, Any]]:
    """Extract metadata from HTML comment format.

    Handles metadata anywhere in the response (not just at end) by keeping
    content both before and after the metadata block.

    Returns:
        Tuple of (clean_content, metadata_dict)
    """
    match = METADATA_PATTERN.search(content)
    if not match:
        return content, {}

    try:
        metadata = json.loads(match.group(1).strip())
        # Keep content before AND after the metadata block
        before = content[: match.start()].rstrip()
        after = content[match.end() :].lstrip()
        clean_content = f"{before}\n\n{after}".strip() if after else before
        return clean_content, metadata
    except (json.JSONDecodeError, AttributeError):
        return content, {}


def _extract_plain_json_metadata(content: str) -> tuple[str, dict[str, Any]]:
    """Extract metadata from plain JSON at end of content.

    Searches backwards for JSON objects containing 'sources' or 'generated_images'.

    Returns:
        Tuple of (clean_content, metadata_dict)
    """
    search_start = len(content)

    while True:
        last_brace = content.rfind("{", 0, search_start)
        if last_brace == -1:
            break

        end_pos = _find_json_object_end(content, last_brace)
        if end_pos:
            try:
                parsed = json.loads(content[last_brace:end_pos])
                if "sources" in parsed or "generated_images" in parsed:
                    return content[:last_brace].rstrip(), parsed
            except (json.JSONDecodeError, ValueError):
                pass

        search_start = last_brace

    return content, {}


def extract_metadata_from_response(response: str) -> tuple[str, dict[str, Any]]:
    """Extract metadata from LLM response and return clean content.

    The LLM is instructed to append metadata at the end of responses in the format:
    <!-- METADATA:
    {"sources": [...]}
    -->

    However, sometimes the LLM outputs plain JSON without the HTML comment wrapper,
    or outputs it in both formats. This function prefers the HTML comment format,
    but removes both if they both exist.

    Also removes any tool call JSON artifacts that leaked into the response.

    Args:
        response: The raw LLM response text

    Returns:
        Tuple of (clean_content, metadata_dict)
        - clean_content: Response with metadata block and tool call JSON removed
        - metadata_dict: Parsed metadata (empty dict if none found or parse error)
    """
    response = clean_tool_call_json(response)

    # Clean malformed METADATA at start (no proper closing -->)
    # This can happen when LLM outputs METADATA immediately after MSG_CONTEXT
    # e.g., "<!-- METADATA: {"language": "en"}Actual content here..."
    response = MALFORMED_METADATA_START_PATTERN.sub("", response).lstrip()

    # Try HTML comment format first (preferred)
    clean_content, metadata = _extract_html_comment_metadata(response)

    # Also check for plain JSON and remove it (even if HTML comment found)
    plain_content, plain_metadata = _extract_plain_json_metadata(clean_content)

    # Use HTML comment metadata if found, otherwise use plain JSON metadata
    if not metadata and plain_metadata:
        metadata = plain_metadata

    return plain_content.rstrip(), metadata


def strip_full_result_from_tool_content(content: str) -> str:
    """Strip the _full_result field from tool result JSON to avoid sending large data to LLM.

    The generate_image tool returns image data in a _full_result field that should be
    extracted server-side but not sent back to the LLM (to avoid ~650K tokens of base64).

    Args:
        content: The tool result content (JSON string)

    Returns:
        The content with _full_result removed, or original content if not JSON
    """
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "_full_result" in data:
            # Remove the _full_result field before sending to LLM
            data_for_llm = {k: v for k, v in data.items() if k != "_full_result"}
            return json.dumps(data_for_llm)
        return content
    except (json.JSONDecodeError, TypeError):
        return content
