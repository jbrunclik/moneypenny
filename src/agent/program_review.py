"""The setup Review the Quick actions sheet asks for.

One structured model call reads the program's setup (quick actions, its
standing instructions), the suggestions the user declined, and the program
chat's latest messages, and returns suggested changes - each with the dated
turns it rests on. Every suggestion is validated on its own (allowed keys,
quick action limits, dated evidence, not declined without newer evidence);
the invalid ones are dropped, the rest shown in the sheet where the user
accepts or rejects each (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
Nothing here touches the chat.
"""

from __future__ import annotations

import json
import time
import unicodedata
from datetime import date
from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import BaseModel, Field

from src.agent.gemini_clients import chat_model
from src.config import Config
from src.db.models import db
from src.db.models.programs import PROGRAM_FEATURES
from src.services import program_setup as setup
from src.services.costs import calculate_token_cost
from src.services.program_setup import ProgramRef, SetupChange, SetupChangeError
from src.utils.clock import to_local
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Conversation

logger = get_logger(__name__)


class ReviewItem(BaseModel):
    """One suggestion as the model returns it (flat: Gemini handles open objects poorly)."""

    target: Literal["quick_action", "instruction"]
    op: Literal["add", "edit", "remove"] | None = Field(None, description="quick_action only")
    action_id: str | None = Field(None, description="the quick action's id, for edit/remove")
    emoji: str | None = None
    label: str | None = None
    body: str | None = None
    fields: list[str] = Field(default_factory=list)
    key: str | None = Field(None, description="instruction only: which key")
    patch_json: str | None = Field(
        None, description='instruction only: a JSON merge patch as a string, e.g. {"z2_watts": 125}'
    )
    text: str | None = Field(None, description="instruction only: a whole new prose value")
    summary: str = Field(description="one short line for the user, in their language")
    evidence: list[str] = Field(
        default_factory=list,
        description="1-5 items, each 'YYYY-MM-DD: what was said' from the turns",
    )


class ReviewOutput(BaseModel):
    suggestions: list[ReviewItem] = Field(default_factory=list)


class Suggestion(TypedDict):
    id: str
    change: SetupChange
    summary: str
    before: str
    after: str
    # What changes, field by field (the sheet shows these rows)
    changes: list[setup.FieldChange]
    evidence: list[str]


_PROMPT = """You review the setup of a {namespace} coaching program the user chats with.
The setup is its quick actions (one-tap saved prompts) and its standing instructions.
Suggest changes ONLY where the turns below show they would help: a request the user
types again and again (a quick action would save it), a quick action whose prompt
or fields don't match how it is used, a quick action never used, an instruction
the user corrected. Every suggestion must cite 1-5 turns as "YYYY-MM-DD: what was
said". No evidence, no suggestion - returning no suggestions is a good answer.
Never re-suggest something the user declined unless a turn after the decline
supports it. Labels, bodies and summaries in the user's language.

Instruction keys you may change: {keys}. A JSON value changes by a merge patch
(patch_json; null removes a field); a prose value by text.

Quick actions:
{quick_actions}

Standing instructions:
{instructions}

Declined before:
{declined}

Latest turns (oldest first):
{turns}"""


def _program_chat(user_id: str, ref: ProgramRef) -> Conversation | None:
    column = PROGRAM_FEATURES[ref.namespace].program_column
    chats = db.list_program_conversations(ref.namespace, user_id)
    return next((c for c in chats if getattr(c, column) == ref.program_id), None)


