"""The chat routes start the freshness gate as soon as a turn is accepted.

Nov 16 2026: the gate took a median 943 ms in series before every turn, while
it needs only the user's text, the previous reply and the attachment count -
all known once the turn is accepted. Started there, it runs while the history
is compacted and the prompt assembled; the agent waits only for what is left.
"""

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.agent import freshness
from src.config import Config
from src.db.models import Conversation, Database

_GATE = freshness.GateVerdict(lookup=False, thinking="low")


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "FRESHNESS_GATE_ENABLED", True)


def _batch(
    client: FlaskClient, auth_headers: dict[str, str], conv_id: str, body: dict[str, Any]
) -> MagicMock:
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.chat_batch.return_value = ("Answer", [], {}, [])
        agent_class.return_value = agent
        response = client.post(
            f"/api/conversations/{conv_id}/chat/batch", headers=auth_headers, json=body
        )
    assert response.status_code == 200
    return agent


def test_the_gate_runs_while_the_turn_is_prepared(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    test_database.add_message(test_conversation.id, "user", "Who won?")
    test_database.add_message(test_conversation.id, "assistant", "Pogačar, in July.")
    asked = threading.Event()
    seen: list[tuple[str, str, int]] = []

    def ask(user: str, previous: str, attachments: int) -> Any:
        seen.append((user, previous, attachments))
        asked.set()
        return _GATE, None

    overlapped: list[bool] = []

    def compaction(_user_id: str, _conv_id: str, history: list[Any]) -> list[Any]:
        overlapped.append(asked.wait(timeout=2))
        return history

    with (
        patch.object(freshness, "_ask_gate", side_effect=ask),
        patch("src.api.helpers.chat_turn.build_compacted_history", side_effect=compaction),
    ):
        agent = _batch(client, auth_headers, test_conversation.id, {"message": "And in 2025?"})

    assert overlapped == [True]
    assert seen == [("And in 2025?", "Pogačar, in July.", 0)]
    pending = agent.chat_batch.call_args.kwargs["freshness_gate"]
    assert isinstance(pending, freshness.PendingGate)


def test_attachments_are_counted(
    client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
) -> None:
    seen: list[int] = []

    def ask(_user: str, _previous: str, attachments: int) -> Any:
        seen.append(attachments)
        return _GATE, None

    # A 1x1 PNG and a text file (text arrives as text, not as an attachment)
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    files = [
        {"name": "a.png", "type": "image/png", "data": png},
        {"name": "n.txt", "type": "text/plain", "data": "aGVsbG8="},
    ]
    with patch.object(freshness, "_ask_gate", side_effect=ask):
        _batch(
            client,
            auth_headers,
            test_conversation.id,
            {"message": "What is this?", "files": files},
        )
    assert seen == [1]


def test_the_planner_starts_no_gate(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    planner = test_database.get_or_create_planner_conversation(test_conversation.user_id)
    with patch.object(freshness, "_ask_gate") as ask:
        agent = _batch(client, auth_headers, planner.id, {"message": "Plan my day"})
    ask.assert_not_called()
    assert agent.chat_batch.call_args.kwargs["freshness_gate"] is None
