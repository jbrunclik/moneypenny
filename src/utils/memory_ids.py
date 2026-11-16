"""Short memory ids: the per-turn memory list shows a UUID prefix, and the
memory tools map it back to the full id (Nov 16 2026: the full UUIDs in an
indented JSON list made the list about twice its tokens, on every model call)."""

from collections.abc import Iterable

from src.constants import MEMORY_SHORT_ID_CHARS


def short_memory_id(memory_id: str) -> str:
    """The id as the memory list shows it."""
    return memory_id[:MEMORY_SHORT_ID_CHARS]


def matching_memory_ids(ref: str, memory_ids: Iterable[str]) -> list[str]:
    """The full ids `ref` names: itself when it is one, else every id it is a
    prefix of (at least the short length, so a fragment names nothing)."""
    ids = list(memory_ids)
    if ref in ids:
        return [ref]
    if len(ref) < MEMORY_SHORT_ID_CHARS:
        return []
    return [memory_id for memory_id in ids if memory_id.startswith(ref)]
