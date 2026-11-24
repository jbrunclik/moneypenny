"""search_conversations in a project chat: this project's chats first."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.conversation_search import search_conversations

if TYPE_CHECKING:
    from flask import Flask

    from src.db.models import Conversation, Database, Project, User


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Bikes")


def _chat(
    db: Database, user: User, title: str, text: str, project_id: str | None = None
) -> Conversation:
    conv = db.create_conversation(user.id, title, project_id=project_id)
    db.add_message(conv.id, "user", text)
    return conv


@pytest.fixture
def current(
    app: Flask, test_database: Database, test_user: User, project: Project
) -> Generator[Conversation]:
    conv = _chat(test_database, test_user, "Current", "now", project.id)
    set_conversation_context(conv.id, test_user.id)
    yield conv
    set_conversation_context(None, None)


def _search(query: str, **kw: object) -> str:
    return str(search_conversations.invoke({"query": query, **kw}))


def test_search_project_first_then_other(
    test_database: Database, test_user: User, project: Project, current: Conversation
) -> None:
    _chat(test_database, test_user, "Tyre talk elsewhere", "gravel tyres for the trip")
    _chat(
        test_database, test_user, "Tyre talk in project", "gravel tyres for the Grizl", project.id
    )

    result = _search("gravel tyres")

    assert result.index("Tyre talk in project") < result.index("Tyre talk elsewhere")
    assert "(this project)" in result
    assert "(other)" in result


def test_search_scope_all_unchanged(
    test_database: Database, test_user: User, project: Project, current: Conversation
) -> None:
    _chat(test_database, test_user, "Tyre talk in project", "gravel tyres", project.id)
    result = _search("gravel tyres", scope="all")
    assert "(this project)" not in result
    assert "Tyre talk in project" in result


def test_search_never_returns_other_members_chats(
    test_database: Database, test_user: User, project: Project, current: Conversation
) -> None:
    jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
    test_database.add_project_member(project.id, test_user.id, jana.id)
    _chat(test_database, jana, "Jana's tyre chat", "gravel tyres secret", project.id)

    assert "Jana's tyre chat" not in _search("gravel tyres")


def test_listing_puts_project_chats_first(
    test_database: Database, test_user: User, project: Project, current: Conversation
) -> None:
    _chat(test_database, test_user, "In project", "a", project.id)
    _chat(test_database, test_user, "Newer elsewhere", "b")

    result = _search("")

    assert result.index("In project") < result.index("Newer elsewhere")
