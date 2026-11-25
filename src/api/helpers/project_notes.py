"""The label under a reply that wrote to a shared project's memory.

The privacy gate for shared projects (projects design, Nov 2026): a member's
private fact must never sit unseen in memory the family reads, so every write
to a shared project's memory is shown to its author under the reply, the same
way the background memory review's saves are.

manage_memory records the ids the turn wrote (added or patched); the label is
built from those rows, each under the project it belongs to - not the chat's
current project, which a move during the turn may have changed.
"""

from src.agent.memory_review import format_note
from src.agent.tools.memory import take_project_writes
from src.db.models import Memory, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _by_project(user_id: str, memory_ids: list[str]) -> dict[str, list[Memory]]:
    """The live written rows the user may still see, grouped by project."""
    grouped: dict[str, list[Memory]] = {}
    for memory_id in memory_ids:
        memory = db.get_visible_memory(memory_id, user_id)
        if memory is not None and memory.project_id:
            grouped.setdefault(memory.project_id, []).append(memory)
    return grouped


def note_shared_project_writes(conv_id: str, user_id: str, assistant_message_id: str) -> None:
    """Label the reply with the shared project memories its turn wrote."""
    # Taken (and cleared) first, on every path: a record left behind would
    # label a later reply
    written = take_project_writes(user_id, conv_id)
    if not written:
        return
    notes = []
    for project_id, memories in _by_project(user_id, written).items():
        project = db.get_project(project_id, user_id)
        if project is None or not project.shared:
            continue
        notes.append(format_note([m.content for m in memories], project_name=project.name))
        logger.info(
            "Shared project memory noted",
            extra={"project_id": project.id, "user_id": user_id, "writes": len(memories)},
        )
    if notes:
        db.set_memory_note(assistant_message_id, "; ".join(notes))
