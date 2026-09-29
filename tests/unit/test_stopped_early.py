"""Replies cut off by the tool-round cap are flagged `stopped_early`.

When a turn hits AGENT_MAX_TOOL_ROUNDS the model is told to stop and answer
with what it has (Sep 2026: 3.3% of turns). The flag lets the UI say so and
offer Continue instead of presenting a partial answer as complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from src.api.schemas import MessageRole
from src.api.utils import build_stream_done_event, is_round_capped, serialize_messages_for_response
from src.config import Config
from src.db.models.dataclasses import Message

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


@pytest.fixture
def cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 6)
    return 6


class TestIsRoundCapped:
    def test_at_and_above_cap(self, cap: int) -> None:
        assert is_round_capped(6)
        assert is_round_capped(7)
        assert not is_round_capped(5)
        assert not is_round_capped(0)

    def test_disabled_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "AGENT_MAX_TOOL_ROUNDS", 0)
        assert not is_round_capped(50)


class TestSerializedMessages:
    def test_flags_capped_assistant_messages(
        self,
        cap: int,
        test_database: Database,
        test_conversation: Conversation,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.api.utils as utils

        monkeypatch.setattr(utils, "db", test_database)
        capped = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "partial")
        normal = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "complete")
        for msg, rounds in ((capped, 6), (normal, 2)):
            test_database.save_message_cost(
                msg.id, test_conversation.id, test_user.id, "m", 10, 10, 0.0, tool_rounds=rounds
            )

        serialized = serialize_messages_for_response(
            test_database.get_messages(test_conversation.id)
        )

        by_id = {m["id"]: m for m in serialized}
        assert by_id[capped.id]["stopped_early"] is True
        assert "stopped_early" not in by_id[normal.id]

    def test_filters_empty_placeholders(self, cap: int, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.api.utils as utils

        monkeypatch.setattr(utils.db, "get_round_capped_message_ids", lambda ids, rounds: set())
        placeholder = Message(
            id="p",
            conversation_id="c",
            role=MessageRole.ASSISTANT,
            content="",
            created_at=datetime.now(),
        )
        assert serialize_messages_for_response([placeholder]) == []


class TestDoneEvent:
    def test_done_event_carries_flag(self) -> None:
        msg = Message(
            id="a",
            conversation_id="c",
            role=MessageRole.ASSISTANT,
            content="x",
            created_at=datetime.now(),
        )
        assert build_stream_done_event(msg, [], [], [], stopped_early=True)["stopped_early"] is True
        assert "stopped_early" not in build_stream_done_event(msg, [], [], [])
