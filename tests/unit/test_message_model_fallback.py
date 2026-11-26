"""The model that answered a reply when it was the fallback (messages.model_fallback).

Nov 26 2026: a fallback only showed a toast, gone after a few seconds and
never on another device; the reply now keeps which model wrote it.
"""

import json
from collections.abc import Generator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.enums import MessageRole

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database


def test_add_message_stores_the_fallback(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "Sure.", model_fallback="gemini-4-hydrogen"
    )

    assert msg.model_fallback == "gemini-4-hydrogen"
    [stored] = test_database.get_messages(test_conversation.id)
    assert stored.model_fallback == "gemini-4-hydrogen"


def test_filling_the_placeholder_stores_the_fallback(
    test_database: Database, test_conversation: Conversation
) -> None:
    placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

    updated = test_database.update_message_content(
        placeholder.id, "Sure.", model_fallback="gemini-4-hydrogen"
    )

    assert updated is not None
    assert updated.model_fallback == "gemini-4-hydrogen"


def test_a_resumed_streams_done_event_carries_the_fallback(
    test_database: Database, test_conversation: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.helpers import stream_resume

    monkeypatch.setattr(stream_resume, "db", test_database)
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "Sure.", model_fallback="gemini-4-hydrogen"
    )

    chunks = list(stream_resume.stream_resume_events(msg.id, after_seq=0))

    [done] = [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: ")]
    assert done["type"] == "done"
    assert done["model_fallback"] == "gemini-4-hydrogen"


def test_a_reply_from_its_own_model_has_none(
    test_database: Database, test_conversation: Conversation
) -> None:
    test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")

    [stored] = test_database.get_messages(test_conversation.id)
    assert stored.model_fallback is None


def test_conversation_messages_carry_the_fallback(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    test_database.add_message(test_conversation.id, MessageRole.USER, "Hi")
    test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "Sure.", model_fallback="gemini-4-hydrogen"
    )

    body = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers).get_json()

    user, reply = body["messages"]
    assert user.get("model_fallback") is None
    assert reply["model_fallback"] == "gemini-4-hydrogen"


def test_a_streamed_turn_that_fell_back_saves_it(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        yield {"type": "model_fallback", "to": "gemini-4-hydrogen"}
        yield {"type": "token", "text": "Answer"}
        yield {
            "type": "final",
            "content": "Answer",
            "tool_results": [],
            "usage_info": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "model_fallback": "gemini-4-hydrogen",
            },
            "result_messages": [],
        }

    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.stream_chat_events = stream
        agent_class.return_value = agent
        body = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            json={"message": "Hi"},
            headers=auth_headers,
        ).get_data(as_text=True)

    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert {"type": "model_fallback", "to": "gemini-4-hydrogen"} in events
    done = next(e for e in events if e.get("type") == "done")
    assert done["model_fallback"] == "gemini-4-hydrogen"
    reply = test_database.get_messages(test_conversation.id)[-1]
    assert reply.role == MessageRole.ASSISTANT
    assert reply.model_fallback == "gemini-4-hydrogen"
