"""Memory routes: user memory management.

This module contains routes for managing user memories (stored facts about the user).
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error
from src.api.schemas import MemoriesListResponse, StatusResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("memory", __name__, url_prefix="/api", tag="Memory")


# ============================================================================
# Memory Routes
# ============================================================================


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
        "memories": [
            {
                "id": m.id,
                "content": m.content,
                "category": m.category,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]
    }


@api.route("/memories/<memory_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_memory(user: User, memory_id: str) -> tuple[dict[str, str], int]:
    """Delete a memory."""
    logger.debug("Deleting memory", extra={"user_id": user.id, "memory_id": memory_id})
    if not db.delete_memory(memory_id, user.id):
        logger.warning(
            "Memory not found for deletion",
            extra={"user_id": user.id, "memory_id": memory_id},
        )
        raise_not_found_error("Memory")

    logger.info("Memory deleted", extra={"user_id": user.id, "memory_id": memory_id})
    return {"status": "deleted"}, 200
