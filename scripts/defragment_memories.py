#!/usr/bin/env python3
"""Memory defragmentation script for AI Chatbot.

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
import json
import sys
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.content import extract_text_content
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

Respond with a JSON object containing your changes:
```json
{{
  "reasoning": "Brief explanation of what you're consolidating and why",
  "delete": ["memory-id-1", "memory-id-2"],
  "update": [
    {{"id": "memory-id-3", "content": "Updated consolidated content", "category": "fact"}}
  ],
  "add": [
    {{"content": "New consolidated memory content", "category": "preference"}}
  ]
}}
```

Rules:
- Only include arrays that have items (omit empty arrays)
- If no changes are needed, return: {{"reasoning": "Memories are already well-organized", "no_changes": true}}
- Be conservative - when in doubt, keep the memory
- Aim to REDUCE the total memory count by consolidating, not just reorganizing
- The user currently has {memory_count} memories. Try to get this below {target_count} if possible without losing important information.
"""


def format_memories_for_llm(memories: list[Memory]) -> str:
    """Format memories as a numbered list for the LLM."""
    lines = []
    for i, mem in enumerate(memories, 1):
        category_str = f"[{mem.category}] " if mem.category else ""
        date_str = mem.created_at.strftime("%Y-%m-%d")
        lines.append(f"{i}. {category_str}{mem.content}")
        lines.append(f"   ID: {mem.id} | Created: {date_str}")
        lines.append("")
    return "\n".join(lines)


def parse_llm_response(response_text: str) -> dict | None:
    """Parse the LLM response to extract the changes JSON.

    Returns None if parsing fails.
    """
    try:
        # Try to find JSON in the response
        text = response_text.strip()

        # Look for JSON block markers
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM response as JSON", extra={"error": str(e)})
        return None


def validate_changes(
    changes: dict, existing_memory_ids: set[str]
) -> tuple[list[str], list[dict], list[dict]]:
    """Validate and extract changes from the LLM response.

    Returns (to_delete, to_update, to_add) tuples.
    """
    to_delete: list[str] = []
    to_update: list[dict] = []
    to_add: list[dict] = []

    # Check for no-op
    if changes.get("no_changes"):
        return to_delete, to_update, to_add

    # Validate deletions
    for memory_id in changes.get("delete", []):
        if memory_id in existing_memory_ids:
            to_delete.append(memory_id)
        else:
            logger.warning(
                "LLM tried to delete non-existent memory", extra={"memory_id": memory_id}
            )

    # Validate updates
    for update in changes.get("update", []):
        memory_id = update.get("id")
        content = update.get("content")
        if not memory_id or not content:
            logger.warning("Invalid update entry", extra={"update": update})
            continue
        if memory_id not in existing_memory_ids:
            logger.warning(
                "LLM tried to update non-existent memory", extra={"memory_id": memory_id}
            )
            continue
        if memory_id in to_delete:
            logger.warning(
                "LLM tried to update a memory it's also deleting",
                extra={"memory_id": memory_id},
            )
            continue
        to_update.append(update)

    # Validate additions
    for add in changes.get("add", []):
        content = add.get("content")
        if not content:
            logger.warning("Invalid add entry (missing content)", extra={"add": add})
            continue
        to_add.append(add)

    return to_delete, to_update, to_add


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
    # Target about 70% of current count or the warning threshold, whichever is lower
    target_count = min(int(memory_count * 0.7), Config.USER_MEMORY_WARNING_THRESHOLD)

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
    system_prompt = DEFRAG_SYSTEM_PROMPT.format(
        memory_count=memory_count, target_count=target_count
    )
    user_prompt = f"""Here are the user's current memories:

{format_memories_for_llm(memories)}

Please analyze these memories and provide consolidation recommendations."""

    try:
        # Call the LLM
        response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        content = response.content if hasattr(response, "content") else str(response)
        response_text = extract_text_content(content)
        logger.debug("LLM response received", extra={"response_length": len(response_text)})

        # Parse the response
        changes = parse_llm_response(response_text)
        if not changes:
            logger.error("Could not parse LLM response", extra={"user_id": user.id})
            result["skipped"] = True
            return result

        # Log the reasoning
        if "reasoning" in changes:
            logger.info(
                "Defragmentation reasoning",
                extra={"user_id": user.id, "reasoning": changes["reasoning"]},
            )

        # Check for no-op
        if changes.get("no_changes"):
            logger.info("No changes needed", extra={"user_id": user.id})
            result["skipped"] = True
            return result

        # Validate and extract changes
        existing_ids = {m.id for m in memories}
        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

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
