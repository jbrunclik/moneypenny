"""The stream turns a finished artifact tool call into an `artifact` event."""

import json

from langchain_core.messages import ToolMessage

from src.agent.stream_events import StreamEventProcessor


def _events(name: str, body: dict[str, object]) -> list[dict[str, object]]:
    proc = StreamEventProcessor([])
    proc.pending_tool_calls.add("c1")
    msg = ToolMessage(name=name, content=json.dumps(body), tool_call_id="c1")
    return list(proc.process("messages", (msg, {})))


def test_created_artifact_follows_tool_end() -> None:
    ref = {"id": "a1", "version": 1, "title": "Tips"}
    events = _events("create_artifact", {"success": True, "artifact": ref})
    assert events == [
        {"type": "tool_end", "tool": "create_artifact"},
        {"type": "artifact", "id": "a1", "version": 1, "title": "Tips"},
    ]


def test_failed_or_read_results_make_no_event() -> None:
    ref = {"id": "a1", "version": 1, "title": "T"}
    assert [e["type"] for e in _events("create_artifact", {"success": False})] == ["tool_end"]
    assert [e["type"] for e in _events("read_artifact", {"success": True, "artifact": ref})] == [
        "tool_end"
    ]
