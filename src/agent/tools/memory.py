"""Long-term user memory tool.

This tool *performs* the writes it reports. It used to be a no-op stub whose
arguments were re-extracted from the AIMessage after the turn finished and
applied in the save path, which meant:

- every rejection (oversized content, full bank, unknown id, DB error) was
  logged server-side while the model was told "Processed N operation(s)", so it
  could neither retry nor tell the user;
- new memory IDs were never returned, so the model could not reference within
  the turn what it had just written;
- only the last AIMessage's operations survived, silently dropping writes made
  earlier in a multi-step tool loop.

Writing inside the tool means the model reads the real outcome as a tool result
and can act on it. It also means memory writes are bounded per call, which
matters because the operation list can be influenced by fetched web content.
"""

from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.db.models import db
from src.utils.embeddings import embed_and_store_async, embed_text, top_k_similar
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SEARCH_MEMORY_MAX_RESULTS = 10

VALID_ACTIONS = frozenset({"add", "update", "delete"})
VALID_CATEGORIES = frozenset({"preference", "fact", "context", "goal"})


def _reject(action: str, reason: str) -> str:
    """Format a rejected operation for the model."""
    return f"REJECTED ({action}): {reason}"


def _apply_add(user_id: str, conversation_id: str | None, op: dict[str, Any]) -> str:
    """Add a memory, reporting the new ID or why it was refused."""
    content = str(op.get("content") or "").strip()
    if not content:
        return _reject("add", "missing 'content'")

    if len(content) > Config.MEMORY_MAX_ENTRY_CHARS:
        # Memories are injected into EVERY request, so oversized writes are
        # unbounded context growth and an injection-persistence vector (A2).
        # Rejected rather than truncated - a half-stored fact is worse than none.
        return _reject(
            "add",
            f"content is {len(content)} chars, limit is {Config.MEMORY_MAX_ENTRY_CHARS}. "
            "Store a shorter, denser version.",
        )

    category = op.get("category")
    if category is not None and category not in VALID_CATEGORIES:
        return _reject(
            "add",
            f"unknown category '{category}'. Use one of: {', '.join(sorted(VALID_CATEGORIES))}.",
        )

    count = db.get_memory_count(user_id)
    if count >= Config.MEMORY_MAX_ENTRIES:
        return _reject(
            "add",
            f"memory bank is full ({count}/{Config.MEMORY_MAX_ENTRIES}). Consolidate two "
            "related memories with 'update', or delete one that no longer applies, then retry.",
        )

    memory = db.add_memory(
        user_id,
        content,
        category,
        source_conversation_id=conversation_id,
    )
    logger.info(
        "Memory added via tool",
        extra={"user_id": user_id, "memory_id": memory.id, "category": category},
    )
    embed_and_store_async(user_id, "memory", memory.id, content)
    return f"added id={memory.id} ({count + 1}/{Config.MEMORY_MAX_ENTRIES} used)"


def _apply_update(user_id: str, op: dict[str, Any]) -> str:
    """Update a memory, reporting whether the target existed."""
    memory_id = str(op.get("id") or "").strip()
    if not memory_id:
        return _reject("update", "missing 'id'")

    content = str(op.get("content") or "").strip()
    if not content:
        return _reject("update", f"missing 'content' for id={memory_id}")

    if len(content) > Config.MEMORY_MAX_ENTRY_CHARS:
        return _reject(
            "update",
            f"content is {len(content)} chars, limit is {Config.MEMORY_MAX_ENTRY_CHARS}. "
            "Store a shorter, denser version.",
        )

    category = op.get("category")
    if category is not None and category not in VALID_CATEGORIES:
        return _reject(
            "update",
            f"unknown category '{category}'. Use one of: {', '.join(sorted(VALID_CATEGORIES))}.",
        )

    if not db.update_memory(memory_id, user_id, content, category):
        return _reject(
            "update",
            f"no memory with id={memory_id} (it may have been deleted or consolidated). "
            "Re-read the current memory list before retrying.",
        )

    logger.info("Memory updated via tool", extra={"user_id": user_id, "memory_id": memory_id})
    embed_and_store_async(user_id, "memory", memory_id, content)
    return f"updated id={memory_id}"


def _apply_delete(user_id: str, op: dict[str, Any]) -> str:
    """Delete a memory, reporting protection refusals distinctly."""
    memory_id = str(op.get("id") or "").strip()
    if not memory_id:
        return _reject("delete", "missing 'id'")

    existing = db.get_memory(memory_id, user_id)
    if existing is None:
        return _reject("delete", f"no memory with id={memory_id}")

    if existing.protected:
        return _reject(
            "delete",
            f"id={memory_id} is protected by the user and cannot be deleted. "
            "Use 'update' if the fact has changed.",
        )

    if not db.delete_memory(memory_id, user_id):
        return _reject("delete", f"could not delete id={memory_id}")

    logger.info("Memory deleted via tool", extra={"user_id": user_id, "memory_id": memory_id})
    db.delete_embedding("memory", memory_id)
    return (
        f"deleted id={memory_id} (recoverable by the user for "
        f"{Config.MEMORY_SOFT_DELETE_RETENTION_DAYS} days)"
    )


