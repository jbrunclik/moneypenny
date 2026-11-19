"""Shared synthetic chats that eval cases borrow with ``history_from:``.

Nov 2026: 95 of 120 cases had no earlier turns, while a production turn
carries 15-23 recent messages, often a compaction summary and program data -
the long context where weaker models lose instructions. A few long,
realistic conversations live in evals/fixtures/chats/; a case names one and
adds only its own final turn (and optionally a few turns of its own).

Fixture shape (YAML):

    mode: sports                # optional defaults a case inherits
    program_kv: {...}
    integrations: {...}
    web: {...}
    summary: |                  # frozen compaction summary of the older turns
      ...
    messages: [{role, content, metadata?}]

The summary is generated once with the real summarizer
(evals/freeze_summary.py), reviewed and committed, so every run sees the
same context and pays no summarizer calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CHATS_DIR = Path(__file__).parent / "fixtures" / "chats"

# Inherited key by key; the case's own value wins
_INHERITED = ("mode", "program", "web", "compact_history", "artifacts")
# Merged one level deep; the case's entry wins per key
_MERGED = ("program_kv", "integrations")


def load_chat(name: str, directory: Path | None = None) -> dict[str, Any]:
    """A shared chat's fixture, date placeholders resolved."""
    from evals.run import _resolve_dates

    path = (directory or CHATS_DIR) / f"{name}.yaml"
    if not path.exists():
        raise ValueError(f"unknown shared chat {name!r}")
    data: dict[str, Any] = _resolve_dates(yaml.safe_load(path.read_text()) or {})
    return data


def merge_chat(case_data: dict[str, Any], chat: dict[str, Any]) -> dict[str, Any]:
    """The raw case dict with the chat's defaults filled in (case wins)."""
    merged = dict(case_data)
    for key in _INHERITED:
        if key not in merged and key in chat:
            merged[key] = chat[key]
    for key in _MERGED:
        if key in chat:
            merged[key] = {**(chat[key] or {}), **(case_data.get(key) or {})}
    merged["history"] = [*(chat.get("messages") or []), *(case_data.get("history") or [])]
    if chat.get("summary"):
        merged["frozen_summary"] = str(chat["summary"])
        if chat.get("summary_covers") is not None:
            merged["frozen_summary_covers"] = int(chat["summary_covers"])
    return merged


def seed_frozen_summary(
    case: Any,
    user: Any,
    db: Any,
    conversation_id: str,
    *,
    store_messages: bool = True,
    history: list[dict[str, Any]] | None = None,
    summary: str | None = None,
) -> list[dict[str, Any]]:
    """Seed the chat's frozen summary as production stores compaction state.

    The history's messages become the conversation's (so past-chat search can
    reach the summarized part) unless the program path already stored them;
    the older part is covered by one segment holding the frozen summary.
    Returns the history the turn sees: the summary message plus the recent tail.
    ``history`` and ``summary`` override the case's (e.g. with seeded artifact
    ids filled in - an artifact may be mentioned only in the summarized part).
    """
    from src.agent.conversation_compaction import KV_NAMESPACE, _summary_message
    from src.config import Config

    turns = case.history if history is None else history
    text = case.frozen_summary if summary is None else summary
    if store_messages:
        for turn in turns:
            db.add_message(conversation_id, turn["role"], turn["content"])
    # The chat's own count (frozen with the summary), so turns a case appends
    # join the verbatim tail instead of pushing chat messages out of both
    covers = getattr(case, "frozen_summary_covers", None)
    covered = (
        covers
        if covers is not None
        else max(0, len(turns) - Config.CONVERSATION_COMPACTION_KEEP_RECENT)
    )
    recent = turns[covered:]
    # Coverage indexes the STORED messages: a program chat stores user turns only
    stored = covered if store_messages else sum(t["role"] == "user" for t in turns[:covered])
    state = {
        "segments": [{"text": text, "end": stored, "passes": 1}],
        "covered_count": stored,
    }
    db.kv_set(user.id, KV_NAMESPACE, conversation_id, json.dumps(state))
    return [_summary_message(text), *recent]
