"""Project schemas: folders of chats with shared instructions, memory and documents."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel, Timestamp
from src.api.schemas.conversations import BulkTrashRequest
from src.api.schemas.documents import SavedDocumentResponse
from src.api.schemas.memory import MemoryResponse
from src.config import Config


class ProjectResponse(ResponseModel):
    """A project as the caller sees it (counts are of their own chats)."""

    id: str
    name: str
    owner_id: str
    is_owner: bool
    shared: bool = Field(description="Has members besides the owner")
    member_names: list[str]
    member_ids: list[str]
    chat_count: int = Field(default=0, description="The caller's own chats in the project")
    unread_count: int = Field(default=0, description="Unread messages in the caller's chats")
    created_at: Timestamp
    updated_at: Timestamp
    deleted_at: Timestamp | None = None


class ProjectsListResponse(ResponseModel):
    """The caller's projects (owned or shared with them)."""

    projects: list[ProjectResponse]
    limit: int = Field(description="Maximum projects a user may own")


class DeletedProjectsResponse(ResponseModel):
    """The caller's deleted projects, still restorable."""

    projects: list[ProjectResponse]


class ProjectMemoryResponse(MemoryResponse):
    """A project memory with its author's name."""

    author_name: str | None = None


class ProjectDocumentResponse(SavedDocumentResponse):
    """A project document with its author's name."""

    author_name: str | None = None


class ProjectDetailResponse(ResponseModel):
    """One project with its instructions, memory and documents."""

    project: ProjectResponse
    instructions: str
    memories: list[ProjectMemoryResponse]
    documents: list[ProjectDocumentResponse]
    deleted_memories: list[ProjectMemoryResponse] = Field(
        default_factory=list, description="Soft-deleted, restorable until the purge"
    )
    deleted_documents: list[ProjectDocumentResponse] = Field(
        default_factory=list, description="Soft-deleted, restorable until the purge"
    )
    instructions_limit: int = Field(description="PROJECT_INSTRUCTIONS_MAX_CHARS")
    memory_limit: int = Field(description="PROJECT_MEMORY_MAX_ENTRIES")
    documents_limit: int = Field(description="PROJECT_DOCUMENTS_MAX_ENTRIES")


class CreateProjectRequest(RequestModel):
    """Schema for POST /api/projects."""

    name: str = Field(min_length=1, max_length=Config.PROJECT_NAME_MAX_CHARS)
    instructions: str = Field(default="", max_length=Config.PROJECT_INSTRUCTIONS_MAX_CHARS)


class UpdateProjectRequest(RequestModel):
    """Schema for PATCH /api/projects/<id> (name: owner only)."""

    name: str | None = Field(default=None, min_length=1, max_length=Config.PROJECT_NAME_MAX_CHARS)
    instructions: str | None = Field(default=None, max_length=Config.PROJECT_INSTRUCTIONS_MAX_CHARS)


class PersonResponse(ResponseModel):
    """A family member who can be added to a project."""

    id: str
    name: str
    picture: str | None = None


class PeopleResponse(ResponseModel):
    """The deployment's other users."""

    people: list[PersonResponse]


class MoveConversationRequest(RequestModel):
    """Schema for PUT /api/conversations/<id>/project (null takes it out)."""

    project_id: str | None = None


class BulkMoveRequest(BulkTrashRequest):
    """Move many chats into a project (or out of one, with null): hand-picked
    ids, or every unpinned main-list chat (all) minus exclude_ids plus ids."""

    project_id: str | None = None


class BulkMoveResponse(ResponseModel):
    """The chats that moved."""

    moved_ids: list[str]
