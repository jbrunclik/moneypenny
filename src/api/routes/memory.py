"""Memory routes: user memory management.

This module contains routes for managing user memories (stored facts about the user).

Deletes are soft: a deleted memory stays recoverable for
``MEMORY_SOFT_DELETE_RETENTION_DAYS`` before the nightly job purges it. That
window exists because deletes are the one irreversible memory operation and can
be initiated by the LLM (including on the basis of fetched web content) or by
the defragmentation job, not just by the user.
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error
from src.api.schemas import (
    MemoriesListResponse,
    StatusResponse,
    UpdateMemoryProtectionRequest,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import Memory, User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("memory", __name__, url_prefix="/api", tag="Memory")


# ============================================================================
# Memory Routes
# ============================================================================


def _serialize(memory: Memory) -> dict[str, Any]:
    """Serialize a Memory for the API."""
    return {
        "id": memory.id,
        "content": memory.content,
        "category": memory.category,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
        "protected": memory.protected,
        "source_conversation_id": memory.source_conversation_id,
        "deleted_at": memory.deleted_at.isoformat() if memory.deleted_at else None,
    }


@api.route("/memories", methods=["GET"])
@api.output(MemoriesListResponse)
@require_auth
def list_memories(user: User) -> dict[str, Any]:
    """List all memories for the current user."""
    logger.debug("Listing memories", extra={"user_id": user.id})
    memories = db.list_memories(user.id)
    logger.info(
        "Memories listed",
        extra={"user_id": user.id, "count": len(memories)},
    )
    return {
        "memories": [_serialize(m) for m in memories],
        "limit": Config.MEMORY_MAX_ENTRIES,
    }


@api.route("/memories/deleted", methods=["GET"])
@api.output(MemoriesListResponse)
@require_auth
def list_deleted_memories(user: User) -> dict[str, Any]:
    """List recently deleted memories that can still be restored."""
    memories = db.list_deleted_memories(user.id)
    logger.info(
        "Deleted memories listed",
        extra={"user_id": user.id, "count": len(memories)},
    )
    return {
        "memories": [_serialize(m) for m in memories],
        "limit": Config.MEMORY_MAX_ENTRIES,
    }


@api.route("/memories/<memory_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_memory(user: User, memory_id: str) -> tuple[dict[str, str], int]:
    """Delete a memory (soft delete, restorable during the retention window)."""
    logger.debug("Deleting memory", extra={"user_id": user.id, "memory_id": memory_id})
    # allow_protected: the user is the owner of the protection flag, so their
    # own delete is always honoured. Only LLM/defrag deletes are refused.
    if not db.delete_memory(memory_id, user.id, allow_protected=True):
        logger.warning(
            "Memory not found for deletion",
            extra={"user_id": user.id, "memory_id": memory_id},
        )
        raise_not_found_error("Memory")

    logger.info("Memory deleted", extra={"user_id": user.id, "memory_id": memory_id})
    return {"status": "deleted"}, 200


@api.route("/memories/<memory_id>/restore", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def restore_memory(user: User, memory_id: str) -> tuple[dict[str, str], int]:
    """Restore a soft-deleted memory."""
    if not db.restore_memory(memory_id, user.id):
        raise_not_found_error("Memory")

    logger.info("Memory restored", extra={"user_id": user.id, "memory_id": memory_id})
    return {"status": "restored"}, 200


@api.route("/memories/<memory_id>/protection", methods=["PATCH"])
@api.input(UpdateMemoryProtectionRequest)
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def update_memory_protection(
    user: User, memory_id: str, json_data: UpdateMemoryProtectionRequest
) -> tuple[dict[str, str], int]:
    """Protect or unprotect a memory against LLM and defrag deletion."""
    protected = json_data.protected
    if not db.set_memory_protected(memory_id, user.id, protected):
        raise_not_found_error("Memory")

    logger.info(
        "Memory protection updated",
        extra={"user_id": user.id, "memory_id": memory_id, "protected": protected},
    )
    return {"status": "protected" if protected else "unprotected"}, 200
