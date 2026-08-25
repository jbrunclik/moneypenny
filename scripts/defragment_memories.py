#!/usr/bin/env python3
"""Memory defragmentation script for Moneypenny.

Uses an LLM to consolidate, deduplicate, and clean up user memories.
Runs nightly via systemd timer to keep memory banks efficient.

The LLM is instructed to:
- Group related memories together
- Merge duplicates or near-duplicates
- Remove outdated or irrelevant memories
- Ensure important context is preserved
- Keep the memory count within reasonable limits

Usage:
    python scripts/defragment_memories.py [--dry-run] [--user-id USER_ID]

Options:
    --dry-run       Show what would be changed without making changes
    --user-id       Process only a specific user (for testing)
"""

import argparse
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from src.agent.tools.memory import VALID_CATEGORIES
from src.config import Config
from src.db.models import Memory, User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# System prompt for the defragmentation LLM
DEFRAG_SYSTEM_PROMPT = """You are a memory maintenance assistant. Your task is to consolidate, deduplicate, and clean up a user's memory bank to make it more efficient and useful.

You will be given a list of existing memories about a user. Your job is to:

1. **Merge related memories**: If multiple memories cover the same topic, combine them into one comprehensive memory.
   - Example: "User likes coffee" + "User prefers dark roast" → "User enjoys coffee, preferring dark roast"

2. **Remove duplicates**: Delete memories that say essentially the same thing.

3. **Update outdated information**: If a newer memory contradicts an older one, keep the newer information.
   - Example: "User works at Company A" (older) + "User started new job at Company B" (newer) → Keep only "User works at Company B"

4. **Remove irrelevant memories**: Delete memories that are:
   - Too vague to be useful (e.g., "User asked about something")
   - Temporary/one-time context that's no longer relevant
   - Duplicated information that doesn't add value

5. **Preserve important facts**: Never delete:
   - Family member names and relationships
   - Important personal facts (birthdays, locations, etc.)
   - Strong preferences with clear reasoning
   - Ongoing goals or projects
   - Professional context

6. **Maintain categories**: Keep memories organized by category (preference, fact, context, goal).

7. **Write complete memories**: Each memory should be self-contained and understandable without context from other memories.

Rules:
- Be conservative - when in doubt, keep the memory
- Consolidating means REPLACING: if you merge several memories into a new one, delete
  every memory you merged. An `add` without the matching `delete`s grows the bank.
- Prefer rewriting one of the merged memories via `update` over `add` + `delete` of all
  of them: it keeps the original creation date.
- Memories marked PROTECTED cannot be deleted. Leave them, or update them in place.
- Content must be at most {max_entry_chars} characters, and category must be one of:
  preference, fact, context, goal.
- Set no_changes=true if the bank is already well-organized.
{target_instruction}
"""


class MemoryUpdate(BaseModel):
    """An edit to an existing memory."""

    id: str = Field(..., description="ID of the memory to update")
    content: str = Field(..., description="New consolidated content")
    category: str | None = Field(None, description="preference, fact, context or goal")


class MemoryAddition(BaseModel):
    """A new consolidated memory."""

    content: str = Field(..., description="Content of the new memory")
    category: str | None = Field(None, description="preference, fact, context or goal")


class DefragPlan(BaseModel):
    """The consolidation plan for one user's memory bank.

    Requested as a schema rather than parsed out of prose: a defrag run that
    silently no-ops because the model wrapped its JSON differently is invisible,
    and the old text parser skipped the user on any formatting surprise.
    """

    reasoning: str = Field("", description="Brief explanation of the consolidation")
    no_changes: bool = Field(False, description="True if the bank is already well-organized")
    delete: list[str] = Field(default_factory=list, description="IDs of memories to delete")
    update: list[MemoryUpdate] = Field(default_factory=list)
    add: list[MemoryAddition] = Field(default_factory=list)


