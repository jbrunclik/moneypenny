"""Artifacts made during a turn reach the reply, the stream, the journal and history."""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient
from langchain_core.messages import AIMessage, ToolMessage

from src.agent.history import enrich_history
from src.agent.message_content import format_message_with_metadata
from src.api.helpers.chat_streaming import FORWARDED_EVENT_TYPES
from src.api.helpers.stream_resume import _JOURNALED_EVENT_TYPES
from src.api.schemas.common import MessageRole
from src.db.models.dataclasses import Message

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_USAGE = {"input_tokens": 50, "output_tokens": 10}


def _events(lines: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in lines.splitlines()
        if line.startswith("data: ")
    ]


def _turn(db: Database, conv: Conversation) -> tuple[dict[str, Any], list[Any]]:
    """An artifact created as the tool would, and the turn's result messages."""
    art, _ = db.create_artifact(conv.id, conv.user_id, "Tips", "<p>tip</p>")
    ref = {"id": art.id, "version": 1, "title": "Tips"}
    call = {"name": "create_artifact", "args": {"title": "Tips", "html": "x"}, "id": "c1"}
    result = ToolMessage(
        name="create_artifact",
        content=json.dumps({"success": True, "artifact": ref}),
        tool_call_id="c1",
    )
    return ref, [AIMessage(content="", tool_calls=[call]), result]


def test_artifact_events_are_forwarded_and_journaled() -> None:
    assert "artifact" in FORWARDED_EVENT_TYPES
    assert "artifact" in _JOURNALED_EVENT_TYPES


def test_stream_turn_saves_and_streams_the_artifact(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    ref, result_messages = _turn(test_database, test_conversation)

    def stream(*args: Any, **kwargs: Any) -> Any:
        yield {"type": "artifact", **ref}
        yield {"type": "token", "text": "Here it is."}
        yield {
            "type": "final",
            "content": "Here it is.",
            "result_messages": result_messages,
            "tool_results": [],
            "usage_info": _USAGE,
        }

    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.stream_chat_events = stream
        agent_class.return_value = agent
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={"message": "Tip calculator"},
        )
        events = _events(response.get_data(as_text=True))

    # The journal numbers journaled events (seq) for resume
    streamed = [{k: v for k, v in e.items() if k != "seq"} for e in events]
    assert {"type": "artifact", **ref} in streamed
    done = next(e for e in events if e["type"] == "done")
    assert done["artifacts"] == [ref]
    saved = next(m for m in test_database.get_messages(test_conversation.id) if m.id == done["id"])
    assert saved.artifacts == [ref]
    version = test_database.get_artifact_version(ref["id"], 1)
    assert version is not None and version.created_by_message_id == done["id"]


def test_batch_turn_returns_the_artifact(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    ref, result_messages = _turn(test_database, test_conversation)

    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.chat_batch.return_value = ("Here it is.", [], _USAGE, result_messages)
        agent_class.return_value = agent
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "Tip calculator"},
        )

    assert response.status_code == 200
    assert response.get_json()["artifacts"] == [ref]
    loaded = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers)
    assert loaded.get_json()["messages"][-1]["artifacts"] == [ref]


def test_history_names_the_artifacts() -> None:
    msg = Message(
        id="m1",
        conversation_id="c1",
        role=MessageRole.ASSISTANT,
        content="Here it is.",
        created_at=datetime.now(),
        artifacts=[{"id": "a1", "version": 2, "title": "Tips"}],
    )

    [enriched] = enrich_history([msg])

    assert enriched["metadata"]["artifacts"] == "a1 v2 'Tips'"
    assert "a1 v2 'Tips'" in format_message_with_metadata(enriched)
