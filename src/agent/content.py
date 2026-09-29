"""Content extraction utilities for chat agent responses.

This module handles extracting text, thinking content, and structured metadata
from various response formats (strings, dicts, lists).
"""

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

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
    except json.JSONDecodeError, TypeError:
        return content


# ============ Structured Metadata Extraction ============
# These functions replace the old text-based <!-- METADATA: --> parsing.
# Metadata is now extracted from tool calls and tool results, and deterministic
# server-side analysis. Memory operations are NOT extracted here - manage_memory
# performs its own writes and reports the outcome to the model.


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


# Source chips per turn: pages actually read, else the top search results
_MAX_READ_SOURCES = 10
_MAX_SEARCH_SOURCES = 5


def _json_object(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError, TypeError:
        return None
    return data if isinstance(data, dict) else None


def _title_from_url(url: str) -> str:
    """Readable stand-in title when the tool did not report one."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else url


def _search_results(data: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Result lists of a single ({results}) or batched ({searches}) web_search."""
    if isinstance(data.get("searches"), list):
        return [s.get("results") or [] for s in data["searches"] if isinstance(s, dict)]
    return [data.get("results") or []]


def extract_read_sources(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Source chips for a turn, derived from what its tools actually read.

    Replaces the cite_sources tool: the model sent it WITHOUT answer text in
    79% of tool-using turns (Sep 2026: 687 of 869), which cost a full extra
    model round each time (~49M input tokens/month) - and it forgot it in
    others. Sources are now the pages the turn READ: research pages that
    were fetched, successful fetch_url calls, browser pages, and sources a
    delegate_task subagent returned. A turn that answered from search
    snippets alone gets the top search results (rank-interleaved) instead.

    Returns:
        [{"title", "url"}], de-duplicated by URL, at most 10 read pages or
        5 search results.
    """
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls:
                call_id = tc.get("id")
                if call_id:
                    calls[call_id] = (tc.get("name", ""), tc.get("args") or {})

    read: list[dict[str, str]] = []
    searched: list[list[dict[str, Any]]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        call_name, args = calls.get(msg.tool_call_id, ("", {}))
        name = msg.name or call_name
        data = _json_object(msg.content)
        if name in ("research", "delegate_task") and data:
            for source in data.get("sources") or []:
                # research lists failed fetches too; only pages with content were read
                if isinstance(source, dict) and (name == "delegate_task" or "content" in source):
                    read.append(source)
        elif name == "fetch_url":
            url = args.get("url")
            failed = data is not None and bool(data.get("error"))
            if url and msg.content and not failed:
                read.append({"title": _title_from_url(str(url)), "url": str(url)})
        elif name == "browser" and data and data.get("success") and data.get("url"):
            read.append(data)
        elif name == "web_search" and data:
            searched.extend(_search_results(data))

    def unique(items: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            url = item.get("url") or item.get("href")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(
                {"title": str(item.get("title") or _title_from_url(str(url))), "url": str(url)}
            )
            if len(out) >= limit:
                break
        return out

    if read:
        return unique(read, _MAX_READ_SOURCES)
    interleaved = [
        results[rank]
        for rank in range(max((len(r) for r in searched), default=0))
        for results in searched
        if rank < len(results) and isinstance(results[rank], dict)
    ]
    return unique(interleaved, _MAX_SEARCH_SOURCES)


def extract_conversation_title(messages: list[BaseMessage]) -> str | None:
    """Extract the title arg from the turn's set_conversation_title calls.

    The agent retitles a conversation when its scope has drifted from the
    current title. This is an extract-only tool: the args
    are read straight off the AIMessage tool calls. When a multi-step turn
    retitles more than once, the last call wins.

    Args:
        messages: List of LangChain messages from the graph result

    Returns:
        The cleaned title (quotes stripped, clamped to TITLE_MAX_LENGTH),
        or None when the tool wasn't called or the title was blank.
    """
    from src.config import Config

    title: str | None = None
    for msg in messages:
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            if tc.get("name") != "set_conversation_title":
                continue
            candidate = str(tc.get("args", {}).get("title", "")).strip().strip("\"'").strip()
            if candidate:
                title = candidate

    if title is None:
        return None
    if len(title) > Config.TITLE_MAX_LENGTH:
        title = title[: Config.TITLE_TRUNCATE_LENGTH] + "..."
    return title
