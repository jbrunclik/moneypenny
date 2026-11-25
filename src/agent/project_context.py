"""A project chat's additions to the turn: the project's instructions, memory
and documents (docs/superpowers/specs/2026-11-24-projects-design.md).

Loaded once per turn, like a standing chat's context; the prompt section is
src/agent/prompt_projects.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.db.models import db
from src.utils.clock import local_today
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Conversation, Document, Memory, User

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProjectContext:
    """The project a chat is filed under, as one member's turn sees it."""

    id: str
    name: str
    instructions: str
    shared: bool
    # First names of the members other than the user (shared projects)
    other_member_names: list[str] = field(default_factory=list)
    # user_id -> first name, for "by <name>" on shared memories
    author_names: dict[str, str] = field(default_factory=dict)
    memories: list[Memory] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)


def _first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def load_project_context(
    conv: Conversation, user: User, anonymous_mode: bool
) -> ProjectContext | None:
    """The chat's project, or None: no project, anonymous mode, or the user
    is no longer a member of it."""
    if anonymous_mode or conv.project_id is None:
        return None
    project = db.project_for_conversation(conv.id, user.id)
    if project is None:
        return None
    names = {person.id: _first_name(person.name) for person in db.list_people(exclude_user_id="")}
    today = local_today()
    return ProjectContext(
        id=project.id,
        name=project.name,
        instructions=project.instructions,
        shared=project.shared,
        other_member_names=[names.get(m, "") for m in project.member_ids if m != user.id],
        author_names=names,
        memories=[m for m in db.list_project_memories(project.id) if not m.expired(today)],
        documents=[d for d in db.list_project_documents(project.id) if not d.expired(today)],
    )
