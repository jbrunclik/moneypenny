"""Project routes: folders of chats with shared instructions, memory and
documents, and moving chats in and out of them.

A non-member gets 404 for any project route; an owner-only action by a member
gets 403. Each member sees only their own chats in a project.
"""

from apiflask import APIBlueprint

from src.api.errors import (
    raise_auth_forbidden_error,
    raise_conflict_error,
    raise_not_found_error,
    raise_validation_error,
)
from src.api.routes.conversations import api as conversations_api
from src.api.routes.documents import serialize_document
from src.api.routes.memory import serialize_memory
from src.api.schemas.common import StatusResponse
from src.api.schemas.conversations import ConversationsListPaginatedResponse, ConversationsPageQuery
from src.api.schemas.projects import (
    BulkMoveRequest,
    BulkMoveResponse,
    CreateProjectRequest,
    DeletedProjectsResponse,
    MoveConversationRequest,
    PeopleResponse,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectsListResponse,
    UpdateProjectRequest,
)
from src.api.validation import validate_query, validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import Project, ProjectSummary, User, db
from src.db.models.projects import ProjectWriteError
from src.services.push import send_push_to_user
from src.utils.clock import local_today, to_api
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("projects", __name__, url_prefix="/api", tag="Projects")


def _serialize(
    project: Project, user: User, summary: ProjectSummary | None = None
) -> dict[str, object]:
    names = summary.member_names if summary else _names(project.member_ids)
    return {
        "id": project.id,
        "name": project.name,
        "owner_id": project.owner_id,
        "is_owner": project.owner_id == user.id,
        "shared": project.shared,
        "member_names": names,
        "member_ids": project.member_ids,
        "chat_count": summary.chat_count if summary else 0,
        "unread_count": summary.unread_count if summary else 0,
        "created_at": to_api(project.created_at),
        "updated_at": to_api(project.updated_at),
        "deleted_at": to_api(project.deleted_at) if project.deleted_at else None,
    }


def _names(user_ids: list[str]) -> list[str]:
    people = dict(db.list_people(exclude_user_id=""))
    return [people.get(user_id, "") for user_id in user_ids]


def _member_project(user: User, project_id: str) -> Project:
    project = db.get_project(project_id, user.id)
    if project is None:
        raise_not_found_error("Project")
    return project


def _owned_project(user: User, project_id: str) -> Project:
    project = _member_project(user, project_id)
    if project.owner_id != user.id:
        raise_auth_forbidden_error("Only the project's owner can do that.")
    return project


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise_validation_error("The project needs a name.")
    return cleaned


@api.route("/projects", methods=["GET"])
@api.output(ProjectsListResponse)
@require_auth
def list_projects(user: User) -> dict[str, object]:
    """The projects the user owns or was added to."""
    return {
        "projects": [_serialize(s.project, user, s) for s in db.list_projects(user.id)],
        "limit": Config.PROJECTS_MAX_PER_USER,
    }


@api.route("/projects", methods=["POST"])
@api.output(ProjectResponse, status_code=201)
@api.doc(responses=[409, 422])
@require_auth
@validate_request(CreateProjectRequest)
def create_project(user: User, data: CreateProjectRequest) -> tuple[dict[str, object], int]:
    """Create a project (the caller owns it)."""
    try:
        project = db.create_project(user.id, _clean_name(data.name), data.instructions.strip())
    except ProjectWriteError as e:
        raise_conflict_error(str(e))
    return _serialize(project, user), 201


@api.route("/projects/deleted", methods=["GET"])
@api.output(DeletedProjectsResponse)
@require_auth
def list_deleted_projects(user: User) -> dict[str, object]:
    """The caller's deleted projects, restorable until the purge."""
    return {"projects": [_serialize(p, user) for p in db.list_deleted_projects(user.id)]}


@api.route("/projects/people", methods=["GET"])
@api.output(PeopleResponse)
@require_auth
def list_people(user: User) -> dict[str, object]:
    """The family members a project can be shared with."""
    return {"people": [{"id": i, "name": n} for i, n in db.list_people(user.id)]}


@api.route("/projects/<project_id>", methods=["GET"])
@api.output(ProjectDetailResponse)
@api.doc(responses=[404])
@require_auth
def get_project(user: User, project_id: str) -> dict[str, object]:
    """A project with its instructions, memory and documents."""
    project = _member_project(user, project_id)
    authors = dict(db.list_people(exclude_user_id=""))
    today = local_today()
    memories = [m for m in db.list_project_memories(project.id) if not m.expired(today)]
    documents = db.list_project_documents(project.id)
    summary = next((s for s in db.list_projects(user.id) if s.project.id == project.id), None)
    return {
        "project": _serialize(project, user, summary),
        "instructions": project.instructions,
        "memories": [
            {**serialize_memory(m), "author_name": authors.get(m.user_id)} for m in memories
        ],
        "documents": [
            {**serialize_document(d), "author_name": authors.get(d.user_id)} for d in documents
        ],
        "instructions_limit": Config.PROJECT_INSTRUCTIONS_MAX_CHARS,
        "memory_limit": Config.PROJECT_MEMORY_MAX_ENTRIES,
        "documents_limit": Config.PROJECT_DOCUMENTS_MAX_ENTRIES,
    }


