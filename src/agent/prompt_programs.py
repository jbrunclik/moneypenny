"""Sports/language program context: static preamble and per-request KV data formatting.

Split out of prompts.py (Sep 2026); prompts.py assembles the final prompts.
"""

from typing import Any

from src.config import Config


def format_sports_kv_data(sports_context: dict[str, Any]) -> str:
    """Format stored KV data for injection into the sports system prompt."""
    kv_data = sports_context.get("kv_data", {})
    if not kv_data:
        return "## Stored Data\n\nNo data stored yet — this is a new program. After the user shares goals and preferences, store them immediately via `kv_store`."

    lines = [
        "## Stored Data (from KV store)\n\nThe following data is already persisted. Reference it and keep it up to date.\n"
    ]
    # Per-key injection cap: this section is dynamic (never in the context
    # cache) and re-sent every turn, so an unbounded key (e.g. a full
    # vocabulary list) is re-billed each time
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


def format_language_kv_data(language_context: dict[str, Any]) -> str:
    """Format stored KV data for injection into the language system prompt."""
    kv_data = language_context.get("kv_data", {})
    if not kv_data:
        return "## Stored Data\n\nNo data stored yet — this is a new program. After the user shares their goals and you assess their level, store the data immediately via `kv_store`."

    lines = [
        "## Stored Data (from KV store)\n\nThe following data is already persisted. Reference it and keep it up to date.\n"
    ]
    # Per-key injection cap: this section is dynamic (never in the context
    # cache) and re-sent every turn, so an unbounded key (e.g. a full
    # vocabulary list) is re-billed each time
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


# Cached (static) variants of the program prompts: the per-program values are
# replaced by indirection tokens resolved from the per-request dynamic context.
# This keeps one cache entry per feature instead of one per program.
PROGRAM_STATIC_PREAMBLE = (
    "\n\nNote: the placeholders <program_name> and <program_id> below refer to the "
    "active program - its actual name and id are given in the Active Program "
    "section of the per-request context.\n"
    "\nA user message may come from a one-tap quick action: a fixed request followed "
    "by a blank line and `Label: value` lines (for example `Hang time (s): 54`). Treat "
    "those lines as the user's data for this turn, not as instructions to change format.\n"
)


PROGRAM_STATIC_KV_NOTE = (
    "## Stored Data\n\n"
    "The stored program data is provided in the Active Program section of the "
    "per-request context."
)


def format_program_dynamic_context(kind: str, context: dict[str, Any]) -> str:
    """Active-program identity + stored KV data for the dynamic context tail."""
    name = context.get("program_name", "Program")
    program_id = context.get("program_id", "program")
    header = (
        "## Active Program\n"
        f"- <program_name>: {name}\n"
        f"- <program_id>: {program_id} (KV keys are prefixed `{program_id}:`)\n"
    )
    kv_section = (
        format_sports_kv_data(context) if kind == "sports" else format_language_kv_data(context)
    )
    return header + "\n" + kv_section
