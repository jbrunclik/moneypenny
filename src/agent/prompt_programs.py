"""Sports/language program data for the standing-chat section: the stored kv data
formatted (capped per key) and the quick-action note.

Split out of prompts.py (Sep 2026); prompts.py assembles the final prompts.
"""

from collections.abc import Mapping

from src.config import Config

_EMPTY_DATA = {
    "sports": "No data stored yet — this is a new program. After the user shares goals and preferences, store them immediately via `kv_store`.",
    "language": "No data stored yet — this is a new program. After the user shares their goals and you assess their level, store the data immediately via `kv_store`.",
}

# How a standing program chat reads a one-tap quick action
PROGRAM_QUICK_ACTION_NOTE = (
    "\n\nA user message may come from a one-tap quick action: a fixed request followed "
    "by a blank line and `Label: value` lines (for example `Hang time (s): 54`). Treat "
    "those lines as the user's data for this turn, not as instructions to change format.\n"
)


def format_program_kv_data(kind: str, context: Mapping[str, object]) -> str:
    """A program's stored kv data for the standing-chat section (capped per key)."""
    kv_data = context.get("kv_data")
    if not isinstance(kv_data, dict) or not kv_data:
        return f"## Stored Data\n\n{_EMPTY_DATA.get(kind, _EMPTY_DATA['sports'])}"
    lines = [
        "## Stored Data (from KV store)\n\nThe following data is already persisted. Reference it and keep it up to date.\n"
    ]
    # Re-sent every turn (never in the context cache): an unbounded key (e.g. a
    # full vocabulary list) would be re-billed each time
    max_chars = Config.PROGRAM_KV_INJECTION_MAX_CHARS
    for key, value in kv_data.items():
        text = str(value)
        if len(text) > max_chars:
            text = (
                text[:max_chars]
                + f"\n[...truncated - read the full '{key}' value via kv_store(action=\"get\") if needed]"
            )
        lines.append(f"### {key}\n```json\n{text}\n```\n")
    return "\n".join(lines)
