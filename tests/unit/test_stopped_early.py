"""Replies whose turn stopped early (a turn budget, or the old round cap) are
flagged `stopped_early`: the UI says so and offers Continue instead of
presenting a partial answer as complete. Why it stopped is stored as
message_costs.stopped_by (cost, time, rounds, loop)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from src.api.utils import build_stream_done_event, serialize_messages_for_response
from src.db.models.dataclasses import Message
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestSerializedMessages:
    def test_flags_capped_assistant_messages(
        self,
        test_database: Database,
        test_conversation: Conversation,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.api.utils as utils

        monkeypatch.setattr(utils, "db", test_database)
        capped = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "partial")
        normal = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "complete")
        for msg, stopped_by in ((capped, "time"), (normal, None)):
            test_database.save_message_cost(
                msg.id, test_conversation.id, test_user.id, "m", 10, 10, 0.0, stopped_by=stopped_by
            )

        serialized = serialize_messages_for_response(
            test_database.get_messages(test_conversation.id)
        )

        by_id = {m["id"]: m for m in serialized}
        assert by_id[capped.id]["stopped_early"] is True
        assert "stopped_early" not in by_id[normal.id]

    def test_filters_empty_placeholders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.api.utils as utils

        monkeypatch.setattr(utils.db, "get_stopped_early_message_ids", lambda ids: set())
        placeholder = Message(
            id="p",
            conversation_id="c",
            role=MessageRole.ASSISTANT,
            content="",
            created_at=datetime.now(UTC),
        )
        assert serialize_messages_for_response([placeholder]) == []


class TestDoneEvent:
    def test_done_event_carries_flag(self) -> None:
        msg = Message(
            id="a",
            conversation_id="c",
            role=MessageRole.ASSISTANT,
            content="x",
            created_at=datetime.now(UTC),
        )
        assert build_stream_done_event(msg, [], [], [], stopped_early=True)["stopped_early"] is True
        assert "stopped_early" not in build_stream_done_event(msg, [], [], [])