def _ascii_id(text: str) -> str:
    """A quick action id from a label: ASCII letters, digits and - only
    ("Plán týdne" -> "plan-tydne"; final review: Czech adds were all dropped)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = "-".join(folded.casefold().split())
    return "".join(ch for ch in words if ch.isalnum() or ch in "-_")[:32] or "action"


def _turns(user_id: str, ref: ProgramRef) -> str:
    conv = _program_chat(user_id, ref)
    if conv is None:
        return "(no turns yet)"
    messages, _ = db.get_messages_paginated(conv.id, limit=Config.PROGRAM_REVIEW_MESSAGES)
    lines = [
        f"{to_local(m.created_at).date().isoformat()} {m.role.value}: "
        f"{' '.join(m.content.split())[: Config.PROGRAM_REVIEW_MESSAGE_CHARS]}"
        for m in messages
        if m.content.strip()
    ]
    return "\n".join(lines) or "(no turns yet)"


def _prompt(user_id: str, ref: ProgramRef) -> str:
    current = setup.load_setup(user_id, ref)
    declined = setup.declined(user_id, ref)
    return _PROMPT.format(
        namespace=ref.namespace,
        keys=", ".join(setup.INSTRUCTION_KEYS.get(ref.namespace, ())),
        quick_actions=json.dumps(current["quick_actions"], ensure_ascii=False, indent=1),
        instructions=json.dumps(current["instructions"], ensure_ascii=False, indent=1),
        declined="\n".join(f"- {e['declined_at']}: {e['summary']}" for e in declined) or "(none)",
        turns=_turns(user_id, ref),
    )


def _invoke(prompt: str) -> tuple[ReviewOutput, dict[str, int]]:
    """The one model call: the parsed suggestions and the token usage."""
    model = chat_model(Config.PROGRAM_REVIEW_MODEL, timeout=Config.PROGRAM_REVIEW_TIMEOUT_SECONDS)
    out = model.with_structured_output(ReviewOutput, include_raw=True).invoke(prompt)
    parsed = out.get("parsed") if isinstance(out, dict) else None
    raw = out.get("raw") if isinstance(out, dict) else None
    metadata = getattr(raw, "usage_metadata", None) or {}
    usage = {
        "input_tokens": int(metadata.get("input_tokens", 0)),
        "output_tokens": int(metadata.get("output_tokens", 0)),
    }
    return (parsed if isinstance(parsed, ReviewOutput) else ReviewOutput()), usage


def _change(item: ReviewItem) -> dict[str, object] | None:
    """The item as a SetupChange draft (None when its patch is not a JSON object)."""
    if item.target == "instruction":
        draft: dict[str, object] = {"target": "instruction", "key": item.key}
        if item.text is not None:
            draft["text"] = item.text
        else:
            try:
                patch = json.loads(item.patch_json or "")
            except json.JSONDecodeError:
                return None
            draft["patch"] = patch
        return draft
    draft = {"target": "quick_action", "op": item.op, "action_id": item.action_id}
    if item.op != "remove":
        draft["action"] = {
            "id": _ascii_id(item.action_id or item.label or "action"),
            "emoji": item.emoji or "✨",
            "label": item.label or "",
            "body": item.body or "",
            "fields": list(item.fields),
        }
    return {k: v for k, v in draft.items() if v is not None}


def _suggestion(
    user_id: str,
    ref: ProgramRef,
    item: ReviewItem,
    current: setup.ProgramSetup,
    known_days: set[date],
) -> Suggestion | None:
    draft = _change(item)
    checked = setup.validate_change(ref.namespace, draft) if draft is not None else "bad patch"
    evidence = [e.strip() for e in item.evidence if e.strip()]
    if isinstance(checked, str) or setup.evidence_problem(evidence, known_days):
        return None
    if setup.blocked_by_decline(setup.declined(user_id, ref), checked, evidence):
        return None
    try:
        before, after = setup.describe_change(current, checked)
    except SetupChangeError:
        return None
    return {
        "id": setup.fingerprint(checked),
        # Accepting later applies only if the target is still what was shown
        "change": setup.with_snapshot(current, checked),
        "summary": item.summary.strip()[:200],
        "before": before,
        "after": after,
        "changes": setup.field_changes(current, checked),
        "evidence": evidence,
    }


def refresh_suggestion(
    user_id: str, ref: ProgramRef, change: SetupChange, summary: str, evidence: list[str]
) -> Suggestion | None:
    """The same suggestion against the setup as it is now (a field it touches
    changed since the review): new before/after and snapshot, or None when it no
    longer applies (its target is gone, or it now changes nothing)."""
    current = setup.load_setup(user_id, ref)
    clean = {k: v for k, v in change.items() if k != "expect"}
    checked = setup.validate_change(ref.namespace, clean)
    if isinstance(checked, str):
        return None
    try:
        rows = setup.field_changes(current, checked)
        before, after = setup.describe_change(current, checked)
    except SetupChangeError:
        return None
    if not rows:
        return None
    return {
        "id": setup.fingerprint(checked),
        "change": setup.with_snapshot(current, checked),
        "summary": summary,
        "before": before,
        "after": after,
        "changes": rows,
        "evidence": evidence,
    }


def review_setup(user_id: str, ref: ProgramRef) -> list[Suggestion]:
    """Suggested changes to the program's setup, each valid on its own; [] = nothing to change."""
    started = time.monotonic()
    output, usage = _invoke(_prompt(user_id, ref))
    current = setup.load_setup(user_id, ref)
    chat = _program_chat(user_id, ref)
    # Evidence must cite days the user really wrote in the program chat
    known_days = setup.chat_dates(chat.id) if chat is not None else set()
    suggestions: list[Suggestion] = []
    seen: set[str] = set()
    for item in output.suggestions:
        found = _suggestion(user_id, ref, item, current, known_days)
        if found is not None and found["id"] not in seen:
            seen.add(found["id"])
            suggestions.append(found)
    suggestions = suggestions[: Config.PROGRAM_REVIEW_MAX_SUGGESTIONS]
    cost = calculate_token_cost(
        Config.PROGRAM_REVIEW_MODEL, usage["input_tokens"], usage["output_tokens"]
    )
    logger.info(
        "Setup review",
        extra={
            "user_id": user_id,
            "namespace": ref.namespace,
            "returned": len(output.suggestions),
            "suggestions": len(suggestions),
            "cost_usd": round(cost, 5),
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return suggestions
