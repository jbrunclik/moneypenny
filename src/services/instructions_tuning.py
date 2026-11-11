"""Custom instructions self-tuning: what a suggestion may change, and applying it.

The user's custom instructions (one prose text on ``users.custom_instructions``,
in every chat's system prompt) and the memories on their border. A suggestion -
from the Settings Review or a card in an ordinary chat - edits one passage of
the instructions, changes one memory, or does both as a move; only the user's
yes applies it, all or nothing (docs/superpowers/specs/
2026-11-11-instructions-self-tuning-design.md). Declined suggestions are
remembered per user so they are not offered again without newer evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date
from typing import Literal, Required, TypedDict, cast

from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Memory
from src.db.models.memory import (
    InstructionsWriteConflictError,
    MemoryWrite,
    MemoryWriteConflictError,
)
from src.services import program_setup as setup
from src.services.program_setup import EVIDENCE_MAX, DeclinedEntry, FieldChange
from src.utils.clock import local_today, to_local
from src.utils.logging import get_logger
from src.utils.threat_patterns import find_injection

logger = get_logger(__name__)

# The app's own per-user state (reserved: the model's kv_store cannot write it)
NAMESPACE = "instructions_tuning"
_DECLINED_KEY = "declined"
MEMORY_CATEGORIES = ("preference", "fact", "context", "goal")
_ITEM = re.compile(r"^\s*(Memory|Instructions):\s*(.+?)\s*$", re.DOTALL)

_INSTRUCTION_OPS = ("append", "replace", "remove")
_MEMORY_OPS = ("add", "patch", "delete")
_CHANGED_MEANWHILE = "That changed since this was suggested - nothing was changed."


class InstructionsChangeError(Exception):
    """A change that cannot apply now (gone, ambiguous, over a limit); says why."""


class InstructionsConflictError(InstructionsChangeError):
    """What the change touches was changed since it was suggested."""


class InstructionEdit(TypedDict, total=False):
    op: Required[Literal["append", "replace", "remove"]]
    old: str
    new: str


class MemoryEdit(TypedDict, total=False):
    op: Required[Literal["add", "patch", "delete"]]
    id: str
    content: str
    category: str
    # The memory's content when suggested (the collision snapshot)
    expected: str


class InstructionChange(TypedDict, total=False):
    instructions: InstructionEdit
    memory: MemoryEdit


class TuningState(TypedDict):
    instructions: str
    memories: list[Memory]


class Turn(TypedDict):
    day: date
    user: str
    # The assistant reply the user answered (a correction reads next to it)
    reply: str


def load_state(user_id: str) -> TuningState:
    user = db.get_user_by_id(user_id)
    return {
        "instructions": (user.custom_instructions or "") if user else "",
        "memories": db.list_memories(user_id),
    }


# --- validation ------------------------------------------------------------------


def _text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unsafe(text: str) -> str | None:
    reason = find_injection(text)
    return f"the text {reason}" if reason else None


def _instruction_edit(raw: object) -> InstructionEdit | str:
    if not isinstance(raw, Mapping):
        return "instructions must be an object"
    op = raw.get("op")
    if op not in _INSTRUCTION_OPS:
        return f"instructions.op must be one of {', '.join(_INSTRUCTION_OPS)}"
    old, new = _text(raw, "old"), _text(raw, "new")
    if op in ("replace", "remove") and old is None:
        return f"instructions.old is required for {op}"
    if op in ("append", "replace") and new is None:
        return f"instructions.new is required for {op}"
    if new is not None:
        if len(new) > Config.CUSTOM_INSTRUCTIONS_MAX_CHARS:
            return f"instructions.new is over {Config.CUSTOM_INSTRUCTIONS_MAX_CHARS} characters"
        if problem := _unsafe(new):
            return problem
    edit: InstructionEdit = {"op": cast("Literal['append', 'replace', 'remove']", op)}
    if old is not None and op != "append":
        edit["old"] = old
    if new is not None and op != "remove":
        edit["new"] = new
    return edit


def _memory_problem(
    op: object, memory_id: str | None, content: str | None, category: str | None
) -> str | None:
    """Why a memory edit's fields do not hold, or None."""
    categories = ", ".join(MEMORY_CATEGORIES)
    if op != "add" and memory_id is None:
        return f"memory.id is required for {op}"
    if op != "delete" and content is None:
        return f"memory.content is required for {op}"
    if (op == "add" or category is not None) and category not in MEMORY_CATEGORIES:
        return f"memory.category must be one of {categories}"
    if content is not None and len(content) > Config.MEMORY_MAX_ENTRY_CHARS:
        return f"memory.content is over {Config.MEMORY_MAX_ENTRY_CHARS} characters"
    return _unsafe(content) if content is not None else None


