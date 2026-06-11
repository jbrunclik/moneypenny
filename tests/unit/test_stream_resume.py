"""Unit tests for resumable streams: event journal + resume generator."""

from __future__ import annotations

import json
import queue
from typing import TYPE_CHECKING

import pytest

from src.api.schemas import MessageRole
from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Database, User


# ============ Journal DB Mixin ============


class TestStreamJournalMixin:
    def test_append_and_get_after_seq(self, test_database: Database) -> None:
        test_database.journal_append_events(
            "msg-1", [(1, '{"type":"token"}'), (2, '{"type":"token2"}'), (3, '{"type":"end"}')]
        )
        events = test_database.journal_get_events("msg-1", after_seq=1)
        assert [seq for seq, _ in events] == [2, 3]

    def test_get_unknown_message_empty(self, test_database: Database) -> None:
        assert test_database.journal_get_events("nope", 0) == []

    def test_duplicate_seq_ignored(self, test_database: Database) -> None:
        test_database.journal_append_events("msg-2", [(1, "a")])
        test_database.journal_append_events("msg-2", [(1, "b"), (2, "c")])
        events = test_database.journal_get_events("msg-2", 0)
        assert events == [(1, "a"), (2, "c")]

    def test_cleanup_removes_old_rows(self, test_database: Database) -> None:
        test_database.journal_append_events("msg-3", [(1, "a")])
        assert test_database.journal_cleanup(max_age_seconds=0) >= 1
        assert test_database.journal_get_events("msg-3", 0) == []


# ============ Producer Journaling ============


class _ThreeTokenAgent:
    """Fake agent emitting three tokens and a final event."""

    def stream_chat_events(self, *args: object, **kwargs: object):
        yield {"type": "token", "text": "a"}
        yield {"type": "token", "text": "b"}
        yield {"type": "tool_start", "tool": "web_search"}
        yield {
            "type": "final",
            "content": "ab",
            "result_messages": [],
            "tool_results": [],
            "usage_info": {},
        }


