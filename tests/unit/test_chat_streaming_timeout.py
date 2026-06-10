"""Unit tests for the chat-stream request deadline (CHAT_TIMEOUT)."""

import queue
import time
import types

from src.agent.tools.request_approval import ApprovalRequestedException
from src.api.helpers.chat_streaming import (
    STREAM_TIMEOUT_MARKER,
    _handle_generator_error,
    _handle_queue_event,
    _process_event_queue,
    stream_events,
)
from src.config import Config


class _ForeverAgent:
    """Fake ChatAgent whose stream_chat_events never finishes on its own."""

    def stream_chat_events(self, *args, **kwargs):
        i = 0
        while True:
            i += 1
            yield {"type": "token", "text": f"t{i}"}


class _ApprovalAgent:
    """Fake ChatAgent that immediately requests approval."""

    def stream_chat_events(self, *args, **kwargs):
        raise ApprovalRequestedException("ap-1", "send email", "todoist")
        yield  # pragma: no cover - makes this a generator


def _drain(q: queue.Queue) -> list:
    items = []
    while True:
        item = q.get_nowait()
        items.append(item)
        if item is None:
            break
    return items


def test_stream_events_breaks_at_deadline(monkeypatch) -> None:
    """Producer must stop iterating the agent once CHAT_TIMEOUT passes and
    signal a timeout marker followed by the completion sentinel."""
    monkeypatch.setattr(Config, "CHAT_TIMEOUT", 0)  # deadline already passed
    q: queue.Queue = queue.Queue()
    final_results: dict = {"ready": False, "saved": False}

    stream_events(
        _ForeverAgent(),
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
    )

    items = _drain(q)
    assert {"type": "timeout"} in items
    assert items[-1] is None
    assert any(isinstance(x, dict) and x.get("type") == "token" for x in items)
    assert final_results["ready"] is False  # no final event arrived


def _make_ctx(items=()) -> types.SimpleNamespace:
    """Minimal stand-in for _StreamContext for consumer-path tests."""
    q: queue.Queue = queue.Queue()
    for it in items:
        q.put(it)
    ctx = types.SimpleNamespace(
        event_queue=q,
        partial_content="",
        clean_content="",
        result_messages=[],
        tool_results=[],
        usage_info={},
        final_results={"ready": False, "saved": False},
        user_id="user-1",
        conv_id="conv-1",
        client_connected=True,
    )
    ctx.mark_disconnected = lambda error, where: None
    return ctx


def test_handle_queue_event_accumulates_token_text() -> None:
    ctx = _make_ctx()
    list(_handle_queue_event(ctx, {"type": "token", "text": "hel"}))
    list(_handle_queue_event(ctx, {"type": "token", "text": "lo"}))
    assert ctx.partial_content == "hello"


def test_consumer_handles_producer_timeout_marker() -> None:
    """Tokens then a {'type':'timeout'} marker -> partial content saved + event."""
    ctx = _make_ctx(
        [
            {"type": "token", "text": "partial "},
            {"type": "token", "text": "answer"},
            {"type": "timeout"},
        ]
    )
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' in out
    assert ctx.clean_content == "partial answer" + STREAM_TIMEOUT_MARKER
    assert ctx.final_results["ready"] is True
    assert ctx.final_results["clean_content"] == ctx.clean_content


def test_consumer_backstop_fires_with_no_events(monkeypatch) -> None:
    """Empty queue + passed deadline -> emits timeout and returns (no hang)."""
    monkeypatch.setattr(Config, "CHAT_TIMEOUT", 0)
    monkeypatch.setattr(Config, "SSE_KEEPALIVE_INTERVAL", 0.05)
    ctx = _make_ctx()  # empty queue
    started = time.monotonic()
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' in out
    assert time.monotonic() - started < 2.0  # terminated promptly
    assert ctx.clean_content == ""  # no partial content to save


def test_stream_events_approval_puts_completion_sentinel() -> None:
    """ApprovalRequestedException must be followed by the None sentinel.

    Regression test: without the sentinel the consumer keeps blocking on the
    queue, sending keepalives until the backstop deadline (CHAT_TIMEOUT +
    keepalive interval, ~615s) and then emits a bogus timeout event - the
    approval done event reaches the client ten minutes late.
    """
    q: queue.Queue = queue.Queue()
    final_results: dict = {"ready": False, "saved": False}

    stream_events(
        _ApprovalAgent(),
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
    )

    items = _drain(q)
    approvals = [x for x in items if isinstance(x, dict) and x.get("type") == "approval_required"]
    assert approvals and approvals[0]["approval_id"] == "ap-1"
    assert items[-1] is None


def test_consumer_approval_completion_no_timeout() -> None:
    """approval_required -> None terminates promptly with no timeout event."""
    ctx = _make_ctx(
        [
            {
                "type": "approval_required",
                "approval_id": "ap-1",
                "description": "send email",
                "tool_name": "todoist",
            },
            None,
        ]
    )
    out = "".join(_process_event_queue(ctx))
    assert '"type": "approval_required"' in out
    assert '"type": "timeout"' not in out
    assert ctx.approval_info["approval_id"] == "ap-1"


def test_generator_error_does_not_delete_saved_message(monkeypatch) -> None:
    """A post-save exception must not delete the just-saved message.

    Regression test: _handle_generator_error checked only placeholder_saved and
    empty clean_content; when _finalize_stream saved successfully but raised
    afterwards, the saved message was deleted.
    """
    ctx = _make_ctx()
    ctx.placeholder_saved = True
    ctx.expected_assistant_msg_id = "msg-1"
    ctx.final_results["saved"] = True

    deleted: list[str] = []
    monkeypatch.setattr(
        "src.api.helpers.chat_streaming.db.delete_message_by_id",
        lambda mid: deleted.append(mid),
    )

    list(_handle_generator_error(ctx, RuntimeError("boom")))
    assert deleted == []


def test_consumer_normal_completion_no_timeout() -> None:
    """token -> final -> None completes normally with no timeout event."""
    ctx = _make_ctx(
        [
            {"type": "token", "text": "full "},
            {
                "type": "final",
                "content": "full answer",
                "result_messages": [],
                "tool_results": [],
                "usage_info": {},
            },
            None,
        ]
    )
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' not in out
    assert ctx.clean_content == "full answer"
    assert ctx.final_results["ready"] is False  # consumer doesn't set ready on normal path