def _memory_edit(raw: object) -> MemoryEdit | str:
    if not isinstance(raw, Mapping):
        return "memory must be an object"
    op = raw.get("op")
    if op not in _MEMORY_OPS:
        return f"memory.op must be one of {', '.join(_MEMORY_OPS)}"
    memory_id, content, category = _text(raw, "id"), _text(raw, "content"), _text(raw, "category")
    if problem := _memory_problem(op, memory_id, content, category):
        return problem
    edit: MemoryEdit = {"op": cast("Literal['add', 'patch', 'delete']", op)}
    fields = {
        "id": memory_id if op != "add" else None,
        "content": content if op != "delete" else None,
        "category": category if op != "delete" else None,
        "expected": raw.get("expected") if op != "add" else None,
    }
    for key, value in fields.items():
        if isinstance(value, str):
            edit[key] = value  # type: ignore[literal-required]
    return edit


def validate_change(raw: object) -> InstructionChange | str:
    """The change in canonical form, or why it is not one (border rule included)."""
    if not isinstance(raw, Mapping):
        return "change must be an object"
    if extra := sorted(set(raw) - {"instructions", "memory"}):
        return f"unknown keys: {', '.join(map(str, extra))}"
    change: InstructionChange = {}
    if raw.get("instructions") is not None:
        edit = _instruction_edit(raw["instructions"])
        if isinstance(edit, str):
            return edit
        change["instructions"] = edit
    if raw.get("memory") is not None:
        memory = _memory_edit(raw["memory"])
        if isinstance(memory, str):
            return memory
        change["memory"] = memory
    if not change:
        return "change must touch the instructions, a memory, or both"
    # Memory suggestions stay at the instructions' border: a new memory only as
    # the other half of moving a passage out of the instructions
    instructions_op = change.get("instructions", {}).get("op")
    if change.get("memory", {}).get("op") == "add" and instructions_op not in ("remove", "replace"):
        return "a new memory is only suggested when moving a passage out of the instructions"
    return change


# --- reading the change against the current state ----------------------------------


def _memory(state: TuningState, memory_id: str | None) -> Memory | None:
    return next((m for m in state["memories"] if m.id == memory_id), None)


def _target_memory(state: TuningState, edit: MemoryEdit) -> Memory:
    """The memory a patch or delete acts on; raises when gone, protected or changed."""
    target = _memory(state, edit.get("id"))
    if target is None:
        raise InstructionsChangeError("That memory no longer exists - nothing was changed.")
    if target.protected:
        raise InstructionsChangeError("That memory is protected - only you can change it.")
    expected = edit.get("expected")
    if expected is not None and expected != target.content:
        raise InstructionsConflictError(_CHANGED_MEANWHILE)
    return target


def with_snapshot(state: TuningState, change: InstructionChange) -> InstructionChange:
    """The change carrying its memory's content as it is now (the collision check).
    The instructions need none: a passage edit applies while its passage is there."""
    memory = change.get("memory")
    if memory is None or memory.get("op") == "add":
        return change
    target = _memory(state, memory.get("id"))
    if target is None:
        return change
    return {**change, "memory": {**memory, "expected": target.content}}