@api.route("/projects/<project_id>", methods=["PATCH"])
@api.output(ProjectResponse)
@api.doc(responses=[403, 404, 422])
@require_auth
@validate_request(UpdateProjectRequest)
def update_project(user: User, data: UpdateProjectRequest, project_id: str) -> dict[str, object]:
    """Rename (owner only) or change the instructions (any member)."""
    project = _owned_project(user, project_id) if data.name is not None else None
    project = project or _member_project(user, project_id)
    name = _clean_name(data.name) if data.name is not None else None
    instructions = data.instructions.strip() if data.instructions is not None else None
    if not db.update_project(project.id, user.id, name=name, instructions=instructions):
        raise_not_found_error("Project")
    logger.info(
        "Project updated",
        extra={
            "user_id": user.id,
            "project_id": project.id,
            "renamed": name is not None,
            "instructions_chars": len(instructions) if instructions is not None else None,
        },
    )
    return _serialize(_member_project(user, project.id), user)


@api.route("/projects/<project_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[403, 404])
@require_auth
def delete_project(user: User, project_id: str) -> tuple[dict[str, str], int]:
    """Delete a project (owner only): its chats return to the main lists."""
    project = _owned_project(user, project_id)
    db.delete_project(project.id, user.id)
    return {"status": "deleted"}, 200


@api.route("/projects/<project_id>/restore", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def restore_project(user: User, project_id: str) -> tuple[dict[str, str], int]:
    """Bring a deleted project back with its memory and documents."""
    if not db.restore_project(project_id, user.id):
        raise_not_found_error("Project")
    return {"status": "restored"}, 200


@api.route("/projects/<project_id>/conversations", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[404])
@require_auth
@validate_query(ConversationsPageQuery)
def list_project_conversations(
    user: User, query: ConversationsPageQuery, project_id: str
) -> dict[str, object]:
    """The caller's own chats in the project, newest first."""
    _member_project(user, project_id)
    limit = max(1, min(query.limit, Config.CONVERSATIONS_MAX_PAGE_SIZE))
    rows, next_cursor, has_more = db.list_project_conversations(
        project_id, user.id, limit=limit, cursor=query.cursor
    )
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": to_api(c.created_at),
                "updated_at": to_api(c.updated_at),
                "message_count": count,
                "read_count": c.read_message_count,
                "pinned": c.pinned or None,
                "project_id": c.project_id,
                "last_message_preview": preview,
            }
            for c, count, preview in rows
        ],
        "pagination": {"next_cursor": next_cursor, "has_more": has_more, "total_count": len(rows)},
    }


@api.route("/projects/<project_id>/members/<member_id>", methods=["PUT"])
@api.output(ProjectResponse)
@api.doc(responses=[403, 404])
@require_auth
def add_member(user: User, project_id: str, member_id: str) -> dict[str, object]:
    """Share the project with a family member (owner only); a newly added
    member gets a push notification."""
    project = _owned_project(user, project_id)
    already = member_id in project.member_ids
    if not db.add_project_member(project.id, user.id, member_id):
        raise_not_found_error("User")
    if not already:
        owner = (user.name or "").split()[0] or "Someone"
        send_push_to_user(
            member_id,
            title=f"{owner} shared {project.name} with you",
            body="Its instructions, memory and documents are in your sidebar now.",
            url=f"/#/projects/{project.id}",
            tag=f"project-{project.id}",
        )
    return _serialize(_member_project(user, project.id), user)


@api.route("/projects/<project_id>/members/<member_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[403, 404])
@require_auth
def remove_member(user: User, project_id: str, member_id: str) -> tuple[dict[str, str], int]:
    """Remove a member (owner), or leave (the member themself). The owner
    cannot leave their own project - they delete it instead."""
    project = _member_project(user, project_id)
    if user.id not in (project.owner_id, member_id):
        raise_auth_forbidden_error("Only the project's owner can remove other members.")
    if not db.remove_project_member(project.id, user.id, member_id):
        raise_not_found_error("Member")
    return {"status": "removed"}, 200


@conversations_api.route("/conversations/<conv_id>/project", methods=["PUT"])
@conversations_api.output(StatusResponse)
@conversations_api.doc(responses=[404])
@require_auth
@validate_request(MoveConversationRequest)
def move_conversation(
    user: User, data: MoveConversationRequest, conv_id: str
) -> tuple[dict[str, str], int]:
    """File a chat under a project, or take it out (project_id null)."""
    if not db.set_conversation_project(conv_id, user.id, data.project_id):
        raise_not_found_error("Conversation or project")
    return {"status": "moved"}, 200


@conversations_api.route("/conversations/bulk-move", methods=["POST"])
@conversations_api.output(BulkMoveResponse)
@conversations_api.doc(responses=[400, 404])
@require_auth
@validate_request(BulkMoveRequest)
def bulk_move_conversations(user: User, data: BulkMoveRequest) -> dict[str, list[str]]:
    """Move many chats into a project (or out of one) in one transaction."""
    if data.project_id is not None:
        _member_project(user, data.project_id)
    moved = db.move_conversations(
        user.id,
        data.project_id,
        data.ids,
        all_before=data.created_before if data.all else None,
        exclude_ids=data.exclude_ids,
    )
    return {"moved_ids": moved}
