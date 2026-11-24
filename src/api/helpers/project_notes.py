"""The label under a reply that wrote to a shared project's memory.

The privacy gate for shared projects (projects design, Nov 2026): a member's
private fact must never sit unseen in memory the family reads, so every write
to a shared project's memory is shown to its author under the reply, the same
way the background memory review's saves are.
"""

from src.agent.memory_review import format_note
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def note_shared_project_writes(conv_id: str, user_id: str, assistant_message_id: str) -> None:
    """Label the reply with the shared project memories its turn wrote."""
    project = db.project_for_conversation(conv_id, user_id)
    if project is None or not project.shared:
        return
    written = db.project_memories_written_this_turn(conv_id)
    if not written:
        return
    db.set_memory_note(
        assistant_message_id,
        format_note([m.content for m in written], project_name=project.name),
    )
    logger.info(
        "Shared project memory noted",
        extra={"project_id": project.id, "user_id": user_id, "writes": len(written)},
    )