def _edited_text(text: str, edit: InstructionEdit) -> str:
    """The instructions after one passage edit; raises when the passage is gone or ambiguous."""
    new = edit.get("new", "")
    if edit["op"] == "append":
        base = text.rstrip()
        return f"{base}\n\n{new}" if base else new
    old = edit.get("old", "")
    count = text.count(old)
    if count == 0:
        raise InstructionsConflictError(
            "That passage is no longer in your instructions - nothing was changed."
        )
    if count > 1:
        raise InstructionsChangeError(
            "That passage appears more than once in your instructions - nothing was changed."
        )
    if new:
        return text.replace(old, new, 1)
    at = text.index(old)
    return _joined(text[:at], text[at + len(old) :])


def _joined(before: str, after: str) -> str:
    """Close the gap a removed passage left, touching only its two sides (the
    rest of the text stays exactly as the user wrote it)."""
    left, right = before.rstrip(" \t"), after.lstrip(" \t")
    if not left:
        return right.lstrip("\n")
    if not right:
        return left.rstrip("\n")
    left_breaks = len(left) - len(left.rstrip("\n"))
    right_breaks = len(right) - len(right.lstrip("\n"))
    if left_breaks or right_breaks:
        # A removed line or paragraph: keep the larger break that was there
        return left.rstrip("\n") + "\n" * max(left_breaks, right_breaks) + right.lstrip("\n")
    return f"{left} {right}"


def _memory_label(category: str | None) -> str:
    return f"Memory ({category})" if category else "Memory"


def field_changes(state: TuningState, change: InstructionChange) -> list[FieldChange]:
    """What changes, one row per part: the passage, the memory. Raises when stale."""
    rows: list[FieldChange] = []
    if (edit := change.get("instructions")) is not None:
        if edit["op"] != "append":
            _edited_text(state["instructions"], edit)  # gone / ambiguous -> raises
        rows.append(
            {"field": "Instructions", "before": edit.get("old", ""), "after": edit.get("new", "")}
        )
    if (memory := change.get("memory")) is not None:
        if memory["op"] == "add":
            before, category = "", memory.get("category")
        else:
            target = _target_memory(state, memory)
            before, category = target.content, memory.get("category") or target.category
        after = "" if memory["op"] == "delete" else memory.get("content", "")
        rows.append({"field": _memory_label(category), "before": before, "after": after})
    return rows


def describe_change(state: TuningState, change: InstructionChange) -> tuple[str, str]:
    """Before / after as "Field: value" lines (the card's and the Review's text form)."""
    rows = field_changes(state, change)
    before = "\n".join(f"{r['field']}: {r['before']}" for r in rows if r["before"])
    after = "\n".join(f"{r['field']}: {r['after']}" for r in rows if r["after"])
    return before or "(none)", after or "(removed)"


# --- evidence ---------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


# A quote shorter than this must be the whole item (final review: "Memory: e"
# matched any memory with an e in it)
_MIN_QUOTE_CHARS = 12


def _quotes(needle: str, text: str) -> bool:
    return needle in text and (len(needle) >= _MIN_QUOTE_CHARS or needle == text)


def _cited(kind: str, quoted: str, state: TuningState) -> set[str] | None:
    """What a "Memory: ..." / "Instructions: ..." item quotes now: the memory ids
    it matches, {"instructions"} for the text, or None when it matches nothing."""
    needle = _norm(quoted.strip("\"'“”‘’ "))
    if not needle:
        return None
    if kind == "Instructions":
        return {"instructions"} if _quotes(needle, _norm(state["instructions"])) else None
    ids = {m.id for m in state["memories"] if _quotes(needle, _norm(m.content))}
    return ids or None


def needs_turn(change: InstructionChange) -> bool:
    """New wording or a removed rule needs a dated turn where the user asked for
    it; a move and a duplicate removal rest on the items themselves."""
    if "instructions" in change and "memory" in change:
        return False
    if "instructions" in change:
        return True
    return change.get("memory", {}).get("op") == "patch"


