"""Memory prompt assembly: static instructions + the per-user memory listing (tiered injection).

Split out of prompts.py (Sep 2026); prompts.py assembles the final prompts.
"""

from src.agent.prompt_texts.memory import MEMORY_SYSTEM_PROMPT
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Memory
from src.utils.clock import to_local
from src.utils.memory_ids import short_memory_id


def get_memory_instructions_prompt() -> str:
    """Return the static memory instructions (no per-user content).

    Kept separate from the memory list so it can live in the cached prefix:
    these ~1k tokens never change, and bundling them with the volatile list
    meant re-sending them uncached on every single request.
    """
    return MEMORY_SYSTEM_PROMPT.format(
        warning_threshold=Config.MEMORY_WARNING_THRESHOLD,
    )


# Memory categories injected even when the bank exceeds MEMORY_INJECT_FULL_MAX
_ALWAYS_INJECTED_MEMORY_CATEGORIES = frozenset({"preference", "goal", "fact"})


def _memory_line(mem: Memory) -> str:
    """One memory as the list shows it: short id, category, dates, flags, text.

    One line each (Nov 16 2026): indented JSON with full UUIDs was about twice
    the tokens, sent on every model call. Text is whitespace-folded so a
    multi-line memory cannot break the list.
    """
    created = to_local(mem.created_at).strftime("%Y-%m-%d")
    updated = to_local(mem.updated_at).strftime("%Y-%m-%d")
    dates = created if updated == created else f"{created}, upd {updated}"
    fields = [f"- {short_memory_id(mem.id)}", mem.category or "fact", dates]
    if mem.protected:
        fields.append("protected")
    # "" marks a memory Flash-Lite would not summarise: shown whole
    condensed = bool(mem.summary) and len(mem.content) > Config.MEMORY_SUMMARY_MAX_CHARS
    text = " ".join((mem.summary if condensed and mem.summary else mem.content).split())
    if condensed:
        # The full text is a search_memory id lookup away (Nov 15 2026)
        text += f" (condensed from {len(mem.content)} chars)"
    return " | ".join([*fields, text])


def get_user_memories_list_prompt(user_id: str) -> str:
    """Build just the current-memories listing for a user.

    This is the genuinely dynamic half of the memory prompt - it changes as soon
    as any memory is written, so it cannot be cached.

    Args:
        user_id: The user ID to fetch memories for

    Returns:
        Formatted string with the user's current memories
    """
    memories = db.list_memories(user_id)
    memory_count = len(memories)
    limit = Config.MEMORY_MAX_ENTRIES

    # Tiered injection: above the threshold, inject only core entries
    # (protected + preference + goal + fact) plus the most recently updated
    # others. Facts are core because the memory guidance files family, birthdays
    # and health under "fact" and says never to lose them - an old, never-updated
    # fact must not silently age out. Only transient "context" is recency-limited.
    # Everything is still reachable via the search_memory tool; this bounds
    # the per-turn token cost of a bank approaching MEMORY_MAX_ENTRIES.
    hidden_count = 0
    shown = memories
    if memory_count > Config.MEMORY_INJECT_FULL_MAX:
        core_ids = {
            mem.id
            for mem in memories
            if mem.protected or mem.category in _ALWAYS_INJECTED_MEMORY_CATEGORIES
        }
        rest = [mem for mem in memories if mem.id not in core_ids]
        recent_ids = {
            mem.id
            for mem in sorted(rest, key=lambda m: m.updated_at, reverse=True)[
                : Config.MEMORY_INJECT_RECENT_COUNT
            ]
        }
        shown = [mem for mem in memories if mem.id in core_ids or mem.id in recent_ids]
        hidden_count = memory_count - len(shown)

    if hidden_count > 0:
        header = f"## Current Memories ({len(shown)} of {memory_count}/{limit} shown)"
    else:
        header = f"## Current Memories ({memory_count}/{limit})"
    prompt_parts = [header]

    if memory_count >= Config.MEMORY_WARNING_THRESHOLD:
        prompt_parts.append(
            "\n**WARNING**: Near memory limit! Consider consolidating or removing outdated memories."
        )

    if shown:
        prompt_parts.append("(id | category | created[, upd updated] | [protected |] text)")
        prompt_parts.extend(_memory_line(mem) for mem in shown)
    else:
        prompt_parts.append("\nNo memories stored yet.")

    if hidden_count > 0:
        prompt_parts.append(
            f"\n{hidden_count} more memories exist but are not shown (only core and "
            "recently updated entries are listed). Use search_memory to look for "
            "facts not listed here BEFORE saying you don't know something about the user."
        )

    return "\n".join(prompt_parts)


def get_user_memories_prompt(user_id: str) -> str:
    """Build the full memory section (instructions + current memories).

    Used without a static prefix, where the SystemMessage carries everything.
    The split layout separates the two halves - see get_memory_instructions_prompt.

    Args:
        user_id: The user ID to fetch memories for

    Returns:
        Formatted string with memory instructions and current memories
    """
    return get_memory_instructions_prompt() + "\n\n" + get_user_memories_list_prompt(user_id)
