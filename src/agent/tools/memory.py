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

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.db.models import db
from src.db.models.memory import MemoryWrite, MemoryWriteConflictError
from src.utils.embeddings import embed_text, top_k_similar
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SEARCH_MEMORY_MAX_RESULTS = 10

VALID_ACTIONS = frozenset({"add", "patch", "delete"})
VALID_CATEGORIES = frozenset({"preference", "fact", "context", "goal"})


class MemoryOp(TypedDict, total=False):
    """One manage_memory operation as the model sends it (fields per action)."""

    action: str
    id: str
    content: str
    category: str
    old_text: str
    new_text: str


def _reject(action: str, reason: str) -> str:
    """Format a rejected operation for the model."""
    logger.info("Memory write rejected", extra={"action": action, "reason": reason[:120]})
    return f"REJECTED ({action}): {reason}"


# Steering rides on the tool RESULT (prompt rules were measured to be
# ignored): oversized and near-full entries were catch-alls absorbing
# unrelated facts, and each forced rewrite dropped details
_ONE_TOPIC_HINT = "Keep one topic per memory: save a new fact as its own memory with 'add'."


def _too_long(action: str, content: str) -> str:
    return _reject(
        action,
        f"content is {len(content)} chars, limit is {Config.MEMORY_MAX_ENTRY_CHARS}. "
        f"{_ONE_TOPIC_HINT} Otherwise store a shorter, denser version.",
    )


def _bad_category(action: str, category: object) -> str | None:
    if category is None or category in VALID_CATEGORIES:
        return None
    return _reject(
        action,
        f"unknown category '{category}'. Use one of: {', '.join(sorted(VALID_CATEGORIES))}.",
    )


@dataclass
class _Planned:
    """A validated operation, written only once the whole batch validates."""

    write: MemoryWrite
    old_chars: int = 0


@dataclass
class _BatchState:
    """The memory bank as the batch leaves it, built while planning.

    Limits and later operations are checked against this final state, so a
    delete-then-add on a full bank works and a patch after a patch of the same
    memory edits the patched text.
    """

    user_id: str
    count: int
    contents: dict[str, str] = field(default_factory=dict)
    protected: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)

    def content_of(self, memory_id: str) -> str | None:
        """The memory's text as of this point in the batch, None if gone."""
        if memory_id in self.deleted:
            return None
        if memory_id not in self.contents:
            memory = db.get_memory(memory_id, self.user_id)
            if memory is None:
                return None
            self.contents[memory_id] = memory.content
            if memory.protected:
                self.protected.add(memory_id)
        return self.contents[memory_id]


def _unknown_id(action: str, memory_id: str) -> str:
    return _reject(
        action,
        f"no memory with id={memory_id} (it may have been deleted, also earlier in this "
        "batch). Re-read the current memory list before retrying.",
    )


def _plan_add(op: MemoryOp, state: _BatchState) -> _Planned | str:
    content = str(op.get("content") or "").strip()
    if not content:
        return _reject("add", "missing 'content'")
    if len(content) > Config.MEMORY_MAX_ENTRY_CHARS:
        # Memories are injected into EVERY request, so oversized writes are
        # unbounded context growth and an injection-persistence vector (A2).
        # Rejected rather than truncated - a half-stored fact is worse than none.
        return _too_long("add", content)
    category = op.get("category")
    if rejection := _bad_category("add", category):
        return rejection
    state.count += 1
    return _Planned(MemoryWrite("add", content=content, category=category))


def _patched_text(op: MemoryOp, memory_id: str, content: str) -> str:
    """The memory after replacing old_text once; raises ValueError with the reason."""
    old_text, new_text = str(op["old_text"]), str(op["new_text"])
    matches = content.count(old_text)
    if matches == 0:
        raise ValueError(
            f'old_text not found in id={memory_id}. Its current text is: "{content}" - '
            "copy old_text from it exactly."
        )
    if matches > 1:
        raise ValueError(
            f"old_text matches {matches} times in id={memory_id}; include more surrounding "
            "text so it matches once."
        )
    return content.replace(old_text, new_text, 1).strip()