def _grounding_problem(change: InstructionChange, cited: set[str], dated: int) -> str | None:
    """Clean-up must name what it acts on: a move or a removed memory cites that
    memory, and a removed memory also what it duplicates (final review I2)."""
    memory: Mapping[str, object] = change.get("memory") or {}
    target = memory.get("id")
    if memory.get("op") not in ("delete", "patch") or target is None:
        return None
    if target not in cited:
        return "Quote the memory this changes as 'Memory: <its text>'."
    alone = "instructions" not in change and memory.get("op") == "delete"
    if alone and not (cited - {target}) and not dated:
        return "Quote what this memory duplicates or contradicts ('Instructions: ...' or 'Memory: ...')."
    return None


def evidence_problem(
    evidence: list[str], known_days: set[date], state: TuningState, change: InstructionChange
) -> str | None:
    """Why the evidence does not hold, or None: 1-5 items, each a dated turn on a
    day the user wrote ("YYYY-MM-DD: ...") or a quote of a current item
    ("Memory: ..." / "Instructions: ..."); new wording needs a dated turn, and
    clean-up names what it acts on."""
    items = [e.strip() for e in evidence if e.strip()]
    if not 1 <= len(items) <= EVIDENCE_MAX:
        return f"Give 1-{EVIDENCE_MAX} evidence items."
    dated, cited = 0, set[str]()
    for item in items:
        days = setup.evidence_dates([item])
        if days:
            if days[0] not in known_days:
                return f"Cite only days the user wrote on - not {days[0].isoformat()}."
            dated += 1
            continue
        match = _ITEM.match(item)
        found = _cited(match.group(1), match.group(2), state) if match else None
        if found is None:
            return (
                "Each evidence item is 'YYYY-MM-DD: what the user said' or quotes a current "
                "item as 'Memory: <its text>' / 'Instructions: <the passage>'."
            )
        cited |= found
    if needs_turn(change) and dated == 0:
        return "New wording needs at least one dated turn where the user asked for it."
    return _grounding_problem(change, cited, dated)


# --- fingerprints and declines -----------------------------------------------------


def fingerprint(change: InstructionChange) -> str:
    """The same suggestion has the same fingerprint (case and spacing ignored)."""
    edit: Mapping[str, object] = change.get("instructions") or {}
    memory: Mapping[str, object] = change.get("memory") or {}
    parts = (
        edit.get("op", ""),
        edit.get("old", ""),
        edit.get("new", ""),
        memory.get("op", ""),
        memory.get("id", ""),
        memory.get("content", ""),
    )
    raw = "|".join(_norm(str(p)) for p in parts)
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def declined(user_id: str) -> list[DeclinedEntry]:
    """The suggestions the user declined, oldest first."""
    return setup.parse_declined(db.kv_get(user_id, NAMESPACE, _DECLINED_KEY))


def record_decline(user_id: str, change: InstructionChange, summary: str) -> None:
    """Remember a declined suggestion (the newest SETUP_DECLINED_MAX are kept)."""
    entry: DeclinedEntry = {
        "fingerprint": fingerprint(change),
        "summary": summary[:200],
        "declined_at": local_today().isoformat(),
    }
    entries = [*declined(user_id), entry][-Config.SETUP_DECLINED_MAX :]
    db.kv_set(user_id, NAMESPACE, _DECLINED_KEY, setup.dump_declined(entries))


def blocked_by_decline(
    entries: list[DeclinedEntry], change: InstructionChange, evidence: list[str]
) -> bool:
    """True when this suggestion was declined and no evidence is newer than the decline."""
    mark = fingerprint(change)
    declines = [date.fromisoformat(e["declined_at"]) for e in entries if e["fingerprint"] == mark]
    if not declines:
        return False
    newest = max(declines)
    return not any(d > newest for d in setup.evidence_dates(evidence))


# --- applying ---------------------------------------------------------------------


