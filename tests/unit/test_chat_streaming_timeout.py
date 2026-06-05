"""Unit tests for the chat-stream request deadline (CHAT_TIMEOUT)."""

import queue

from src.api.helpers.chat_streaming import stream_events
from src.config import Config


class _ForeverAgent:
    """Fake ChatAgent whose stream_chat_events never finishes on its own."""

    def stream_chat_events(self, *args, **kwargs):
        i = 0
        while True:
            i += 1
            yield {"type": "token", "text": f"t{i}"}


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