def _plan_patch(op: MemoryOp, state: _BatchState) -> _Planned | str:
    """Replace one unique span of a memory (and/or change its category)."""
    memory_id = str(op.get("id") or "").strip()
    if not memory_id:
        return _reject("patch", "missing 'id'")
    category = op.get("category")
    if rejection := _bad_category("patch", category):
        return rejection
    has_span = bool(op.get("old_text"))
    if not has_span and (category is None or op.get("new_text") is not None):
        return _reject(
            "patch", "missing 'old_text' (the exact text to replace, copied from the memory)"
        )
    if has_span and op.get("new_text") is None:
        return _reject("patch", "missing 'new_text' (use \"\" to remove old_text)")

    content = state.content_of(memory_id)
    if content is None:
        return _unknown_id("patch", memory_id)
    try:
        new_content = _patched_text(op, memory_id, content) if has_span else content
    except ValueError as e:
        return _reject("patch", str(e))
    if not new_content:
        return _reject(
            "patch", f"this would leave id={memory_id} empty; use 'delete' to remove a memory."
        )
    if len(new_content) > Config.MEMORY_MAX_ENTRY_CHARS:
        return _too_long("patch", new_content)

    state.contents[memory_id] = new_content
    write = MemoryWrite("patch", memory_id, new_content, expected=content, category=category)
    return _Planned(write, old_chars=len(content))


def _plan_delete(op: MemoryOp, state: _BatchState) -> _Planned | str:
    memory_id = str(op.get("id") or "").strip()
    if not memory_id:
        return _reject("delete", "missing 'id'")
    if state.content_of(memory_id) is None:
        return _unknown_id("delete", memory_id)
    if memory_id in state.protected:
        return _reject(
            "delete",
            f"id={memory_id} is protected by the user and cannot be deleted. "
            "Use 'patch' if the fact has changed.",
        )
    state.deleted.add(memory_id)
    state.count -= 1
    return _Planned(MemoryWrite("delete", memory_id))


_PLANNERS = {"add": _plan_add, "patch": _plan_patch, "delete": _plan_delete}


def _plan_op(op: MemoryOp, state: _BatchState) -> _Planned | str:
    action = op.get("action")
    if action == "update":
        return _reject(
            "update",
            "'update' was replaced by 'patch': send the exact text to change as old_text "
            "and its replacement as new_text.",
        )
    planner = _PLANNERS.get(str(action))
    if planner is None:
        return _reject(
            str(action), f"unknown action. Use one of: {', '.join(sorted(VALID_ACTIONS))}."
        )
    return planner(op, state)


def _plan_batch(user_id: str, operations: list[MemoryOp]) -> tuple[list[_Planned | str], int]:
    """Validate every operation against the batch's final state.

    Returns the plan and the bank size the batch leaves.
    """
    state = _BatchState(user_id, count=db.get_memory_count(user_id))
    plan = [_plan_op(op, state) for op in operations]
    if state.count > Config.MEMORY_MAX_ENTRIES:
        full = (
            f"memory bank would be full ({state.count}/{Config.MEMORY_MAX_ENTRIES} after this "
            "batch). Merge two related memories (add the merged one, delete both) or delete one "
            "that no longer applies, in the same batch."
        )
        plan = [
            _reject("add", full) if isinstance(p, _Planned) and p.write.action == "add" else p
            for p in plan
        ]
    return plan, state.count


def _rejected_batch(plan: list[_Planned | str]) -> list[str]:
    lines = ["Nothing was applied: fix the REJECTED operations and resubmit the whole batch."]
    for planned in plan:
        if isinstance(planned, str):
            lines.append(planned)
        else:
            lines.append(f"not applied ({planned.write.action}): valid, resubmit it with the fixes")
    return lines


def _best_effort(side_effect: Callable[..., object], *args: str) -> None:
    """Run a post-commit side effect (embeddings) without failing the report.

    The writes already landed: an error here must not reach the model as
    "nothing was applied", or it resubmits and duplicates them.
    """
    try:
        side_effect(*args)
    except Exception:
        logger.warning("Memory side effect failed after commit", exc_info=True)