def _memory_write(state: TuningState, edit: MemoryEdit) -> MemoryWrite:
    if edit["op"] == "add":
        if len(state["memories"]) >= Config.MEMORY_MAX_ENTRIES:
            raise InstructionsChangeError("Your memory bank is full - nothing was changed.")
        return MemoryWrite("add", content=edit.get("content"), category=edit.get("category"))
    target = _target_memory(state, edit)
    if edit["op"] == "delete":
        # The content it was shown with is checked again inside the transaction
        return MemoryWrite("delete", memory_id=target.id, expected=target.content)
    return MemoryWrite(
        "patch",
        memory_id=target.id,
        content=edit.get("content"),
        expected=target.content,
        category=edit.get("category"),
    )


def _sync_embedding(user_id: str, write: MemoryWrite, new_id: str | None) -> None:
    """Keep memory search's vectors in step, as manage_memory does (best effort:
    the change already landed)."""
    try:
        if write.action == "delete":
            db.delete_embedding("memory", str(write.memory_id))
        else:
            ref = new_id if write.action == "add" else write.memory_id
            db.embed_and_store_async(user_id, "memory", str(ref), str(write.content))
    except Exception:
        logger.warning("Memory embedding update failed after commit", exc_info=True)


def already_there(state: TuningState, change: InstructionChange) -> str | None:
    """Why the change would add what is already there, or None (final review:
    a second copy of a rule made later edits of it ambiguous)."""
    edit = change.get("instructions")
    new = edit.get("new") if edit is not None else None
    if new and _norm(new) in _norm(state["instructions"]):
        return "That's already in your instructions - nothing was changed."
    memory = change.get("memory")
    content = memory.get("content") if memory is not None and memory["op"] == "add" else None
    known = [_norm(m.content) for m in state["memories"]]
    if content and any(_norm(content) in k for k in known):
        return "That's already remembered - nothing was changed."
    return None


def target_name(change: InstructionChange) -> str:
    if "instructions" in change and "memory" in change:
        return "move"
    return "instructions" if "instructions" in change else "memory"


def apply_change(user_id: str, raw: Mapping[str, object]) -> str:
    """Apply an approved change, all or nothing; returns the instructions as they
    now are. Raises InstructionsChangeError (InstructionsConflictError when
    something it touches changed since it was suggested)."""
    change = validate_change(raw)
    if isinstance(change, str):
        raise InstructionsChangeError(change)
    state = load_state(user_id)
    if duplicate := already_there(state, change):
        raise InstructionsChangeError(duplicate)
    text = state["instructions"]
    if (edit := change.get("instructions")) is not None:
        text = _edited_text(text, edit)
    if len(text) > Config.CUSTOM_INSTRUCTIONS_MAX_CHARS:
        raise InstructionsChangeError(
            f"Your instructions would be over {Config.CUSTOM_INSTRUCTIONS_MAX_CHARS} characters "
            "- nothing was changed."
        )
    writes = [_memory_write(state, change["memory"])] if "memory" in change else []
    try:
        new_ids = db.apply_instructions_change(user_id, state["instructions"], text or None, writes)
    except (InstructionsWriteConflictError, MemoryWriteConflictError) as e:
        raise InstructionsConflictError(_CHANGED_MEANWHILE) from e
    for write, new_id in zip(writes, new_ids, strict=True):
        _sync_embedding(user_id, write, new_id)
    logger.info(
        "Instructions changed",
        extra={"user_id": user_id, "target": target_name(change), "length": len(text)},
    )
    return text


def log_resolved(
    source: Literal["card", "review"], outcome: str, change: InstructionChange
) -> None:
    """One line per answered suggestion (the regular review counts them, rule A8)."""
    logger.info(
        "Instructions suggestion resolved",
        extra={"source": source, "outcome": outcome, "target": target_name(change)},
    )


# --- what the review reads ---------------------------------------------------------


def ordinary_turns(user_id: str, limit: int) -> list[Turn]:
    """The user's latest messages in ordinary chats (oldest first), each with the
    reply it answered."""
    rows = db.recent_ordinary_user_turns(user_id, limit)
    turns: list[Turn] = [
        {"day": to_local(at).date(), "user": text, "reply": reply or ""} for at, text, reply in rows
    ]
    return list(reversed(turns))
