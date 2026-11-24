"""Projects tool: the agent creates projects, files chats under them, and
sets their instructions (docs/superpowers/specs/2026-11-24-projects-design.md).

Sharing and deleting are not here on purpose: who can read a project's
memory is decided by a person on the project page, never by a turn that may
have read planted web content. Lasting corrections to a project's rules go
through propose_instruction_change's card; set_instructions is for when the
user asks for the instructions outright.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.db.models import Project, db
from src.db.models.projects import ProjectWriteError
from src.utils.logging import get_logger
from src.utils.memory_ids import short_memory_id
from src.utils.threat_patterns import find_injection

logger = get_logger(__name__)

_NEXT_TURN = "This chat is in the project from your next reply on."


class ProjectOp(BaseModel):
    """One manage_project operation (fields per op: see the tool)."""

    op: Literal["list", "create", "move_chat", "remove_chat", "rename", "set_instructions"]
    project: str = ""
    name: str = ""
    instructions: str = ""
    chat: str = ""
    move_current_chat: bool = True


class _RejectedError(Exception):
    """An operation the tool refuses; the message says why."""


def _log(op: str, project_id: str | None, result: str) -> None:
    _, user_id = get_conversation_context()
    logger.info(
        "Project tool",
        extra={"user_id": user_id, "op": op, "project_id": project_id, "result": result},
    )


def _checked_text(value: str, limit: int, label: str, required: bool) -> str:
    text = value.strip() if label == "instructions" else " ".join(value.split())
    if required and not text:
        raise _RejectedError(f"{label} is required")
    if len(text) > limit:
        raise _RejectedError(f"{label} is {len(text)} characters, the limit is {limit}")
    if reason := find_injection(text):
        raise _RejectedError(f"{label} looks like an instruction injection ({reason})")
    return text


def _find_project(user_id: str, ref: str) -> Project:
    wanted = " ".join(ref.split()).casefold()
    if not wanted:
        raise _RejectedError("project is required (its id or exact name)")
    projects = [s.project for s in db.list_projects(user_id)]
    by_id = [p for p in projects if p.id == ref.strip() or short_memory_id(p.id) == ref.strip()]
    found = by_id or [p for p in projects if p.name.casefold() == wanted]
    if len(found) != 1:
        names = ", ".join(f"{p.name} ({short_memory_id(p.id)})" for p in projects) or "none"
        raise _RejectedError(f"no single project matches '{ref}'. The user's projects: {names}")
    return found[0]


def _chat_id(op: ProjectOp, conversation_id: str | None) -> str:
    chat_id = op.chat.strip() or conversation_id
    if not chat_id:
        raise _RejectedError("no chat to move")
    return chat_id


def _moved_line(chat_id: str, conversation_id: str | None, verb: str, where: str) -> str:
    suffix = f" {_NEXT_TURN}" if chat_id == conversation_id and verb == "MOVED" else ""
    return f"{verb}: chat {chat_id} {where}.{suffix}"


def _create(op: ProjectOp, user_id: str, conversation_id: str | None) -> str:
    name = _checked_text(op.name, Config.PROJECT_NAME_MAX_CHARS, "name", required=True)
    instructions = _checked_text(
        op.instructions, Config.PROJECT_INSTRUCTIONS_MAX_CHARS, "instructions", required=False
    )
    try:
        project = db.create_project(user_id, name, instructions)
    except ProjectWriteError as e:
        raise _RejectedError(str(e)) from e
    line = f"CREATED: project {short_memory_id(project.id)} '{project.name}'."
    if op.move_current_chat and conversation_id:
        if db.set_conversation_project(conversation_id, user_id, project.id):
            line += f" {_NEXT_TURN}"
        else:
            line += " This chat cannot be filed under a project (not an ordinary chat)."
    _log("create", project.id, "ok")
    return line


def _move(op: ProjectOp, user_id: str, conversation_id: str | None) -> str:
    project = _find_project(user_id, op.project)
    chat_id = _chat_id(op, conversation_id)
    if not db.set_conversation_project(chat_id, user_id, project.id):
        raise _RejectedError(
            "that chat cannot be filed under a project (not the user's own ordinary chat)"
        )
    _log("move_chat", project.id, "ok")
    return _moved_line(chat_id, conversation_id, "MOVED", f"to '{project.name}'")


def _remove(op: ProjectOp, user_id: str, conversation_id: str | None) -> str:
    chat_id = _chat_id(op, conversation_id)
    if not db.set_conversation_project(chat_id, user_id, None):
        raise _RejectedError("no such chat of the user's")
    _log("remove_chat", None, "ok")
    return _moved_line(chat_id, conversation_id, "REMOVED", "from its project")


def _rename(op: ProjectOp, user_id: str) -> str:
    project = _find_project(user_id, op.project)
    name = _checked_text(op.name, Config.PROJECT_NAME_MAX_CHARS, "name", required=True)
    if project.owner_id != user_id or not db.update_project(project.id, user_id, name=name):
        raise _RejectedError("only the project's owner can rename it")
    _log("rename", project.id, "ok")
    return f"RENAMED: project {short_memory_id(project.id)} is now '{name}'."


def _set_instructions(op: ProjectOp, user_id: str) -> str:
    project = _find_project(user_id, op.project)
    text = _checked_text(
        op.instructions, Config.PROJECT_INSTRUCTIONS_MAX_CHARS, "instructions", required=False
    )
    if not db.update_project(project.id, user_id, instructions=text):
        raise _RejectedError("the project could not be updated")
    _log("set_instructions", project.id, "ok")
    return f"UPDATED: the instructions of '{project.name}' ({len(text)} characters)."


def _list(user_id: str) -> str:
    summaries = db.list_projects(user_id)
    if not summaries:
        return "No projects yet."
    return "\n".join(
        f"- {short_memory_id(s.project.id)} | {s.project.name} | "
        f"{'shared' if s.project.shared else 'solo'} | {s.chat_count} chats"
        for s in summaries
    )


def _run(op: ProjectOp, user_id: str, conversation_id: str | None) -> str:
    try:
        if op.op == "list":
            return _list(user_id)
        if op.op == "create":
            return _create(op, user_id, conversation_id)
        if op.op == "move_chat":
            return _move(op, user_id, conversation_id)
        if op.op == "remove_chat":
            return _remove(op, user_id, conversation_id)
        if op.op == "rename":
            return _rename(op, user_id)
        return _set_instructions(op, user_id)
    except _RejectedError as e:
        _log(op.op, None, "rejected")
        return f"REJECTED ({op.op}): {e}"


@tool
def manage_project(operations: list[ProjectOp]) -> str:
    """List, create and rename the user's projects (folders of chats with their
    own instructions and memory), file chats under them, and set a project's
    instructions. Act when the user asks; when a chat clearly belongs to one of
    their projects, or a topic keeps coming back, offer first and act only after
    a yes. Sharing and deleting projects are done by the user on the project page.

    Args:
        operations: Each has an "op":
            - "list": the user's projects (id, name, shared/solo, chats)
            - "create": "name"; optional "instructions" (draft them from the chat
              when the user asks), "move_current_chat" (default true)
            - "move_chat": "project" (id or exact name); optional "chat" (a
              conversation id; default this chat)
            - "remove_chat": optional "chat" (default this chat)
            - "rename": "project", "name" (owner only)
            - "set_instructions": "project", "instructions" (replaces them all;
              only when the user asks for it)

    Returns:
        One line per operation: CREATED/MOVED/REMOVED/RENAMED/UPDATED or the
        list, or REJECTED with the reason.
    """
    check_autonomous_permission("manage_project", {"operation_count": len(operations)})
    conversation_id, user_id = get_conversation_context()
    if not user_id:
        return tool_error("No user context available, nothing was changed.", retriable=False)
    if not operations:
        return "No operations submitted."
    limit = Config.PROJECT_MAX_OPS_PER_CALL
    if len(operations) > limit:
        return (
            f"REJECTED (batch): {len(operations)} operations, the limit is {limit}. "
            "Nothing was applied."
        )
    return "\n".join(_run(op, user_id, conversation_id) for op in operations)
