"""The background memory review pass (src/agent/memory_review.py)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from src.agent import memory_review
from src.agent.memory_review import format_note, parse_ops, review_messages
from src.config import Config
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


def test_parse_ops_fenced_json() -> None:
    text = '```json\n[{"action": "add", "content": "Owns a beagle", "category": "fact"}]\n```'
    assert parse_ops(text) == [{"action": "add", "content": "Owns a beagle", "category": "fact"}]


def test_parse_ops_drops_delete_and_unknown() -> None:
    text = json.dumps(
        [
            {"action": "delete", "id": "m1"},
            {"action": "update", "id": "m1"},
            "add",
            {"action": "patch", "id": "m1", "old_text": "a", "new_text": "b"},
        ]
    )
    assert parse_ops(text) == [{"action": "patch", "id": "m1", "old_text": "a", "new_text": "b"}]


def test_parse_ops_caps_at_max_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "MEMORY_REVIEW_MAX_OPS", 2)
    ops = [{"action": "add", "content": f"fact {i}", "category": "fact"} for i in range(5)]
    assert len(parse_ops(json.dumps(ops))) == 2


@pytest.mark.parametrize("text", ["sure!", '{"action": "add"}', "", "[1, 2"])
def test_parse_ops_garbage_is_empty(text: str) -> None:
    assert parse_ops(text) == []


def test_format_note_one_two_and_more() -> None:
    assert format_note(["A"]) == "A"
    assert format_note(["A", "B"]) == "A, B"
    assert format_note(["A", "B", "C"]) == "A, B, and 1 more"


def test_format_note_truncates_long_items() -> None:
    note = format_note(["x" * 100])
    assert len(note) == 60
    assert note.endswith("…")


class _FakeModels:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.prompts.append(contents)
        return SimpleNamespace(
            text=self.reply,
            usage_metadata=SimpleNamespace(prompt_token_count=900, candidates_token_count=40),
        )


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch, test_database: Database) -> _FakeModels:
    import src.agent.tools.memory as memory_module

    monkeypatch.setattr(memory_module, "db", test_database)
    monkeypatch.setattr(memory_review, "db", test_database)
    models = _FakeModels("[]")
    monkeypatch.setattr(
        memory_review, "shared_genai_client", lambda: SimpleNamespace(models=models)
    )
    return models


def _chat(db: Database, conv: Conversation) -> list[Any]:
    db.add_message(conv.id, MessageRole.USER, "Dinner ideas? Ema has ballet every Tuesday.")
    db.add_message(conv.id, MessageRole.ASSISTANT, "How about risotto?")
    return db.get_messages(conv.id)


def test_review_messages_builds_prompt_with_bank_and_deleted(
    fake_model: _FakeModels,
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    kept = test_database.add_memory(test_user.id, "Lives in Brno", "fact")
    gone = test_database.add_memory(test_user.id, "Plays chess", "context")
    test_database.delete_memory(gone.id, test_user.id)
    messages = _chat(test_database, test_conversation)
    messages.append(
        SimpleNamespace(
            role="tool", content="TOOL OUTPUT SECRET", id="t1", created_at=messages[-1].created_at
        )
    )

    review_messages(test_user.id, test_conversation.id, messages)

    [prompt] = fake_model.prompts
    assert kept.id in prompt and "Lives in Brno" in prompt
    assert "Plays chess" in prompt
    assert prompt.index("Plays chess") > prompt.index("do not re-add")
    assert "Ema has ballet every Tuesday" in prompt
    assert "TOOL OUTPUT SECRET" not in prompt


def test_review_messages_applies_each_op_independently(
    fake_model: _FakeModels,
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    fake_model.reply = json.dumps(
        [
            {"action": "patch", "id": "missing", "old_text": "a", "new_text": "b"},
            {"action": "add", "content": "Ema - ballet on Tuesdays", "category": "fact"},
        ]
    )

    result = review_messages(
        test_user.id, test_conversation.id, _chat(test_database, test_conversation)
    )

    assert result.applied == ["Ema - ballet on Tuesdays"]
    assert result.ops == [
        {"action": "add", "content": "Ema - ballet on Tuesdays", "category": "fact"}
    ]
    assert (result.input_tokens, result.output_tokens) == (900, 40)
