"""Compact digests of a turn's tool outputs, kept for later turns.

A turn's ToolMessages are gone by the next turn: history only carries the
assistant's prose. Web sources survive as a title+URL digest (history.py), but
every other tool - Garmin, Todoist, calendar, kv_store, code execution - left
nothing, so "what was my HRV again?" had to re-call the tool or could not be
answered. This module keeps a bounded digest (tool, arguments, head of the
result) per call; it is persisted on the assistant message and rendered into
that message's MSG_CONTEXT in later turns.

Deterministic from persisted data, so the history prefix stays byte-stable.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.tools.metadata import EXTRACT_ONLY_TOOL_NAMES

# Tools whose outputs are NOT digested:
# - web/page tools: already covered by the sources digest
# - image generation: covered by generated_images
# - recall tools: they re-read data that is already persisted and re-searchable
# - memory writes: their outcome is stated in the reply
# - load_skill: repo-authored instructions - re-sending them in every later
#   turn's MSG_CONTEXT would crowd out the digests that matter
_EXCLUDED_TOOLS = EXTRACT_ONLY_TOOL_NAMES | frozenset(
    {
        "web_search",
        "fetch_url",
        "research",
        "browser",
        "generate_image",
        "search_conversations",
        "read_conversation",
        "search_memory",
        "manage_memory",
        "retrieve_file",
        "request_approval",
        "load_skill",  # repo-authored instructions, not user data
    }
)

# Result keys that are server-side plumbing, never content
_INTERNAL_KEYS = frozenset({"_full_result", "_efficiency", "_degraded"})

_ARGS_MAX_CHARS = 160
_RESULT_MAX_CHARS = 400
# Budget for one message's rendered digest - it is re-sent every turn the
# message stays in the verbatim window
TOOL_OUTPUTS_MAX_CHARS = 1500


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _compact_result(content: Any) -> str:
    if not isinstance(content, str):
        return "[non-text result]"
    try:
        data = json.loads(content)
    except json.JSONDecodeError, TypeError:
        return " ".join(content.split())
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in _INTERNAL_KEYS}
    return _compact_json(data)


def build_tool_outputs(messages: list[BaseMessage]) -> list[dict[str, str]] | None:
    """Digest every non-excluded tool call in ``messages`` (one turn's graph output).

    Returns ``[{"tool", "args", "result"}]`` in call order, bounded to
    TOOL_OUTPUTS_MAX_CHARS when rendered (a final ``{"tool": "…"}`` entry notes
    how many calls were dropped), or None when nothing qualifies.
    """
    calls: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tool_call in msg.tool_calls:
                call_id = tool_call.get("id")
                if call_id:
                    calls[call_id] = dict(tool_call)

    candidates: list[dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        call = calls.get(msg.tool_call_id, {})
        name = msg.name or call.get("name") or ""
        if not name or name in _EXCLUDED_TOOLS:
            continue
        candidates.append(
            {
                "tool": name,
                "args": _truncate(_compact_json(call.get("args", {})), _ARGS_MAX_CHARS),
                "result": _truncate(_compact_result(msg.content), _RESULT_MAX_CHARS),
            }
        )

    outputs: list[dict[str, str]] = []
    used = 0
    for i, entry in enumerate(candidates):
        size = len(_render(entry)) + 2
        if used + size > TOOL_OUTPUTS_MAX_CHARS:
            outputs.append(
                {"tool": "…", "args": "", "result": f"+{len(candidates) - i} more calls"}
            )
            break
        outputs.append(entry)
        used += size
    return outputs or None


def _render(entry: dict[str, str]) -> str:
    if entry["tool"] == "…":
        return entry["result"]
    return f"{entry['tool']}({entry['args']}) -> {entry['result']}"


def format_tool_outputs(outputs: list[dict[str, str]] | None) -> str | None:
    """Render digests as one line for MSG_CONTEXT (never contains '-->')."""
    if not outputs:
        return None
    return "; ".join(_render(entry) for entry in outputs).replace("-->", "->")