class TestProducerJournaling:
    def test_events_journaled_with_seq_and_stream_end(
        self, test_database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.api.helpers import chat_streaming, stream_resume

        monkeypatch.setattr(stream_resume, "db", test_database)
        monkeypatch.setattr(chat_streaming, "db", test_database)
        q: queue.Queue = queue.Queue()
        final_results: dict = {"ready": False, "saved": False}

        chat_streaming.stream_events(
            _ThreeTokenAgent(),
            q,
            final_results,
            "hello",
            None,
            [],
            None,
            "Alice",
            "user-1",
            None,
            False,
            None,
            "conv-1",
            "req-1",
            journal_message_id="assist-msg-1",
        )

        events = test_database.journal_get_events("assist-msg-1", 0)
        parsed = [json.loads(e) for _, e in events]
        types = [p["type"] for p in parsed]
        # token/token/tool_start journaled; final is NOT; stream_end terminates
        assert types == ["token", "token", "tool_start", "stream_end"]
        assert [p["seq"] for p in parsed] == [1, 2, 3, 4]
        # live queue events carry the same seq for client-side tracking
        live = []
        while True:
            item = q.get_nowait()
            if item is None:
                break
            live.append(item)
        assert [e.get("seq") for e in live if e.get("type") == "token"] == [1, 2]


# ============ Resume Generator ============


def _drain_sse(gen) -> list[dict]:
    out = []
    for chunk in gen:
        if chunk.startswith("data: "):
            out.append(json.loads(chunk[len("data: ") :]))
    return out


class TestStreamResumeEvents:
    @pytest.fixture(autouse=True)
    def _patch_db(self, test_database: Database, monkeypatch: pytest.MonkeyPatch):
        from src.api.helpers import stream_resume as chat_streaming

        monkeypatch.setattr(chat_streaming, "db", test_database)
        yield

    def _make_message(self, test_database: Database, test_user: User, content: str = "") -> str:
        conv = test_database.create_conversation(test_user.id, model=Config.DEFAULT_MODEL)
        msg = test_database.add_message(conv.id, MessageRole.ASSISTANT, content)
        return msg.id

    def test_replays_after_seq_and_emits_done(
        self, test_database: Database, test_user: User
    ) -> None:
        from src.api.helpers.stream_resume import stream_resume_events

        msg_id = self._make_message(test_database, test_user, content="full answer")
        test_database.journal_append_events(
            msg_id,
            [
                (1, json.dumps({"type": "token", "text": "full ", "seq": 1})),
                (2, json.dumps({"type": "token", "text": "answer", "seq": 2})),
                (3, json.dumps({"type": "stream_end", "seq": 3})),
            ],
        )

        events = _drain_sse(stream_resume_events(msg_id, after_seq=1))
        types = [e["type"] for e in events]
        assert types == ["token", "done"]
        assert events[0]["seq"] == 2  # only events after the client's offset
        assert events[1]["content"] == "full answer"

    def test_done_without_journal_when_message_saved(
        self, test_database: Database, test_user: User
    ) -> None:
        """Journal swept but the message is saved -> immediate done."""
        from src.api.helpers.stream_resume import stream_resume_events

        msg_id = self._make_message(test_database, test_user, content="late answer")
        events = _drain_sse(stream_resume_events(msg_id, after_seq=0))
        assert [e["type"] for e in events] == ["done"]
        assert events[0]["content"] == "late answer"

    def test_resume_failed_when_placeholder_deleted(
        self, monkeypatch: pytest.MonkeyPatch, test_database: Database
    ) -> None:
        """stream_end + no message row -> RESUME_FAILED error event."""
        from src.api.helpers.stream_resume import stream_resume_events

        test_database.journal_append_events(
            "gone-msg", [(1, json.dumps({"type": "stream_end", "seq": 1}))]
        )
        events = _drain_sse(stream_resume_events("gone-msg", after_seq=0))
        assert [e["type"] for e in events] == ["error"]
        assert events[0]["code"] == "RESUME_FAILED"


class TestResumeStallBound:
    @pytest.fixture(autouse=True)
    def _patch_db(self, test_database: Database, monkeypatch: pytest.MonkeyPatch):
        from src.api.helpers import stream_resume as chat_streaming

        monkeypatch.setattr(chat_streaming, "db", test_database)
        yield

    def test_dead_producer_ends_resume_promptly(
        self, test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Journal with no stream_end and no progress -> RESUME_FAILED, not a
        CHAT_TIMEOUT-long keepalive hold (process killed mid-turn)."""
        from src.api.helpers.stream_resume import stream_resume_events

        monkeypatch.setattr(Config, "STREAM_RESUME_STALL_SECONDS", 0)
        conv = test_database.create_conversation(test_user.id, model=Config.DEFAULT_MODEL)
        msg = test_database.add_message(conv.id, MessageRole.ASSISTANT, "")
        test_database.journal_append_events(
            msg.id, [(1, json.dumps({"type": "token", "text": "partial", "seq": 1}))]
        )

        events = _drain_sse(stream_resume_events(msg.id, after_seq=0))
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "RESUME_FAILED"


class _ApprovalAgent:
    """Fake agent that immediately requests approval."""

    def stream_chat_events(self, *args: object, **kwargs: object):
        from src.agent.tools.request_approval import ApprovalRequestedException

        raise ApprovalRequestedException("ap-9", "send email", "todoist")
        yield  # pragma: no cover


class TestProducerSideApprovalSave:
    def test_approval_message_saved_even_without_consumer(
        self, test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the client disconnects before the consumer processes the approval
        event, the approval message must already be in the placeholder - the
        consumer's finally would otherwise delete it."""
        from src.api.helpers import chat_streaming, stream_resume

        monkeypatch.setattr(stream_resume, "db", test_database)
        monkeypatch.setattr(chat_streaming, "db", test_database)
        conv = test_database.create_conversation(test_user.id, model=Config.DEFAULT_MODEL)
        placeholder = test_database.add_message(conv.id, MessageRole.ASSISTANT, "")

        q: queue.Queue = queue.Queue()
        final_results: dict = {"ready": False, "saved": False}
        chat_streaming.stream_events(
            _ApprovalAgent(),
            q,
            final_results,
            "hello",
            None,
            [],
            None,
            "Alice",
            test_user.id,
            None,
            False,
            None,
            conv.id,
            "req-1",
            journal_message_id=placeholder.id,
        )

        saved = test_database.get_message_by_id(placeholder.id)
        assert saved is not None
        assert "approval-request:ap-9" in saved.content
        assert final_results["saved"] is True
