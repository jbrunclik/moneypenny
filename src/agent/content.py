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
    metadata: dict[str, Any] = {}
    clean_content = response

    # Try HTML comment format first (preferred format)
    match = METADATA_PATTERN.search(clean_content)
    if match:
        try:
            metadata = json.loads(match.group(1).strip())
            clean_content = clean_content[: match.start()].rstrip()
        except (json.JSONDecodeError, AttributeError):
            # If parsing fails, continue to check for plain JSON
            pass

    # Also check for plain JSON metadata and remove it (even if we already found HTML comment)
    # This ensures we remove both if the LLM outputs metadata in both formats
    # Search backwards for JSON objects that might contain metadata
    # We need to find the outermost object, so we search from the end
    search_start = len(clean_content)
    while True:
        # Find the last opening brace before our search start
        last_brace = clean_content.rfind("{", 0, search_start)
        if last_brace == -1:
            break

        end_pos = _find_json_object_end(clean_content, last_brace)
        if end_pos:
            try:
                parsed = json.loads(clean_content[last_brace:end_pos])
                if "sources" in parsed or "generated_images" in parsed:
                    # Only use this metadata if we didn't already get it from HTML comment
                    if not metadata:
                        metadata = parsed
                    # Remove the JSON from response regardless
                    clean_content = clean_content[:last_brace].rstrip()
                    break
            except (json.JSONDecodeError, ValueError):
                pass

        # Continue searching backwards from before this brace
        search_start = last_brace

    return clean_content.rstrip(), metadata


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
