"""Content extraction utilities for chat agent responses.

This module handles extracting text, thinking content, and structured metadata
from various response formats (strings, dicts, lists).
"""

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from src.utils.logging import get_logger

logger = get_logger(__name__)


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


# ============ Structured Metadata Extraction ============
# These functions replace the old text-based <!-- METADATA: --> parsing.
# Metadata is now extracted from tool calls (cite_sources, manage_memory)
# and deterministic server-side analysis.


def detect_response_language(text: str) -> str | None:
    """Detect the language of a response using langdetect.

    Args:
        text: The response text to analyze

    Returns:
        ISO 639-1 language code (e.g., "en", "cs") or None if detection fails
    """
    if not text or len(text.strip()) < 10:
        return None

    try:
        from langdetect import detect

        lang = detect(text)
        # langdetect returns codes like "en", "cs", "zh-cn" etc.
        # Normalize to 2-char ISO 639-1
        return str(lang).lower().split("-")[0][:2]
    except Exception:
        # langdetect can raise LangDetectException for short/ambiguous text
        return None


def extract_image_prompts_from_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Extract image generation prompts from generate_image tool calls in message history.

    Scans AIMessage tool_calls for generate_image calls and returns the prompts used.

    Args:
        messages: List of LangChain messages from the graph result

    Returns:
        List of dicts with "prompt" key, e.g. [{"prompt": "a sunset over mountains"}]
    """
    prompts: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "generate_image":
                    prompt = tc.get("args", {}).get("prompt")
                    if prompt:
                        prompts.append({"prompt": prompt})
    return prompts


def extract_metadata_tool_args(
    messages: list[BaseMessage],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Extract cite_sources and manage_memory args from the final AIMessage.

    Scans the last AIMessage's tool_calls for metadata tools and returns
    their structured args directly (no JSON parsing needed - Gemini validates
    the schema at the API level).

    Args:
        messages: List of LangChain messages from the graph result

    Returns:
        Tuple of (sources, memory_operations)
        - sources: List of source dicts with "title" and "url"
        - memory_operations: List of memory operation dicts
    """
    from src.agent.tools.metadata import METADATA_TOOL_NAMES

    sources: list[dict[str, str]] = []
    memory_ops: list[dict[str, Any]] = []

    # Scan from the end - metadata tools are typically on the last AIMessage
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            name = tc.get("name")
            args = tc.get("args", {})

            if name == "cite_sources":
                raw_sources = args.get("sources", [])
                for s in raw_sources:
                    if isinstance(s, dict) and "title" in s and "url" in s:
                        sources.append({"title": str(s["title"]), "url": str(s["url"])})
            elif name == "manage_memory":
                raw_ops = args.get("operations", [])
                for op in raw_ops:
                    if isinstance(op, dict) and "action" in op:
                        memory_ops.append(op)

        # Only check the last AIMessage that has tool calls
        if any(tc.get("name") in METADATA_TOOL_NAMES for tc in msg.tool_calls):
            break

    return sources, memory_ops


def extract_sources_fallback_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Fallback: extract sources from web_search tool results when cite_sources wasn't called.

    If the model used web_search but didn't call cite_sources, this extracts
    sources from the raw tool results to prevent silent source loss.

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        List of source dicts with "title" and "url"
    """
    sources: list[dict[str, str]] = []

    for result in tool_results:
        if not isinstance(result, dict) or result.get("type") != "tool":
            continue

        content = result.get("content", "")
        if not content:
            continue

        try:
            data = json.loads(content) if isinstance(content, str) else {}
        except (json.JSONDecodeError, TypeError):
            continue

        # web_search returns a list of result dicts
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "title" in item and "href" in item:
                    sources.append({"title": str(item["title"]), "url": str(item["href"])})
        elif isinstance(data, dict):
            # Check for results array inside the response
            results = data.get("results", [])
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and "title" in item and "href" in item:
                        sources.append({"title": str(item["title"]), "url": str(item["href"])})

    return sources