def _applied_line(user_id: str, planned: _Planned, new_id: str | None, count: int) -> str:
    """Log, embed and describe one write that landed."""
    write = planned.write
    if write.action == "add":
        logger.info(
            "Memory added via tool",
            extra={"user_id": user_id, "memory_id": new_id, "category": write.category},
        )
        _best_effort(db.embed_and_store_async, user_id, "memory", str(new_id), str(write.content))
        return f"added id={new_id} ({count}/{Config.MEMORY_MAX_ENTRIES} used)"
    if write.action == "patch":
        content = str(write.content)
        # The old length shows in the log whether edits shrink memories (lose details)
        logger.info(
            "Memory updated via tool",
            extra={
                "user_id": user_id,
                "memory_id": write.memory_id,
                "old_chars": planned.old_chars,
                "new_chars": len(content),
            },
        )
        _best_effort(db.embed_and_store_async, user_id, "memory", str(write.memory_id), content)
        line = f'patched id={write.memory_id}, now: "{content}"'
        limit = Config.MEMORY_MAX_ENTRY_CHARS
        if len(content) >= limit * Config.MEMORY_ENTRY_NEAR_LIMIT_RATIO:
            line += f" ({len(content)}/{limit} chars). {_ONE_TOPIC_HINT}"
        return line
    logger.info("Memory deleted via tool", extra={"user_id": user_id, "memory_id": write.memory_id})
    _best_effort(db.delete_embedding, "memory", str(write.memory_id))
    return (
        f"deleted id={write.memory_id} (recoverable by the user for "
        f"{Config.MEMORY_SOFT_DELETE_RETENTION_DAYS} days)"
    )


def _run_batch(user_id: str, conversation_id: str | None, operations: list[MemoryOp]) -> list[str]:
    """Plan the batch, then write all of it in one transaction or none of it."""
    try:
        plan, count = _plan_batch(user_id, operations)
        planned = [p for p in plan if isinstance(p, _Planned)]
        if len(planned) < len(plan):
            return _rejected_batch(plan)
        new_ids = db.apply_memory_batch(user_id, conversation_id, [p.write for p in planned])
    except MemoryWriteConflictError as e:
        logger.info("Memory write rejected", extra={"action": "batch", "reason": "conflict"})
        return [
            f"Nothing was applied: memory id={e.memory_id} changed or was deleted while this "
            "batch ran. Look it up again with search_memory and resubmit the whole batch."
        ]
    except Exception as e:
        # A failed write must be visible to the model, not just the log. Only
        # planning and the transaction are in here: past the commit, the
        # writes landed whatever happens next.
        logger.exception(
            "Error processing memory operations", extra={"user_id": user_id, "error": str(e)}
        )
        return [_reject("batch", f"storage error: {e}. Nothing was applied.")]
    return [
        _applied_line(user_id, p, new_id, count) for p, new_id in zip(planned, new_ids, strict=True)
    ]


@tool
def manage_memory(operations: list[dict[str, Any]]) -> str:
    """Store, edit, or delete user memories for personalization.

    Call this when you learn new facts about the user that should be remembered
    for future conversations. Write facts, not commands: "Prefers short answers",
    not "Always answer briefly". The batch is applied all-or-nothing: if any
    operation is rejected, none is applied and the result says why - fix it and
    resubmit the whole batch. Limits are checked on the batch's end state.

    Args:
        operations: List of memory operations. Each dict has an "action":
            - "add": "content", "category" (one of "preference", "fact",
              "context", "goal")
            - "patch": "id", "old_text" (an exact span of the memory, matching
              once), "new_text" (its replacement; "" removes it); optionally
              "category" to recategorize (old_text may then be omitted)
            - "delete": "id"
            To merge memories: add the merged one and delete the old ones in
            one batch.

    Returns:
        One result line per operation, in the order submitted.
    """
    # Autonomous agents must have manage_memory in their permission list: an
    # unattended run that reads the web should not be able to write to the
    # user's long-term memory unless that was explicitly granted.
    check_autonomous_permission("manage_memory", {"operation_count": len(operations)})

    conversation_id, user_id = get_conversation_context()
    if not user_id:
        return tool_error("No user context available, memories were not changed.", retriable=False)

    if not operations:
        return "No operations submitted."

    # Bound the batch. A single turn has no legitimate need to rewrite the whole
    # bank, and the operation list can be influenced by fetched web content.
    # Refused whole, not cut: a cut applies half a merge and skips validating
    # the rest.
    limit = Config.MEMORY_MAX_OPS_PER_CALL
    if len(operations) > limit:
        logger.warning(
            "Memory operation batch refused",
            extra={"user_id": user_id, "submitted": len(operations), "limit": limit},
        )
        return _reject(
            "batch",
            f"{len(operations)} operations submitted, the per-call limit is {limit}. "
            "Nothing was applied: submit only the important ones, at most "
            f"{limit} per call.",
        )

    # Entries are guaranteed to be objects: the tool schema is validated by
    # Gemini and again by Pydantic before this function is entered.
    return "\n".join(_run_batch(user_id, conversation_id, cast(list[MemoryOp], operations)))


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
        return tool_error("No user context available, cannot search memories.", retriable=False)

    query = (query or "").strip()
    if not query:
        return tool_error("'query' is required.")

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
