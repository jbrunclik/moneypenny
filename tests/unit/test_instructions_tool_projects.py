"""propose_instruction_change in a project chat (decided with Jiri, 1A): a
project-scoped card changes the project's instructions, not the user's."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.proposals import resolve
from src.agent.tool_results import set_current_request_id
from src.agent.tools.context import set_conversation_context
from src.agent.tools.instructions_tool import propose_instruction_change
from src.db.models import use_database
from src.enums import MessageRole
from src.utils.clock import local_today

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Project, Proposal, User

RULE = "No emoji in posts for this client."
_APPEND = {"instructions": {"op": "append", "new": RULE}}


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Hanák", "LinkedIn posts, friendly tone.")


@pytest.fixture
def project_chat(
    test_database: Database, test_user: User, project: Project
) -> Iterator[Conversation]:
    with use_database(test_database):
        test_database.update_user_custom_instructions(test_user.id, "Answer in Czech.")
        conv = test_database.create_conversation(test_user.id, "Posts", project_id=project.id)
        test_database.add_message(conv.id, MessageRole.USER, "no emoji for this client from now on")
        set_conversation_context(conv.id, test_user.id)
        set_current_request_id("turn-1")
        yield conv
        set_conversation_context(None, None)
        set_current_request_id(None)


def _propose(scope: str, change: dict[str, Any] | None = None) -> str:
    return str(
        propose_instruction_change.invoke(
            {
                "change": json.dumps(change if change is not None else _APPEND),
                "evidence": [
                    f"{local_today().isoformat()}: 'no emoji for this client from now on'"
                ],
                "reason": "You asked for no emoji for this client.",
                "scope": scope,
            }
        )
    )


def _card(db: Database, conv: Conversation) -> Proposal:
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Noted.")
    db.link_proposals("turn-1", reply.id)
    [card] = db.pending_proposals(conv.id)
    return card


def test_card_project_scope_names_project(
    project_chat: Conversation, test_database: Database
) -> None:
    assert _propose("project").startswith("PROPOSAL")
    card = _card(test_database, project_chat)
    assert "Hanák" in card.details["Applies to"]
    assert "Hanák" in card.summary


def test_accept_project_card_updates_project_instructions(
    project_chat: Conversation, test_database: Database, test_user: User, project: Project
) -> None:
    _propose("project")
    answered = resolve(_card(test_database, project_chat), 0, "button")

    assert answered.state == "approved"
    got = test_database.get_project(project.id, test_user.id)
    assert got is not None
    assert got.instructions == f"LinkedIn posts, friendly tone.\n\n{RULE}"
    user = test_database.get_user_by_id(test_user.id)
    assert user is not None
    assert user.custom_instructions == "Answer in Czech."


def test_stale_project_card_fails_with_reason(
    project_chat: Conversation, test_database: Database, test_user: User, project: Project
) -> None:
    _propose(
        "project",
        {"instructions": {"op": "replace", "old": "friendly tone", "new": "formal tone"}},
    )
    card = _card(test_database, project_chat)
    test_database.update_project(project.id, test_user.id, instructions="Short posts.")

    answered = resolve(card, 0, "button")

    assert answered.state == "failed"
    got = test_database.get_project(project.id, test_user.id)
    assert got is not None
    assert got.instructions == "Short posts."


def test_project_scope_outside_project_refused(test_database: Database, test_user: User) -> None:
    with use_database(test_database):
        conv = test_database.create_conversation(test_user.id, "Plain")
        test_database.add_message(conv.id, MessageRole.USER, "no emoji from now on")
        set_conversation_context(conv.id, test_user.id)
        try:
            result = _propose("project")
        finally:
            set_conversation_context(None, None)
    assert "not in a project" in result


def test_memory_edit_with_project_scope_refused(project_chat: Conversation) -> None:
    change = {**_APPEND, "memory": {"op": "delete", "id": "abcd1234"}}
    assert "project" in _propose("project", change)
    assert not _propose("project", change).startswith("PROPOSAL")


def test_personal_scope_unchanged_in_project_chat(
    project_chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose("personal")
    resolve(_card(test_database, project_chat), 0, "button")
    user = test_database.get_user_by_id(test_user.id)
    assert user is not None
    assert user.custom_instructions == f"Answer in Czech.\n\n{RULE}"


_ = timedelta
