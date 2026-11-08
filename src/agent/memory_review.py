"""The background memory review: a cheap pass that adds or patches memories.

Every few user turns (api/helpers/memory_review_trigger.py) the recent turns of
a chat are reread by the fast model, which may return a few add/patch
operations. Each is applied on its own through the memory tool's guards, so one
rejected op does not block the rest. Conservative by design: see
docs/superpowers/specs/2026-11-08-background-memory-review-design.md.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel

from src.agent.gemini_clients import shared_genai_client
from src.agent.prompt_texts.memory_review import MEMORY_REVIEW_PROMPT
from src.agent.tools.memory import MemoryOp, apply_single_op
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Memory
    from src.db.models.dataclasses import Message

logger = get_logger(__name__)

_MESSAGE_MAX_CHARS = 2000
_NOTE_ITEM_MAX_CHARS = 60
_NOTE_MAX_ITEMS = 2
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class ReviewResult:
    """What one pass applied (new memory texts and their ops) and its tokens."""

    applied: list[str] = field(default_factory=list)
    ops: list[MemoryOp] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def parse_ops(text: str) -> list[MemoryOp]:
    """The add/patch ops of the model's reply, capped; [] when unparseable."""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    ops = [
        cast(MemoryOp, item)
        for item in data
        if isinstance(item, dict) and item.get("action") in ("add", "patch")
    ]
    return ops[: Config.MEMORY_REVIEW_MAX_OPS]


def format_note(applied: list[str]) -> str:
    """The reply's label: up to two items, then "and N more"."""
    items = [_truncate(text) for text in applied[:_NOTE_MAX_ITEMS]]
    note = ", ".join(items)
    rest = len(applied) - len(items)
    return f"{note}, and {rest} more" if rest > 0 else note


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= _NOTE_ITEM_MAX_CHARS:
        return text
    return text[: _NOTE_ITEM_MAX_CHARS - 1] + "…"


def _memory_lines(memories: list[Memory], with_ids: bool) -> str:
    if not memories:
        return "(none)"
    if with_ids:
        return "\n".join(f"{m.id} | {m.category or 'fact'} | {m.content}" for m in memories)
    return "\n".join(f"- {m.content}" for m in memories)


def _transcript(messages: list[Message]) -> str:
    """Message text only: tool outputs (fetched pages, files) are left out."""
    lines = []
    for message in messages:
        role = str(message.role)
        content = str(message.content or "").strip()[:_MESSAGE_MAX_CHARS]
        if content:
            lines.append(f"{role.capitalize()}: {content}")
    return "\n\n".join(lines)


def build_prompt(user_id: str, messages: list[Message]) -> str:
    # A random boundary the conversation cannot forge: text inside it is data
    boundary = f"conversation-{secrets.token_hex(8)}"
    return MEMORY_REVIEW_PROMPT.format(
        boundary=boundary,
        max_ops=Config.MEMORY_REVIEW_MAX_OPS,
        memories=_memory_lines(db.list_memories(user_id), with_ids=True),
        deleted=_memory_lines(db.list_deleted_memories(user_id), with_ids=False),
        transcript=_transcript(messages),
    )


def _call_model(prompt: str) -> tuple[str, int, int]:
    response = shared_genai_client().models.generate_content(
        model=Config.AI_ASSIST_MODEL,
        contents=prompt,
        config=GenerateContentConfig(
            temperature=0.2,
            thinking_config=ThinkingConfig(thinking_level=ThinkingLevel.LOW),
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
    tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
    return response.text or "", tokens_in, tokens_out


def review_messages(user_id: str, conversation_id: str, messages: list[Message]) -> ReviewResult:
    """Review a chat's recent messages and apply what is worth remembering.

    Synchronous (the trigger runs it on a daemon thread; evals call it directly).
    Raises when the model call fails - the caller logs and retries next time.
    """
    text, tokens_in, tokens_out = _call_model(build_prompt(user_id, messages))
    result = ReviewResult(input_tokens=tokens_in, output_tokens=tokens_out)
    for op in parse_ops(text):
        applied = apply_single_op(user_id, conversation_id, op)
        if applied is not None:
            result.applied.append(applied)
            result.ops.append(op)
    return result
