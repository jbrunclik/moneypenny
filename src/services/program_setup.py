"""A program's setup: what the coach may propose changes to, and applying them.

A program chat (sports, language) works from two things the user rarely edits
by hand: its quick actions (inside the program object in the namespace's
``programs`` K/V list) and its standing instructions (the program's
``{program_id}:<key>`` K/V entries, only the keys in INSTRUCTION_KEYS). The
coach proposes changes - on a card in the chat or in the Quick actions
sheet's Review - and only the user's yes applies them (docs/superpowers/
specs/2026-11-11-program-self-tuning-design.md). Declined suggestions are
remembered per program so they are not offered again without new evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypedDict, cast

from src.config import Config
from src.db.models import db
from src.db.models.programs import PROGRAM_FEATURES
from src.utils.clock import local_today, to_local
from src.utils.json_merge import merge_patch
from src.utils.logging import get_logger

logger = get_logger(__name__)

# The keys a change may touch: the ones that steer the coach, not the data it
# logs (progress, vocabulary, stats... - edits there would be noise)
INSTRUCTION_KEYS: dict[str, tuple[str, ...]] = {
    "sports": ("goals", "preferences", "routine"),
    "language": ("profile", "grammar"),
}

QUICK_ACTIONS_MAX_PER_PROGRAM = 12
QUICK_ACTION_MAX_FIELDS = 6
QUICK_ACTION_ID_MAX_CHARS = 32
QUICK_ACTION_EMOJI_MAX_CHARS = 10
QUICK_ACTION_LABEL_MAX_CHARS = 40
QUICK_ACTION_BODY_MAX_CHARS = 2000
QUICK_ACTION_FIELD_MAX_CHARS = 40
_ACTION_ID = re.compile(r"^[A-Za-z0-9_-]+$")

QUICK_ACTION_DEFAULTS: dict[str, list[dict[str, object]]] = {
    "sports": [
        {
            "id": "plan-today",
            "emoji": "\U0001f4cb",
            "label": "Plan today",
            "body": (
                "Plan today's session. Check my Garmin readiness first and tell me "
                "which numbers drove the intensity call."
            ),
            "fields": [],
        },
        {
            "id": "log-review",
            "emoji": "\U0001f4ca",
            "label": "Log & review",
            "body": (
                "Assess today's session against the plan and stored progress, note any "
                "PRs, update the Garmin workouts for the next session, and prepare the "
                "overview table."
            ),
            "fields": ["Results"],
        },
    ],
    "language": [
        {
            "id": "new-lesson",
            "emoji": "\U0001f4d6",
            "label": "New lesson",
            "body": "Start a new lesson.",
            "fields": [],
        },
        {
            "id": "quiz-me",
            "emoji": "\U0001f9e0",
            "label": "Quiz me",
            "body": "Quiz me on the vocabulary from the last two lessons.",
            "fields": [],
        },
    ],
}

# Not under the {program_id}: prefix: program_context.py puts every key there into
# the chat's prompt each turn (final review, Nov 11 2026)
_DECLINED_KEY_PREFIX = "setup_declined:"
EVIDENCE_MAX = 5
# How far back the chat's own dates are read to check evidence against
_CHAT_DATES_MESSAGES = 200
_DATE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


class SetupChangeError(Exception):
    """A change that cannot apply now (stale target, over a limit); says why."""


@dataclass(frozen=True)
class ProgramRef:
    namespace: str
    program_id: str


class SetupChange(TypedDict, total=False):
    target: Literal["quick_action", "instruction"]
    # quick_action
    op: Literal["add", "edit", "remove"]
    action_id: str
    action: dict[str, object]
    # instruction: a JSON merge patch (None removes a field), or a whole prose value
    key: str
    patch: dict[str, object]
    text: str
    # A digest of the target as it was when suggested: a change made since
    # (by hand, or by the coach on request) makes the suggestion stale
    expect: str


class ProgramSetup(TypedDict):
    quick_actions: list[dict[str, object]]
    instructions: dict[str, object]


class DeclinedEntry(TypedDict):
    fingerprint: str
    summary: str
    declined_at: str


# --- quick actions --------------------------------------------------------------


def quick_action_problem(raw: object) -> str | None:
    """Why `raw` is not a valid quick action, or None (the API schema's limits)."""
    if not isinstance(raw, Mapping):
        return "a quick action is an object"
    checks: list[tuple[str, int, int]] = [
        ("id", 1, QUICK_ACTION_ID_MAX_CHARS),
        ("emoji", 1, QUICK_ACTION_EMOJI_MAX_CHARS),
        ("label", 1, QUICK_ACTION_LABEL_MAX_CHARS),
        ("body", 1, QUICK_ACTION_BODY_MAX_CHARS),
    ]
    for name, low, high in checks:
        value = raw.get(name)
        if not isinstance(value, str) or not low <= len(value.strip()) <= high:
            return f"{name} must be {low}-{high} characters"
    if not _ACTION_ID.match(str(raw["id"])):
        return "id may hold only letters, digits, - and _"
    fields = raw.get("fields", [])
    if not isinstance(fields, list) or len(fields) > QUICK_ACTION_MAX_FIELDS:
        return f"at most {QUICK_ACTION_MAX_FIELDS} fields"
    if any(
        not isinstance(f, str) or not 1 <= len(f.strip()) <= QUICK_ACTION_FIELD_MAX_CHARS
        for f in fields
    ):
        return f"each field label must be 1-{QUICK_ACTION_FIELD_MAX_CHARS} characters"
    return None


def _clean_action(raw: Mapping[str, object]) -> dict[str, object]:
    fields = raw.get("fields", [])
    return {
        "id": str(raw["id"]),
        "emoji": str(raw["emoji"]),
        "label": str(raw["label"]),
        "body": str(raw["body"]),
        "fields": [str(f).strip() for f in fields] if isinstance(fields, list) else [],
    }


def sanitize_quick_actions(raw: object) -> list[dict[str, object]]:
    """Valid stored actions, dropping malformed entries instead of failing."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, object]] = []
    for entry in raw:
        if quick_action_problem(entry) is not None:
            logger.warning("Dropping malformed quick action", extra={"entry": repr(entry)[:200]})
            continue
        result.append(_clean_action(cast("Mapping[str, object]", entry)))
        if len(result) >= QUICK_ACTIONS_MAX_PER_PROGRAM:
            break
    return result


def resolve_quick_actions(program: Mapping[str, object], namespace: str) -> list[dict[str, object]]:
    """A program's actions: its stored list (sanitized), or the namespace defaults."""
    if "quick_actions" not in program:
        return [dict(a) for a in QUICK_ACTION_DEFAULTS.get(namespace, [])]
    return sanitize_quick_actions(program["quick_actions"])


# --- reading ---------------------------------------------------------------------


def program_for_conversation(conversation_id: str, user_id: str) -> ProgramRef | None:
    """The program a chat belongs to, or None for any other chat."""
    conv = db.get_conversation(conversation_id, user_id)
    if conv is None:
        return None
    for namespace, feature in PROGRAM_FEATURES.items():
        program_id = getattr(conv, feature.program_column, None)
        if getattr(conv, feature.flag_column, False) and isinstance(program_id, str) and program_id:
            return ProgramRef(namespace, program_id)
    return None


def _programs(user_id: str, namespace: str) -> list[dict[str, object]]:
    try:
        data = json.loads(db.kv_get(user_id, namespace, "programs") or "[]")
    except json.JSONDecodeError, TypeError:
        return []
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def _program(programs: list[dict[str, object]], ref: ProgramRef) -> dict[str, object]:
    program = next((p for p in programs if p.get("id") == ref.program_id), None)
    if program is None:
        raise SetupChangeError("That program no longer exists.")
    return program


def _instruction(user_id: str, ref: ProgramRef, key: str) -> object:
    raw = db.kv_get(user_id, ref.namespace, f"{ref.program_id}:{key}")
    if raw is None:
        return None
    try:
        return cast("object", json.loads(raw))
    except json.JSONDecodeError:
        return raw


def load_setup(user_id: str, ref: ProgramRef) -> ProgramSetup:
    """The program's quick actions and its instruction keys' values."""
    program = _program(_programs(user_id, ref.namespace), ref)
    return {
        "quick_actions": resolve_quick_actions(program, ref.namespace),
        "instructions": {
            key: _instruction(user_id, ref, key) for key in INSTRUCTION_KEYS.get(ref.namespace, ())
        },
    }


# --- validating and describing ----------------------------------------------------------


def _quick_action_change(change: SetupChange) -> str | None:
    op = change.get("op")
    if op not in ("add", "edit", "remove"):
        return "op must be add, edit or remove"
    if op != "add" and not change.get("action_id"):
        return f"{op} needs action_id"
    if op != "remove":
        return quick_action_problem(change.get("action"))
    return None


def _instruction_change(namespace: str, change: SetupChange) -> str | None:
    allowed = INSTRUCTION_KEYS.get(namespace, ())
    if change.get("key") not in allowed:
        return f"only these instruction keys may change: {', '.join(allowed)}"
    has_patch, has_text = isinstance(change.get("patch"), dict), isinstance(change.get("text"), str)
    if has_patch == has_text:
        return "an instruction change has either a patch (object) or a text"
    return None


def validate_change(namespace: str, change: Mapping[str, object]) -> SetupChange | str:
    """The change, re-checked (known fields, valid values); or why not."""
    clean = cast(
        "SetupChange", {k: v for k, v in change.items() if k in SetupChange.__annotations__}
    )
    target = clean.get("target")
    if target == "quick_action":
        problem = _quick_action_change(clean)
    elif target == "instruction":
        problem = _instruction_change(namespace, clean)
    else:
        problem = "target must be quick_action or instruction"
    return problem if problem else clean


def _action_text(action: Mapping[str, object] | None) -> str:
    if not action:
        return "(none)"
    fields = action.get("fields") or []
    extra = (
        f" [fields: {', '.join(str(f) for f in fields)}]"
        if isinstance(fields, list) and fields
        else ""
    )
    return f"{action.get('emoji', '')} {action.get('label', '')}: '{action.get('body', '')}'{extra}".strip()


def _value_text(value: object) -> str:
    if value is None:
        return "(none)"
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _after_instruction(current: object, change: SetupChange) -> object:
    if "text" in change:
        return change["text"]
    if current is not None and not isinstance(current, dict):
        raise SetupChangeError("That instruction is prose: replace it with a text, not a patch.")
    return merge_patch(dict(current or {}), dict(change.get("patch") or {}))


def describe_change(setup: ProgramSetup, change: SetupChange) -> tuple[str, str]:
    """(before, after) as short human text."""
    if change.get("target") == "instruction":
        current = setup["instructions"].get(str(change.get("key")))
        return _value_text(current), _value_text(_after_instruction(current, change))
    actions = {str(a["id"]): a for a in setup["quick_actions"]}
    old = actions.get(str(change.get("action_id"))) if change.get("op") != "add" else None
    new = None if change.get("op") == "remove" else change.get("action")
    return _action_text(old), _action_text(new)


# --- applying -----------------------------------------------------------------


def _apply_quick_action(user_id: str, ref: ProgramRef, change: SetupChange) -> str:
    programs = _programs(user_id, ref.namespace)
    program = _program(programs, ref)
    actions = resolve_quick_actions(program, ref.namespace)
    op = change["op"]
    if op == "add":
        if len(actions) >= QUICK_ACTIONS_MAX_PER_PROGRAM:
            raise SetupChangeError(
                f"A program has at most {QUICK_ACTIONS_MAX_PER_PROGRAM} quick actions."
            )
        new = _clean_action(change["action"])
        if any(a["id"] == new["id"] for a in actions):
            new["id"] = f"{new['id']}-{len(actions) + 1}"
        actions.append(new)
        line = f"Added the quick action {new['label']}."
    else:
        index = next((i for i, a in enumerate(actions) if a["id"] == change.get("action_id")), None)
        if index is None:
            raise SetupChangeError("That quick action no longer exists - it was changed meanwhile.")
        label = actions[index]["label"]
        if op == "remove":
            actions.pop(index)
            line = f"Removed the quick action {label}."
        else:
            actions[index] = {**_clean_action(change["action"]), "id": actions[index]["id"]}
            line = f"Updated the quick action {actions[index]['label']}."
    program["quick_actions"] = actions
    db.kv_set(user_id, ref.namespace, "programs", json.dumps(programs))
    return line


def _apply_instruction(user_id: str, ref: ProgramRef, change: SetupChange) -> str:
    key = change["key"]
    after = _after_instruction(_instruction(user_id, ref, key), change)
    db.kv_set(user_id, ref.namespace, f"{ref.program_id}:{key}", _value_text(after))
    return f"Updated the coach's {key}."


def _target_value(current: ProgramSetup, change: SetupChange) -> object:
    """What the change replaces now: the quick action, or the instruction's value."""
    if change.get("target") == "instruction":
        return current["instructions"].get(str(change.get("key")))
    if change.get("op") == "add":
        return None
    return next((a for a in current["quick_actions"] if a["id"] == change.get("action_id")), None)


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:12]


