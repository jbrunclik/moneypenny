"""When the background memory review runs (src/api/helpers/memory_review_trigger.py)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage

from src.agent.memory_review import ReviewResult
from src.api.helpers import memory_review_trigger as trigger
from src.config import Config
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class _Reviewer:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.result = ReviewResult(applied=["Ema - ballet on Tuesdays"], input_tokens=1000)
        self.error: Exception | None = None

    def __call__(self, user_id: str, conversation_id: str, messages: list[Any]) -> ReviewResult:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def reviewer(monkeypatch: pytest.MonkeyPatch, test_database: Database) -> _Reviewer:
    fake = _Reviewer()
    monkeypatch.setattr(trigger, "db", test_database)
    monkeypatch.setattr(trigger, "review_messages", fake)
    monkeypatch.setattr(trigger, "_start", lambda fn: fn())
    monkeypatch.setattr(Config, "MEMORY_REVIEW_ENABLED", True)
    monkeypatch.setattr(Config, "MEMORY_REVIEW_EVERY_TURNS", 6)
    monkeypatch.setattr(Config, "MEMORY_REVIEW_MAX_TURNS", 12)
    return fake


def _turn(db: Database, conv: Conversation, i: int, tools: list[str] | None = None) -> str:
    """Save one user turn and its reply, then tell the trigger."""
    db.add_message(conv.id, MessageRole.USER, f"question {i}")
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, f"answer {i}")
    calls = [{"name": name, "args": {}, "id": f"c{i}"} for name in tools or []]
    trigger.note_turn(conv.id, conv.user_id, reply.id, [AIMessage(content="", tool_calls=calls)])
    return reply.id


def _state(db: Database, conv: Conversation) -> dict[str, Any]:
    raw = db.kv_get(conv.user_id, trigger.KV_NAMESPACE, conv.id)
    return json.loads(raw) if raw else {}


def _note(db: Database, conv: Conversation, message_id: str) -> str | None:
    return next(m.memory_note for m in db.get_messages(conv.id) if m.id == message_id)


def test_counts_turns_and_fires_at_threshold(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    ids = [_turn(test_database, test_conversation, i) for i in range(5)]
    assert reviewer.calls == []
    assert _state(test_database, test_conversation)["turns"] == 5

    sixth = _turn(test_database, test_conversation, 5)

    assert len(reviewer.calls) == 1
    assert len(reviewer.calls[0]) == 12
    assert _note(test_database, test_conversation, sixth) == "Ema - ballet on Tuesdays"
    assert _note(test_database, test_conversation, ids[0]) is None
    assert _state(test_database, test_conversation)["turns"] == 0


def test_manage_memory_turn_resets_counter_keeps_cursor(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    for i in range(4):
        _turn(test_database, test_conversation, i)
    _turn(test_database, test_conversation, 4, tools=["manage_memory"])

    state = _state(test_database, test_conversation)
    assert state["turns"] == 0
    assert state.get("cursor") is None

    for i in range(5, 11):
        _turn(test_database, test_conversation, i)
    # The pass still reads the turns before the agent's own memory call
    assert reviewer.calls[0][0].content == "question 0"


def test_review_reads_from_cursor_capped_at_max_turns(
    reviewer: _Reviewer,
    test_database: Database,
    test_conversation: Conversation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Config, "MEMORY_REVIEW_EVERY_TURNS", 20)
    for i in range(20):
        _turn(test_database, test_conversation, i)

    [messages] = reviewer.calls
    assert len(messages) == 24
    assert messages[0].content == "question 8"
    assert messages[-1].content == "answer 19"


def test_cursor_moves_to_last_reviewed_message_on_success(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    last = [_turn(test_database, test_conversation, i) for i in range(6)][-1]
    assert _state(test_database, test_conversation)["cursor"] == last

    for i in range(6, 12):
        _turn(test_database, test_conversation, i)
    assert reviewer.calls[1][0].content == "question 6"


def test_failure_keeps_cursor_and_never_raises(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    reviewer.error = RuntimeError("model down")
    for i in range(6):
        _turn(test_database, test_conversation, i)

    state = _state(test_database, test_conversation)
    assert state.get("cursor") is None
    assert state["turns"] == 0


def test_all_rejected_moves_cursor_without_label(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    reviewer.result = ReviewResult()
    last = [_turn(test_database, test_conversation, i) for i in range(6)][-1]

    assert _note(test_database, test_conversation, last) is None
    assert _state(test_database, test_conversation)["cursor"] == last


def test_second_pass_skipped_while_one_runs(
    reviewer: _Reviewer,
    test_database: Database,
    test_conversation: Conversation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held: list[Callable[[], None]] = []
    monkeypatch.setattr(trigger, "_start", held.append)
    for i in range(12):
        _turn(test_database, test_conversation, i)

    assert len(held) == 1
    held[0]()
    assert len(reviewer.calls) == 1


@pytest.mark.parametrize("kind", ["anonymous", "planning", "disabled", "agent"])
def test_skips_anonymous_planning_and_disabled(
    kind: str,
    reviewer: _Reviewer,
    test_database: Database,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if kind == "disabled":
        monkeypatch.setattr(Config, "MEMORY_REVIEW_ENABLED", False)
        conv = test_database.create_conversation(test_user.id, "chat")
    elif kind == "anonymous":
        conv = test_database.create_conversation(test_user.id, "chat")
        test_database.set_conversation_anonymous_mode(conv.id, test_user.id, True)
    elif kind == "agent":
        # Agent runs save their trigger (with another agent's text) as user
        # messages: never a source of memories
        agent = test_database.create_agent(test_user.id, "Watcher", "Watch VWCE")
        conv = test_database.get_conversation(agent.conversation_id, test_user.id)
        assert conv is not None
    else:
        conv = test_database.get_or_create_planner_conversation(test_user.id)
    for i in range(6):
        _turn(test_database, conv, i)

    assert reviewer.calls == []
    assert _state(test_database, conv) == {}


def test_records_cost_on_the_triggering_reply(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    for i in range(5):
        _turn(test_database, test_conversation, i)
    test_database.add_message(test_conversation.id, MessageRole.USER, "q")
    reply = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "a")
    test_database.save_message_cost(
        reply.id, test_conversation.id, test_conversation.user_id, "m", 1, 1, 0.01
    )

    trigger.note_turn(test_conversation.id, test_conversation.user_id, reply.id, [])

    cost = test_database.get_message_cost(reply.id)
    assert cost is not None and cost["cost_usd"] > 0.01


def test_deleted_cursor_falls_back_to_its_time(
    reviewer: _Reviewer, test_database: Database, test_conversation: Conversation
) -> None:
    """A regenerate deletes the reviewed reply: the next pass starts after its
    time, not from the beginning (no reread, no duplicate adds)."""
    last = [_turn(test_database, test_conversation, i) for i in range(6)][-1]
    test_database.delete_message(last, test_conversation.user_id)

    for i in range(6, 12):
        _turn(test_database, test_conversation, i)

    assert reviewer.calls[1][0].content == "question 6"