@tool
def manage_memory(operations: list[dict[str, Any]]) -> str:
    """Store, update, or delete user memories for personalization.

    Call this when you learn new facts about the user that should be remembered
    for future conversations. The result tells you exactly what happened to each
    operation, including new memory IDs and the reason for any rejection - read
    it and correct course if an operation failed.

    Args:
        operations: List of memory operations. Each dict must have:
            - "action": one of "add", "update", or "delete"
            - "content": text content (required for add/update)
            - "category": one of "preference", "fact", "context", "goal" (for add)
            - "id": the memory ID (required for update/delete)

    Returns:
        One result line per operation, in the order submitted.
    """
    # Autonomous agents must have manage_memory in their permission list: an
    # unattended run that reads the web should not be able to write to the
    # user's long-term memory unless that was explicitly granted.
    check_autonomous_permission("manage_memory", {"operation_count": len(operations)})

    conversation_id, user_id = get_conversation_context()
    if not user_id:
        return "Error: no user context available, memories were not changed."

    if not operations:
        return "No operations submitted."

    results: list[str] = []

    # Bound the batch. A single turn has no legitimate need to rewrite the whole
    # bank, and the operation list can be influenced by fetched web content, so
    # the excess is refused rather than applied.
    if len(operations) > Config.MEMORY_MAX_OPS_PER_CALL:
        logger.warning(
            "Memory operation batch truncated",
            extra={
                "user_id": user_id,
                "submitted": len(operations),
                "limit": Config.MEMORY_MAX_OPS_PER_CALL,
            },
        )
        results.append(
            f"NOTE: {len(operations)} operations submitted but only the first "
            f"{Config.MEMORY_MAX_OPS_PER_CALL} were applied "
            f"(per-call limit). Submit the rest in a later turn if they are still needed."
        )
        operations = operations[: Config.MEMORY_MAX_OPS_PER_CALL]

    # Entries are guaranteed to be objects: the tool schema is validated by
    # Gemini and again by Pydantic before this function is entered.
    for op in operations:
        action = op.get("action")
        if action not in VALID_ACTIONS:
            results.append(
                _reject(
                    str(action),
                    f"unknown action. Use one of: {', '.join(sorted(VALID_ACTIONS))}.",
                )
            )
            continue

        try:
            if action == "add":
                results.append(_apply_add(user_id, conversation_id, op))
            elif action == "update":
                results.append(_apply_update(user_id, op))
            else:
                results.append(_apply_delete(user_id, op))
        except Exception as e:
            # A failed write must be visible to the model, not just the log.
            logger.error(
                "Error processing memory operation",
                extra={"user_id": user_id, "action": action, "error": str(e)},
                exc_info=True,
            )
            results.append(_reject(str(action), f"storage error: {e}"))

    return "\n".join(results)


@tool
def search_memory(query: str) -> str:
    """Search the user's stored memories for facts not shown in your context.

    When the memory list in your context says more memories exist than are
    shown, use this BEFORE concluding you don't know something about the user.
    Matches both keywords and meaning.

    Args:
        query: What to look for (topic, name, keyword, or a short question).

    Returns:
        Matching memories with their ids, categories and content.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return "Error: no user context available, cannot search memories."

    query = (query or "").strip()
    if not query:
        return "Error: 'query' is required."

    memories = db.list_memories(user_id)
    by_id = {mem.id: mem for mem in memories}

    # Keyword pass: case-insensitive substring over content and category
    needle = query.casefold()
    matched_ids = [
        mem.id
        for mem in memories
        if needle in mem.content.casefold() or needle in (mem.category or "").casefold()
    ]

    # Semantic pass: cosine over stored embeddings, merged after keyword hits
    if Config.EMBEDDINGS_ENABLED and len(matched_ids) < _SEARCH_MEMORY_MAX_RESULTS:
        query_vec = embed_text(query)
        if query_vec is not None:
            candidates = [
                (ref_id, vector)
                for ref_id, _dim, vector in db.get_embeddings(user_id, "memory")
                if ref_id in by_id
            ]
            for ref_id, score in top_k_similar(query_vec, candidates, _SEARCH_MEMORY_MAX_RESULTS):
                if score >= Config.MEMORY_SEARCH_MIN_SIMILARITY and ref_id not in matched_ids:
                    matched_ids.append(ref_id)

    matched_ids = matched_ids[:_SEARCH_MEMORY_MAX_RESULTS]
    logger.info(
        "Memory search via tool",
        extra={"user_id": user_id, "query": query, "results": len(matched_ids)},
    )

    if not matched_ids:
        return (
            f"No stored memories matched '{query}'. Try a different keyword or phrasing - "
            "if it still finds nothing, the user has not told you this."
        )

    lines = [f"Found {len(matched_ids)} matching memor{'y' if len(matched_ids) == 1 else 'ies'}:"]
    for memory_id in matched_ids:
        mem = by_id[memory_id]
        category = mem.category or "uncategorized"
        lines.append(f"- id={mem.id} [{category}] {mem.content}")
    return "\n".join(lines)