def format_memories_for_llm(memories: list[Memory]) -> str:
    """Format memories as a numbered list for the LLM."""
    lines = []
    for i, mem in enumerate(memories, 1):
        category_str = f"[{mem.category}] " if mem.category else ""
        date_str = mem.created_at.strftime("%Y-%m-%d")
        protected_str = " | PROTECTED (cannot be deleted)" if mem.protected else ""
        lines.append(f"{i}. {category_str}{mem.content}")
        lines.append(f"   ID: {mem.id} | Created: {date_str}{protected_str}")
        lines.append("")
    return "\n".join(lines)


def _valid_category(category: str | None) -> str | None:
    """Drop categories the LLM invented rather than storing them."""
    if category is None:
        return None
    if category in VALID_CATEGORIES:
        return category
    logger.warning("Defrag proposed an unknown category", extra={"category": category})
    return None


def validate_changes(
    changes: DefragPlan | dict[str, Any], existing: dict[str, Memory]
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate and extract changes from the LLM response.

    Every proposed write goes through the same bounds the interactive tool
    enforces - the nightly job is not a privileged path into the memory bank.

    Args:
        changes: The plan returned by the LLM
        existing: The user's current memories, keyed by ID

    Returns:
        (to_delete, to_update, to_add) tuples.
    """
    if isinstance(changes, dict):
        changes = DefragPlan.model_validate(changes)

    to_delete: list[str] = []
    to_update: list[dict[str, Any]] = []
    to_add: list[dict[str, Any]] = []

    if changes.no_changes:
        return to_delete, to_update, to_add

    # Validate deletions
    for memory_id in changes.delete:
        memory = existing.get(memory_id)
        if memory is None:
            logger.warning(
                "LLM tried to delete non-existent memory", extra={"memory_id": memory_id}
            )
            continue
        if memory.protected:
            # Also enforced in the DB layer; logged here so the run is auditable
            logger.warning("LLM tried to delete a protected memory", extra={"memory_id": memory_id})
            continue
        to_delete.append(memory_id)

    # Validate updates
    for update in changes.update:
        if not update.id or not update.content:
            logger.warning("Invalid update entry", extra={"update": update.model_dump()})
            continue
        if update.id not in existing:
            logger.warning(
                "LLM tried to update non-existent memory", extra={"memory_id": update.id}
            )
            continue
        if update.id in to_delete:
            logger.warning(
                "LLM tried to update a memory it's also deleting",
                extra={"memory_id": update.id},
            )
            continue
        if len(update.content) > Config.MEMORY_MAX_ENTRY_CHARS:
            logger.warning(
                "Defrag update rejected - content too large",
                extra={"memory_id": update.id, "content_chars": len(update.content)},
            )
            continue
        to_update.append(
            {
                "id": update.id,
                "content": update.content,
                "category": _valid_category(update.category),
            }
        )

    # Validate additions
    for add in changes.add:
        if not add.content:
            logger.warning("Invalid add entry (missing content)", extra={"add": add.model_dump()})
            continue
        if len(add.content) > Config.MEMORY_MAX_ENTRY_CHARS:
            logger.warning(
                "Defrag add rejected - content too large",
                extra={"content_chars": len(add.content)},
            )
            continue
        to_add.append({"content": add.content, "category": _valid_category(add.category)})

    return to_delete, to_update, to_add


def plan_grows_bank(to_delete: list[str], to_add: list[dict[str, Any]]) -> bool:
    """Whether applying this plan would leave the user with more memories.

    Defragmentation exists to shrink the bank. A plan that adds consolidated
    entries without deleting what they replace makes things strictly worse, and
    that is the most likely way for this job to misbehave, so it is refused
    rather than applied.
    """
    return len(to_add) > len(to_delete)


def defragment_user_memories(
    user: User,
    memories: list[Memory],
    llm: ChatGoogleGenerativeAI,
    dry_run: bool = False,
) -> dict[str, int]:
    """Defragment memories for a single user.

    Args:
        user: The user whose memories to defragment
        memories: List of the user's memories
        llm: The LLM to use for consolidation
        dry_run: If True, don't make any changes

    Returns:
        Dict with counts: {"deleted": N, "updated": N, "added": N, "skipped": bool}
    """
    result = {"deleted": 0, "updated": 0, "added": 0, "skipped": False}

    if not memories:
        logger.info("No memories to defragment", extra={"user_id": user.id})
        result["skipped"] = True
        return result

    memory_count = len(memories)
    # Only push for reduction once the bank is actually large. Below the warning
    # threshold the bank is healthy, so ask for consolidation of genuine
    # duplicates only rather than a fixed percentage cut.
    if memory_count > Config.MEMORY_WARNING_THRESHOLD:
        target_count = min(int(memory_count * 0.7), Config.MEMORY_WARNING_THRESHOLD)
    else:
        target_count = memory_count

    logger.info(
        "Starting memory defragmentation for user",
        extra={
            "user_id": user.id,
            "user_email": user.email,
            "memory_count": memory_count,
            "target_count": target_count,
        },
    )

    # Build the prompt
    if target_count < memory_count:
        target_instruction = (
            f"- The user currently has {memory_count} memories. Try to get this below "
            f"{target_count} without losing important information."
        )
    else:
        target_instruction = (
            f"- The user has {memory_count} memories, which is a healthy size. Do not "
            "cut for the sake of cutting: only merge genuine duplicates and remove "
            "memories that are truly stale."
        )

    system_prompt = DEFRAG_SYSTEM_PROMPT.format(
        max_entry_chars=Config.MEMORY_MAX_ENTRY_CHARS,
        target_instruction=target_instruction,
    )
    user_prompt = f"""Here are the user's current memories:

{format_memories_for_llm(memories)}

Please analyze these memories and provide consolidation recommendations."""

    try:
        # Ask for a schema-validated plan rather than JSON embedded in prose
        changes = llm.with_structured_output(DefragPlan).invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        if changes is None:
            logger.error("LLM returned no defragmentation plan", extra={"user_id": user.id})
            result["skipped"] = True
            return result

        plan = (
            changes
            if isinstance(changes, DefragPlan)
            else DefragPlan.model_validate(
                changes if isinstance(changes, dict) else changes.model_dump()
            )
        )

        if plan.reasoning:
            logger.info(
                "Defragmentation reasoning",
                extra={"user_id": user.id, "reasoning": plan.reasoning},
            )

        # Check for no-op
        if plan.no_changes:
            logger.info("No changes needed", extra={"user_id": user.id})
            result["skipped"] = True
            return result

        # Validate and extract changes
        existing = {m.id: m for m in memories}
        to_delete, to_update, to_add = validate_changes(plan, existing)

        # Log planned changes
        logger.info(
            "Planned memory changes",
            extra={
                "user_id": user.id,
                "to_delete": len(to_delete),
                "to_update": len(to_update),
                "to_add": len(to_add),
                "dry_run": dry_run,
            },
        )

        # Refuse a plan that would grow the bank - see plan_grows_bank
        if plan_grows_bank(to_delete, to_add):
            logger.error(
                "Defragmentation plan rejected - it would grow the memory bank",
                extra={
                    "user_id": user.id,
                    "to_delete": len(to_delete),
                    "to_add": len(to_add),
                },
            )
            result["skipped"] = True
            return result

        if dry_run:
            # Log what would be changed
            for memory_id in to_delete:
                mem = next((m for m in memories if m.id == memory_id), None)
                if mem:
                    logger.info(
                        "[DRY RUN] Would delete memory",
                        extra={"memory_id": memory_id, "content": mem.content[:100]},
                    )
            for update in to_update:
                logger.info(
                    "[DRY RUN] Would update memory",
                    extra={"memory_id": update["id"], "new_content": update["content"][:100]},
                )
            for add in to_add:
                logger.info(
                    "[DRY RUN] Would add memory",
                    extra={"content": add["content"][:100], "category": add.get("category")},
                )

            result["deleted"] = len(to_delete)
            result["updated"] = len(to_update)
            result["added"] = len(to_add)
            return result

        # Apply changes using bulk update
        db_result = db.bulk_update_memories(
            user_id=user.id,
            to_delete=to_delete,
            to_update=[(u["id"], u["content"], u.get("category")) for u in to_update],
            to_add=[(a["content"], a.get("category")) for a in to_add],
        )

        result["deleted"] = db_result["deleted"]
        result["updated"] = db_result["updated"]
        result["added"] = db_result["added"]

        # Log final state
        new_count = memory_count - result["deleted"] + result["added"]
        logger.info(
            "Memory defragmentation completed",
            extra={
                "user_id": user.id,
                "old_count": memory_count,
                "new_count": new_count,
                "reduction": memory_count - new_count,
            },
        )

        return result

    except Exception as e:
        logger.error(
            "Error during memory defragmentation",
            extra={"user_id": user.id, "error": str(e)},
            exc_info=True,
        )
        result["skipped"] = True
        return result


def main() -> int:
    """Run memory defragmentation for eligible users.

    Returns:
        0 if successful, 1 if any errors occurred
    """
    parser = argparse.ArgumentParser(description="Defragment user memories using LLM")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        help="Process only a specific user (for testing)",
    )
    args = parser.parse_args()

    logger.info(
        "Starting memory defragmentation",
        extra={
            "dry_run": args.dry_run,
            "threshold": Config.MEMORY_DEFRAG_THRESHOLD,
            "model": Config.MEMORY_DEFRAG_MODEL,
            "user_id": args.user_id,
        },
    )

    # Purge soft-deleted memories whose recovery window has passed. Done here
    # rather than in a separate timer so the retention window is tied to the job
    # that produces most of the deletes.
    if not args.dry_run:
        purged = db.purge_deleted_memories(Config.MEMORY_SOFT_DELETE_RETENTION_DAYS)
        logger.info(
            "Purged expired soft-deleted memories",
            extra={
                "purged": purged,
                "retention_days": Config.MEMORY_SOFT_DELETE_RETENTION_DAYS,
            },
        )

    # Validate API key
    if not Config.GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is required")
        return 1

    # Initialize the LLM
    try:
        llm = ChatGoogleGenerativeAI(
            model=Config.MEMORY_DEFRAG_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.3,  # Lower temperature for more consistent results
        )
    except Exception as e:
        logger.error("Failed to initialize LLM", extra={"error": str(e)})
        return 1

    # Get users to process
    if args.user_id:
        # Process specific user
        user = db.get_user_by_id(args.user_id)
        if not user:
            logger.error("User not found", extra={"user_id": args.user_id})
            return 1
        memories = db.list_memories(user.id)
        users_to_process = [(user, len(memories))]
    else:
        # Get all users above the threshold
        users_to_process = db.get_users_with_memory_counts(
            min_memories=Config.MEMORY_DEFRAG_THRESHOLD
        )

    if not users_to_process:
        logger.info(
            "No users need memory defragmentation",
            extra={"threshold": Config.MEMORY_DEFRAG_THRESHOLD},
        )
        return 0

    logger.info(
        "Found users for defragmentation",
        extra={"user_count": len(users_to_process)},
    )

    # Process each user
    total_stats = {"users_processed": 0, "users_skipped": 0, "deleted": 0, "updated": 0, "added": 0}
    has_errors = False

    for user, _memory_count in users_to_process:
        try:
            memories = db.list_memories(user.id)
            result = defragment_user_memories(user, memories, llm, dry_run=args.dry_run)

            if result.get("skipped"):
                total_stats["users_skipped"] += 1
            else:
                total_stats["users_processed"] += 1
                total_stats["deleted"] += result["deleted"]
                total_stats["updated"] += result["updated"]
                total_stats["added"] += result["added"]

        except Exception as e:
            logger.error(
                "Error processing user",
                extra={"user_id": user.id, "error": str(e)},
                exc_info=True,
            )
            has_errors = True
            total_stats["users_skipped"] += 1

    # Log final summary
    logger.info(
        "Memory defragmentation completed",
        extra={
            "dry_run": args.dry_run,
            "users_processed": total_stats["users_processed"],
            "users_skipped": total_stats["users_skipped"],
            "total_deleted": total_stats["deleted"],
            "total_updated": total_stats["updated"],
            "total_added": total_stats["added"],
            "net_reduction": total_stats["deleted"] - total_stats["added"],
        },
    )

    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
