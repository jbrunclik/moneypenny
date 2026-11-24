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
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel

from src.agent.flex import generate_on_flex
from src.agent.gemini_clients import shared_genai_client
from src.agent.prompt_texts.memory_review import (
    MEMORY_REVIEW_PROJECT_BLOCK,
    MEMORY_REVIEW_PROMPT,
    MEMORY_REVIEW_SHARED_RULE,
)
from src.agent.tools.memory import MemoryOp, apply_single_op
from src.config import Config
from src.db.models import db
from src.services.side_costs import record_side_cost
from src.utils.logging import get_logger
from src.utils.memory_ids import matching_memory_ids
from src.utils.service_tier import STANDARD, served_tier

if TYPE_CHECKING:
    from src.db.models import Memory, Project
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
    # The applied texts that went to the project's memory
    project_applied: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    # The Gemini tier that served the call (flex bills FLEX_PRICE_RATIO)
    service_tier: str = STANDARD
    model_ms: int = 0


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


def format_note(applied: list[str], project_name: str | None = None) -> str:
    """The reply's label: up to two items, then "and N more"; for a shared
    project's memory, which project's members now read it."""
    items = [_truncate(text) for text in applied[:_NOTE_MAX_ITEMS]]
    note = ", ".join(items)
    rest = len(applied) - len(items)
    note = f"{note}, and {rest} more" if rest > 0 else note
    if project_name:
        note += f" (in the {project_name} project - its members see it)"
    return note


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


def _project_block(project: Project | None) -> str:
    if project is None:
        return ""
    return MEMORY_REVIEW_PROJECT_BLOCK.format(
        name=" ".join(project.name.split()),
        shared_rule=MEMORY_REVIEW_SHARED_RULE if project.shared else "",
        memories=_memory_lines(db.list_project_memories(project.id), with_ids=True),
    )


def build_prompt(user_id: str, messages: list[Message], project: Project | None = None) -> str:
    # A random boundary the conversation cannot forge: text inside it is data
    boundary = f"conversation-{secrets.token_hex(8)}"
    return MEMORY_REVIEW_PROMPT.format(
        boundary=boundary,
        max_ops=Config.MEMORY_REVIEW_MAX_OPS,
        memories=_memory_lines(db.list_memories(user_id), with_ids=True),
        deleted=_memory_lines(db.list_deleted_memories(user_id), with_ids=False),
        transcript=_transcript(messages),
        project_block=_project_block(project),
    )


def _call_model(prompt: str) -> tuple[str, int, int, str]:
    """(text, input tokens, output tokens, the tier that served it)."""
    config = GenerateContentConfig(
        temperature=0.2,
        thinking_config=ThinkingConfig(thinking_level=ThinkingLevel.LOW),
    )
    model = Config.AI_ASSIST_MODEL
    if Config.MEMORY_REVIEW_FLEX:
        response = generate_on_flex(model, prompt, config, feature="memory_review")
    else:
        response = shared_genai_client().models.generate_content(
            model=model, contents=prompt, config=config
        )
    record_side_cost("memory_review", model, response)
    usage = getattr(response, "usage_metadata", None)
    tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
    # Thinking is billed at the output rate
    tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0) + int(
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    return response.text or "", tokens_in, tokens_out, served_tier(response)


def review_messages(
    user_id: str, conversation_id: str, messages: list[Message], project: Project | None = None
) -> ReviewResult:
    """Review a chat's recent messages and apply what is worth remembering.

    Synchronous (the trigger runs it on a daemon thread; evals call it directly).
    Raises when the model call fails - the caller logs and retries next time.
    """
    started = time.monotonic()
    text, tokens_in, tokens_out, tier = _call_model(build_prompt(user_id, messages, project))
    result = ReviewResult(
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        service_tier=tier,
        model_ms=round((time.monotonic() - started) * 1000),
    )
    project_id = project.id if project else None
    for op in parse_ops(text):
        to_project = _targets_project(op, project_id)
        applied = apply_single_op(user_id, conversation_id, op, project_id)
        if applied is not None:
            result.applied.append(applied)
            result.ops.append(op)
            if to_project:
                result.project_applied.append(applied)
    return result


def _targets_project(op: MemoryOp, project_id: str | None) -> bool:
    """Whether the op writes the project's memory: an add with the project
    scope, or a patch of one of the project's memories."""
    if project_id is None:
        return False
    if op.get("action") == "add":
        return op.get("scope") == "project"
    ref = str(op.get("id") or "").strip()
    project_ids = [m.id for m in db.list_project_memories(project_id)]
    return bool(ref) and len(matching_memory_ids(ref, project_ids)) == 1


def review_note(result: ReviewResult, project_name: str | None, shared: bool) -> str:
    """The reply's label: the personal items, then the project's - named as
    the project's (members read them) only in a shared project."""
    if not (project_name and shared and result.project_applied):
        return format_note(result.applied)
    personal = [text for text in result.applied if text not in result.project_applied]
    project_note = format_note(result.project_applied, project_name=project_name)
    return f"{format_note(personal)}; {project_note}" if personal else project_note
