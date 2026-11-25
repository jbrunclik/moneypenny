"""The background memory review in a project chat: project facts go to the
project, and a shared project's privacy rule is in its prompt."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from src.agent import flex, memory_review
from src.agent.memory_review import build_prompt, format_note, review_messages
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Database, Project, User


class _FakeModels:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.prompts.append(contents)
        usage = SimpleNamespace(
            prompt_token_count=900, candidates_token_count=40, thoughts_token_count=0
        )
        return SimpleNamespace(text=self.reply, usage_metadata=usage)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch, test_database: Database) -> _FakeModels:
    import src.agent.tools.memory as memory_module

    monkeypatch.setattr(memory_module, "db", test_database)
    monkeypatch.setattr(memory_review, "db", test_database)
    models = _FakeModels("[]")
    monkeypatch.setattr(
        memory_review, "shared_genai_client", lambda: SimpleNamespace(models=models)
    )
    monkeypatch.setattr(flex, "shared_genai_client", lambda: SimpleNamespace(models=models))
    return models


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Home")


def _messages(db: Database, user: User, project: Project | None) -> tuple[str, list[Any]]:
    conv = db.create_conversation(user.id, "Wallbox", project_id=project.id if project else None)
    db.add_message(conv.id, MessageRole.USER, "The garage has 3-phase power. I'm on antibiotics.")
    db.add_message(conv.id, MessageRole.ASSISTANT, "Noted.")
    return conv.id, db.get_messages(conv.id)


def test_review_prompt_lists_project_memories_and_rule_when_shared(
    fake_model: _FakeModels, test_database: Database, test_user: User, project: Project
) -> None:
    jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
    test_database.add_project_member(project.id, test_user.id, jana.id)
    shared = test_database.get_project(project.id, test_user.id)
    assert shared is not None
    _conv_id, messages = _messages(test_database, test_user, project)

    prompt = build_prompt(test_user.id, messages, shared)

    assert 'This chat is in the project "Home"' in prompt
    assert '"scope": "project"' in prompt
    assert "family members read" in prompt


def test_review_prompt_has_no_project_block_outside_projects(
    fake_model: _FakeModels, test_database: Database, test_user: User
) -> None:
    _conv_id, messages = _messages(test_database, test_user, None)
    prompt = build_prompt(test_user.id, messages, None)
    assert "This chat is in the project" not in prompt


def test_review_project_op_applies_to_project(
    fake_model: _FakeModels, test_database: Database, test_user: User, project: Project
) -> None:
    fake_model.reply = json.dumps(
        [
            {
                "action": "add",
                "content": "Garage has 3-phase power",
                "category": "fact",
                "scope": "project",
            },
            {"action": "add", "content": "On antibiotics this week", "category": "context"},
        ]
    )
    conv_id, messages = _messages(test_database, test_user, project)

    result = review_messages(test_user.id, conv_id, messages, project)

    assert [m.content for m in test_database.list_project_memories(project.id)] == [
        "Garage has 3-phase power"
    ]
    assert [m.content for m in test_database.list_memories(test_user.id)] == [
        "On antibiotics this week"
    ]
    assert result.project_applied == ["Garage has 3-phase power"]


def test_review_scope_project_outside_project_dropped(
    fake_model: _FakeModels, test_database: Database, test_user: User
) -> None:
    fake_model.reply = json.dumps(
        [
            {
                "action": "add",
                "content": "Garage has 3-phase power",
                "category": "fact",
                "scope": "project",
            }
        ]
    )
    conv_id, messages = _messages(test_database, test_user, None)

    result = review_messages(test_user.id, conv_id, messages, None)

    assert result.applied == []
    assert test_database.list_memories(test_user.id) == []


def test_note_names_project() -> None:
    assert format_note(["Garage has 3-phase power"], project_name="Home").startswith("shared in Home")


def test_review_patch_of_project_memory_counts_as_project_write(
    fake_model: _FakeModels, test_database: Database, test_user: User, project: Project
) -> None:
    from src.db.models.memory import MemoryWrite

    [memory_id] = test_database.apply_memory_batch(
        test_user.id,
        None,
        [
            MemoryWrite(
                action="add", content="Breaker is 16 A", category="fact", project_id=project.id
            )
        ],
        project_id=project.id,
    )
    assert memory_id is not None
    fake_model.reply = json.dumps(
        [{"action": "patch", "id": memory_id[:8], "old_text": "16 A", "new_text": "32 A"}]
    )
    conv_id, messages = _messages(test_database, test_user, project)

    result = review_messages(test_user.id, conv_id, messages, project)

    assert result.project_applied == ["Breaker is 32 A"]


def test_review_note_labels_only_the_project_items_and_only_when_shared() -> None:
    from src.agent.memory_review import ReviewResult, review_note

    result = ReviewResult(
        applied=["Likes tea", "Garage 3-phase"], project_applied=["Garage 3-phase"]
    )
    assert review_note(result, "Home", shared=True) == (
        "Likes tea; " + format_note(["Garage 3-phase"], project_name="Home")
    )
    assert review_note(result, "Home", shared=False) == "Likes tea, Garage 3-phase"