def with_snapshot(current: ProgramSetup, change: SetupChange) -> SetupChange:
    """The change carrying a digest of its target as it is now (adds have none)."""
    if change.get("target") == "quick_action" and change.get("op") == "add":
        return change
    return {**change, "expect": _digest(_target_value(current, change))}


def _check_snapshot(user_id: str, ref: ProgramRef, change: SetupChange) -> None:
    """Refuse a change whose target was changed since it was suggested."""
    expected = change.get("expect")
    if not expected:
        return
    value = _target_value(load_setup(user_id, ref), change)
    if value is None and change.get("target") == "quick_action":
        return  # gone entirely: the apply says "no longer exists"
    if _digest(value) != expected:
        raise SetupChangeError("That changed since this was suggested - nothing was changed.")


def apply_change(user_id: str, ref: ProgramRef, change: SetupChange) -> str:
    """Apply an approved change; the line says what changed. Raises SetupChangeError."""
    checked = validate_change(ref.namespace, cast("Mapping[str, object]", change))
    if isinstance(checked, str):
        raise SetupChangeError(checked)
    _check_snapshot(user_id, ref, checked)
    if checked["target"] == "instruction":
        line = _apply_instruction(user_id, ref, checked)
    else:
        line = _apply_quick_action(user_id, ref, checked)
    logger.info(
        "Program setup changed",
        extra={"user_id": user_id, "namespace": ref.namespace, "target": checked["target"]},
    )
    return line


