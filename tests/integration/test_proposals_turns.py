"""Proposals in chat turns: the reply carries its cards (batch, stream and
history), a typed answer resolves them before the agent runs and the agent
hears the outcome, anything else expires them (docs/features/proposals.md)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.proposals import file_proposal, register_kind, resolve
from src.db.models import Proposal
from src.enums import MessageRole
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database, ProposalOption

_USAGE = {"input_tokens": 50, "output_tokens": 10}
_APPLIED: list[dict[str, object]] = []


def _apply(proposal: Proposal, option: ProposalOption) -> str:
    _APPLIED.append(option["payload"])
    return "Reminder set - Thu 8:00."


@pytest.fixture(autouse=True)
def _kind() -> Iterator[None]:
    register_kind("test_kind", _apply)
    _APPLIED.clear()
    yield


def _option() -> ProposalOption:
    return {"label": "Set it up", "description": "", "payload": {"secret": "server-side"}}


def _file_one() -> None:
    file_proposal("test_kind", 'Reminder: "Call the plumber"', {"When": "Thu 8:00"}, [_option()])


def _agent(chat_batch: Any = None, stream: Any = None) -> Any:
    agent = MagicMock()
    if chat_batch is not None:
        agent.chat_batch.side_effect = chat_batch
    if stream is not None:
        agent.stream_chat_events = stream
    return agent


def _batch(
    client: FlaskClient, headers: dict[str, str], conv_id: str, text: str, agent: Any
) -> Any:
    with patch("src.api.helpers.chat_turn.ChatAgent", return_value=agent):
        return client.post(
            f"/api/conversations/{conv_id}/chat/batch", headers=headers, json={"message": text}
        )


def _proposing(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], dict[str, int], list[Any]]:
    _file_one()
    return ("Shall I set a reminder for Thursday 8:00?", [], _USAGE, [])


def _replying(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], dict[str, int], list[Any]]:
    return ("Done.", [], _USAGE, [])


def _seeded(db: Database, conv: Conversation) -> tuple[str, Proposal]:
    """A reply showing one pending card, as an earlier turn left it."""
    db.add_message(conv.id, MessageRole.USER, "Remind me Thursday at 8")
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Shall I?")
    proposal = db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=conv.user_id,
            conversation_id=conv.id,
            message_id=reply.id,
            request_id="earlier",
            kind="test_kind",
            summary='Reminder: "Call the plumber"',
            details={"When": "Thu 8:00"},
            options=[_option()],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
        )
    )
    return reply.id, proposal


def _state(db: Database, proposal: Proposal) -> str:
    found = db.get_proposal(proposal.id, proposal.user_id)
    assert found is not None
    return found.state


def test_the_reply_carries_its_proposal(
    client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
) -> None:
    response = _batch(client, auth_headers, test_conversation.id, "Remind me", _agent(_proposing))

    [card] = response.get_json()["proposals"]
    assert (card["kind"], card["summary"], card["state"]) == (
        "test_kind",
        'Reminder: "Call the plumber"',
        "pending",
    )
    assert card["options"] == [{"label": "Set it up", "description": ""}]
    assert card["details"] == [{"label": "When", "value": "Thu 8:00"}]  # rows keep their order
    assert "secret" not in json.dumps(card)  # payloads never leave the server
    loaded = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers)
    assert loaded.get_json()["messages"][-1]["proposals"][0]["id"] == card["id"]


def test_the_stream_done_event_carries_the_proposal(
    client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
) -> None:
    def stream(*_args: Any, **_kwargs: Any) -> Iterator[dict[str, Any]]:
        _file_one()
        yield {"type": "token", "text": "Shall I?"}
        yield {
            "type": "final",
            "content": "Shall I?",
            "result_messages": [],
            "tool_results": [],
            "usage_info": _USAGE,
        }

    with patch("src.api.helpers.chat_turn.ChatAgent", return_value=_agent(stream=stream)):
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={"message": "Remind me"},
        )
    events = [
        json.loads(line[len("data: ") :])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]

    done = next(e for e in events if e["type"] == "done")
    assert [p["summary"] for p in done["proposals"]] == ['Reminder: "Call the plumber"']


def test_typed_yes_approves_before_the_turn_and_the_agent_hears_it(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    _reply_id, proposal = _seeded(test_database, test_conversation)
    agent = _agent(_replying)

    _batch(client, auth_headers, test_conversation.id, "Ano", agent)

    assert _state(test_database, proposal) == "approved"
    assert _APPLIED == [{"secret": "server-side"}]
    text = agent.chat_batch.call_args.kwargs["text"]
    assert "The user approved" in text and "Reminder set - Thu 8:00." in text


def test_a_non_answer_expires_the_proposal(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    _reply_id, proposal = _seeded(test_database, test_conversation)

    _batch(client, auth_headers, test_conversation.id, "Actually make it 9", _agent(_replying))

    assert _state(test_database, proposal) == "expired"
    assert _APPLIED == []


def test_proposal_of_a_failed_turn_expires(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    def failing(*_args: Any, **_kwargs: Any) -> Any:
        _file_one()
        raise RuntimeError("model down")

    _batch(client, auth_headers, test_conversation.id, "Remind me", _agent(failing))
    [orphan] = test_database.pending_proposals(test_conversation.id)
    assert orphan.message_id is None  # no reply, so no card

    _batch(client, auth_headers, test_conversation.id, "yes", _agent(_replying))

    assert _state(test_database, orphan) == "expired"
    assert _APPLIED == []


def test_regenerate_expires_the_replys_proposal(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    reply_id, proposal = _seeded(test_database, test_conversation)

    response = client.delete(f"/api/messages/{reply_id}", headers=auth_headers)

    assert response.status_code in {200, 204}
    assert _state(test_database, proposal) == "expired"


def test_history_reload_shows_resolved_state(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    _reply_id, proposal = _seeded(test_database, test_conversation)
    resolve(proposal, 0, "button")

    loaded = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers)

    [card] = loaded.get_json()["messages"][-1]["proposals"]
    assert (card["state"], card["result"], card["chosen"]) == (
        "approved",
        "Reminder set - Thu 8:00.",
        0,
    )


def test_regenerate_after_a_typed_yes_still_tells_the_agent(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    """The typed yes applied the card, then the model call failed: the
    regenerate must still hear it was approved (or it files the card again)."""
    _reply_id, proposal = _seeded(test_database, test_conversation)

    def failing(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("model down")

    _batch(client, auth_headers, test_conversation.id, "Ano", _agent(failing))
    assert _state(test_database, proposal) == "approved"
    agent = _agent(_replying)
    with patch("src.api.helpers.chat_turn.ChatAgent", return_value=agent):
        client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "", "rerun_mode": "regenerate"},
        )

    text = agent.chat_batch.call_args.kwargs["text"]
    assert "The user approved" in text
    assert _APPLIED == [{"secret": "server-side"}]  # applied once


def test_an_app_sent_message_never_answers_a_card(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    """An artifact's button (or any app-sent message) saying "ok" is not the
    user's answer: the card expires, nothing applies."""
    _reply_id, proposal = _seeded(test_database, test_conversation)

    with patch("src.api.helpers.chat_turn.ChatAgent", return_value=_agent(_replying)):
        client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "ok", "app_sent": True},
        )

    assert _state(test_database, proposal) == "expired"
    assert _APPLIED == []
