"""Server-side Stop through the real streaming route (agent class patched)."""

import json
import time
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

from src.agent import cancellation
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User

StreamFn = Callable[..., Generator[dict[str, Any]]]


def _final(content: str, stop_reason: str | None = None) -> dict[str, Any]:
    final: dict[str, Any] = {
        "type": "final",
        "content": content,
        "tool_results": [],
        "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "result_messages": [],
    }
    if stop_reason:
        final["stop_reason"] = stop_reason
    return final


def _run_turn(
    client: FlaskClient, auth_headers: dict[str, str], conv_id: str, stream: StreamFn
) -> dict[str, Any]:
    """POST a streaming turn with the agent's event stream replaced; return the done event."""
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.stream_chat_events = stream
        agent_class.return_value = agent
        body = client.post(
            f"/api/conversations/{conv_id}/chat/stream",
            json={"message": "Tell me a long story"},
            headers=auth_headers,
        ).get_data(as_text=True)
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    return next(e for e in events if e.get("type") == "done")


def test_stopped_turn_saves_partial_with_stop_reason(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        yield {"type": "token", "text": "Partial answer"}
        yield _final("Partial answer", stop_reason="user")

    done = _run_turn(client, auth_headers, test_conversation.id, stream)

    assert done["stop_reason"] == "user"
    saved = test_database.get_message_by_id(done["id"])
    assert saved is not None
    assert saved.content == "Partial answer"
    assert saved.stop_reason == "user"
    listed = client.get(
        f"/api/conversations/{test_conversation.id}/messages", headers=auth_headers
    ).get_json()
    assert any(m.get("stop_reason") == "user" for m in listed["messages"])


def test_empty_stopped_turn_saves_placeholder_text(
    client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
) -> None:
    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        yield _final("", stop_reason="user")

    done = _run_turn(client, auth_headers, test_conversation.id, stream)

    assert done["content"] == cancellation.STOPPED_EMPTY_TEXT
    assert done["stop_reason"] == "user"


def test_stale_stop_flag_does_not_cancel_the_next_turn(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_user: User,
    test_conversation: Conversation,
) -> None:
    # A Stop for the previous turn (its message id) that arrived after it ended
    cancellation.request_stop(test_user.id, test_conversation.id, "previous-turn-message")
    seen: dict[str, bool] = {}

    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        time.sleep(0.2)  # several poll intervals (patched below)
        seen["cancelled"] = cancellation.is_cancelled()
        yield _final("Full answer")

    with patch("src.config.Config.CANCEL_POLL_INTERVAL_SECONDS", 0.02):
        done = _run_turn(client, auth_headers, test_conversation.id, stream)

    assert seen["cancelled"] is False
    assert "stop_reason" not in done


def _placeholder_id(test_database: Database, conv_id: str) -> str:
    """The streaming turn's assistant message id (placeholder saved before streaming)."""
    return [m for m in test_database.get_messages(conv_id) if m.role.value == "assistant"][-1].id


def test_stop_flag_cancels_the_running_turn(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    seen: dict[str, bool] = {}
    ids: dict[str, str] = {}

    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        ids["msg"] = _placeholder_id(test_database, test_conversation.id)
        # the /stop route's write, for THIS turn
        cancellation.request_stop(test_user.id, test_conversation.id, ids["msg"])
        for _ in range(100):
            if cancellation.is_cancelled():
                break
            time.sleep(0.01)
        seen["cancelled"] = cancellation.is_cancelled()
        yield _final("Partial", stop_reason="user" if seen["cancelled"] else None)

    with patch("src.config.Config.CANCEL_POLL_INTERVAL_SECONDS", 0.02):
        _run_turn(client, auth_headers, test_conversation.id, stream)

    assert seen["cancelled"] is True
    # The producer clears its own flag in its finally, just after it signals
    # the consumer that the stream ended - allow it a moment
    for _ in range(100):
        if not cancellation.stop_requested(test_user.id, test_conversation.id, ids["msg"]):
            break
        time.sleep(0.01)
    assert cancellation.stop_requested(test_user.id, test_conversation.id, ids["msg"]) is False


def test_stop_during_a_silent_tool_is_acknowledged_at_once(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    """No events flow while a tool runs; the client must still learn the Stop
    landed (else its 5 s grace abort always fires during long tools)."""

    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        msg_id = _placeholder_id(test_database, test_conversation.id)
        cancellation.request_stop(test_user.id, test_conversation.id, msg_id)
        time.sleep(0.5)  # a tool running: the producer yields nothing meanwhile
        yield _final("Partial", stop_reason="user")

    with patch("src.config.Config.CANCEL_POLL_INTERVAL_SECONDS", 0.02):
        with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
            agent = MagicMock()
            agent.stream_chat_events = stream
            agent_class.return_value = agent
            body = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                json={"message": "Search a lot"},
                headers=auth_headers,
            ).get_data(as_text=True)

    types = [
        json.loads(line[6:])["type"] for line in body.splitlines() if line.startswith("data: ")
    ]
    assert "stopping" in types
    assert types.index("stopping") < types.index("done")