# --- fingerprints and declines ----------------------------------------------------


def _normalized(text: object) -> str:
    return " ".join(str(text).casefold().split())


def fingerprint(change: SetupChange) -> str:
    """The same suggestion has the same fingerprint (case and spacing ignored)."""
    if change.get("target") == "instruction":
        content = (
            json.dumps(change.get("patch"), sort_keys=True)
            if "patch" in change
            else change.get("text")
        )
        head = f"instruction|{change.get('key')}"
    else:
        action = change.get("action") or {}
        parts = (action.get("label"), action.get("body"), action.get("fields"))
        content = "|".join(_normalized(part) for part in parts)
        head = f"quick_action|{change.get('op')}|{change.get('action_id', '')}"
    digest = hashlib.sha1(_normalized(content).encode(), usedforsecurity=False).hexdigest()
    return f"{head}|{digest[:12]}"


def _declined_key(ref: ProgramRef) -> str:
    return f"{_DECLINED_KEY_PREFIX}{ref.program_id}"


def _declined_entry(raw: object) -> DeclinedEntry | None:
    """A stored entry, or None when malformed (the key is plain KV data)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("fingerprint"), str):
        return None
    try:
        when = date.fromisoformat(str(raw.get("declined_at")))
    except ValueError:
        return None
    return {
        "fingerprint": raw["fingerprint"],
        "summary": str(raw.get("summary", "")),
        "declined_at": when.isoformat(),
    }


def declined(user_id: str, ref: ProgramRef) -> list[DeclinedEntry]:
    """The suggestions the user declined for this program, oldest first."""
    try:
        data = json.loads(db.kv_get(user_id, ref.namespace, _declined_key(ref)) or "[]")
    except json.JSONDecodeError, TypeError:
        return []
    entries = [_declined_entry(e) for e in data] if isinstance(data, list) else []
    return [e for e in entries if e is not None]


def record_decline(user_id: str, ref: ProgramRef, change: SetupChange, summary: str) -> None:
    """Remember a declined suggestion (the newest SETUP_DECLINED_MAX are kept)."""
    entry: DeclinedEntry = {
        "fingerprint": fingerprint(change),
        "summary": summary[:200],
        "declined_at": local_today().isoformat(),
    }
    entries = [*declined(user_id, ref), entry][-Config.SETUP_DECLINED_MAX :]
    db.kv_set(user_id, ref.namespace, _declined_key(ref), json.dumps(entries))


def evidence_dates(evidence: list[str]) -> list[date]:
    """The YYYY-MM-DD dates the evidence items start with (unparseable ones skipped)."""
    dates: list[date] = []
    for item in evidence:
        if (match := _DATE.match(item)) is not None:
            try:
                dates.append(date.fromisoformat(match.group(1)))
            except ValueError:
                continue
    return dates


def chat_dates(conversation_id: str) -> set[date]:
    """The local days the user wrote in this chat (its latest messages)."""
    messages, _ = db.get_messages_paginated(conversation_id, limit=_CHAT_DATES_MESSAGES)
    return {to_local(m.created_at).date() for m in messages if m.role.value == "user"}


def evidence_problem(evidence: list[str], known_days: set[date]) -> str | None:
    """Why the evidence does not hold, or None: 1-5 items, each starting with a
    YYYY-MM-DD the user actually wrote on in this chat (final review: the dates
    were the model's word, and a fresh date re-opened a declined suggestion)."""
    items = [e.strip() for e in evidence if e.strip()]
    dates = evidence_dates(items)
    if not 1 <= len(items) <= EVIDENCE_MAX or len(dates) != len(items):
        return (
            f"Give 1-{EVIDENCE_MAX} evidence items, each starting with the YYYY-MM-DD date of a "
            "turn in this chat and what was said (e.g. \"2026-11-09: 'what's my next workout?'\")."
        )
    unknown = sorted({d for d in dates if d not in known_days})
    if unknown:
        days = ", ".join(d.isoformat() for d in unknown)
        return f"Cite only days the user wrote in this chat - not {days}."
    return None


def blocked_by_decline(
    entries: list[DeclinedEntry], change: SetupChange, evidence: list[str]
) -> bool:
    """True when this suggestion was declined and no evidence is newer than the decline."""
    mark = fingerprint(change)
    declines = [date.fromisoformat(e["declined_at"]) for e in entries if e["fingerprint"] == mark]
    if not declines:
        return False
    newest = max(declines)
    return not any(d > newest for d in evidence_dates(evidence))


def log_resolved(source: Literal["card", "review"], outcome: str, change: SetupChange) -> None:
    """One line per answered suggestion (the regular review counts them, rule A8)."""
    logger.info(
        "Setup suggestion resolved",
        extra={"source": source, "outcome": outcome, "target": change.get("target")},
    )
