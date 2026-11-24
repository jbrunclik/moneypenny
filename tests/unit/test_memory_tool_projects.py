"""manage_memory and search_memory in a project chat: the two scopes."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.memory import manage_memory, search_memory
from src.config import Config
from src.db.models.memory import MemoryWrite

if TYPE_CHECKING:
    from flask import Flask

    from src.db.models import Conversation, Database, Project, User


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Home")


@pytest.fixture
def project_chat(
    app: Flask, test_database: Database, test_user: User, project: Project
) -> Generator[Conversation]:
    conv = test_database.create_conversation(test_user.id, "Wallbox", project_id=project.id)
    set_conversation_context(conv.id, test_user.id)
    yield conv
    set_conversation_context(None, None)


@pytest.fixture
def plain_chat(app: Flask, test_database: Database, test_user: User) -> Generator[Conversation]:
    conv = test_database.create_conversation(test_user.id, "Plain")
    set_conversation_context(conv.id, test_user.id)
    yield conv
    set_conversation_context(None, None)


def _invoke(*operations: dict[str, object]) -> str:
    return str(manage_memory.invoke({"operations": list(operations)}))


def _project_memory(db: Database, user_id: str, project_id: str, content: str) -> str:
    [memory_id] = db.apply_memory_batch(
        user_id,
        None,
        [MemoryWrite(action="add", content=content, category="fact", project_id=project_id)],
        project_id=project_id,
    )
    assert memory_id is not None
    return memory_id


class TestScopes:
    def test_add_project_scope_in_project_chat(
        self, test_database: Database, test_user: User, project: Project, project_chat: Conversation
    ) -> None:
        result = _invoke(
            {
                "action": "add",
                "content": "Garage has 3-phase power",
                "category": "fact",
                "scope": "project",
            }
        )

        assert "added" in result
        assert "project" in result
        assert [m.content for m in test_database.list_project_memories(project.id)] == [
            "Garage has 3-phase power"
        ]
        assert test_database.list_memories(test_user.id) == []

    def test_default_scope_personal(
        self, test_database: Database, test_user: User, project: Project, project_chat: Conversation
    ) -> None:
        _invoke({"action": "add", "content": "Likes tea", "category": "preference"})

        assert [m.content for m in test_database.list_memories(test_user.id)] == ["Likes tea"]
        assert test_database.list_project_memories(project.id) == []

    def test_add_project_scope_outside_project_rejected(
        self, test_database: Database, test_user: User, plain_chat: Conversation
    ) -> None:
        result = _invoke(
            {"action": "add", "content": "Garage power", "category": "fact", "scope": "project"}
        )
        assert "REJECTED (add)" in result
        assert "not in a project" in result
        assert test_database.list_memories(test_user.id) == []

    def test_unknown_scope_rejected(self, project_chat: Conversation) -> None:
        result = _invoke(
            {"action": "add", "content": "x fact", "category": "fact", "scope": "family"}
        )
        assert "REJECTED (add)" in result

    def test_patch_project_memory_from_its_chat(
        self, test_database: Database, test_user: User, project: Project, project_chat: Conversation
    ) -> None:
        memory_id = _project_memory(test_database, test_user.id, project.id, "Breaker is 16 A")
        result = _invoke(
            {"action": "patch", "id": memory_id[:8], "old_text": "16 A", "new_text": "32 A"}
        )
        assert "patched" in result
        [memory] = test_database.list_project_memories(project.id)
        assert memory.content == "Breaker is 32 A"

    def test_patch_other_projects_memory_not_found(
        self, test_database: Database, test_user: User, project_chat: Conversation
    ) -> None:
        other = test_database.create_project(test_user.id, "Bikes")
        memory_id = _project_memory(test_database, test_user.id, other.id, "Rides a Canyon Grizl")
        result = _invoke({"action": "delete", "id": memory_id})
        assert "REJECTED (delete)" in result
        assert len(test_database.list_project_memories(other.id)) == 1

    def test_short_id_collision_names_both(
        self, test_database: Database, test_user: User, project: Project, project_chat: Conversation
    ) -> None:
        personal = test_database.add_memory(test_user.id, "Likes tea")
        project_id = _project_memory(test_database, test_user.id, project.id, "Garage power")
        # Force a shared prefix between the personal and the project memory
        shared = "abcd1234"
        for old, new in (
            (personal.id, f"{shared}-0000-4000-8000-000000000001"),
            (project_id, f"{shared}-0000-4000-8000-000000000002"),
        ):
            with test_database._pool.get_connection() as conn:
                conn.execute("UPDATE user_memories SET id = ? WHERE id = ?", (new, old))
                conn.commit()

        result = _invoke({"action": "delete", "id": shared})

        assert "matches 2 memories" in result
        assert f"{shared}-0000-4000-8000-000000000001" in result
        assert f"{shared}-0000-4000-8000-000000000002" in result

    def test_project_cap_rejects_add(
        self,
        test_database: Database,
        test_user: User,
        project: Project,
        project_chat: Conversation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Config, "PROJECT_MEMORY_MAX_ENTRIES", 1)
        _project_memory(test_database, test_user.id, project.id, "One")
        result = _invoke(
            {"action": "add", "content": "Two", "category": "fact", "scope": "project"}
        )
        assert "REJECTED (add)" in result
        assert "project memory" in result


class TestSearch:
    def test_search_tags_scopes(
        self, test_database: Database, test_user: User, project: Project, project_chat: Conversation
    ) -> None:
        test_database.add_memory(test_user.id, "Garage door code is personal")
        _project_memory(test_database, test_user.id, project.id, "Garage has 3-phase power")

        result = str(search_memory.invoke({"query": "garage"}))

        assert "(project) Garage has 3-phase power" in result
        assert "Garage door code is personal" in result
        assert "(project) Garage door code" not in result

    def test_search_never_returns_other_project(
        self, test_database: Database, test_user: User, project_chat: Conversation
    ) -> None:
        other = test_database.create_project(test_user.id, "Bikes")
        _project_memory(test_database, test_user.id, other.id, "Garage holds four bikes")

        assert "four bikes" not in str(search_memory.invoke({"query": "garage"}))

    def test_plain_chat_search_has_no_project_rows(
        self, test_database: Database, test_user: User, project: Project, plain_chat: Conversation
    ) -> None:
        _project_memory(test_database, test_user.id, project.id, "Garage has 3-phase power")
        assert "3-phase" not in str(search_memory.invoke({"query": "garage"}))
