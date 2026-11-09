"""Approve or decline a proposal card (docs/features/proposals.md)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from src.agent.proposals import register_kind
from src.db.models import Proposal
from src.enums import MessageRole
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database, ProposalOption, User

_APPLIED: list[dict[str, object]] = []


def _apply(proposal: Proposal, option: ProposalOption) -> str:
    _APPLIED.append(option["payload"])
    return "Reminder set - Thu 8:00."


@pytest.fixture(autouse=True)
def _kind() -> Iterator[None]:
    register_kind("test_kind", _apply)
    _APPLIED.clear()
    yield


def _card(db: Database, conv: Conversation, *, linked: bool = True) -> Proposal:
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Shall I?")
    return db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=conv.user_id,
            conversation_id=conv.id,
            message_id=reply.id if linked else None,
            request_id="r1",
            kind="test_kind",
            summary='Reminder: "Call the plumber"',
            details={"When": "Thu 8:00"},
            options=[{"label": "Set it up", "description": "", "payload": {"n": 1}}],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
        )
    )


def _post(client: FlaskClient, headers: dict[str, str], path: str, body: object = None) -> object:
    return client.post(f"/api/proposals/{path}", headers=headers, json=body or {})


def test_approve_applies_and_returns_the_result(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    card = _card(test_database, test_conversation)

    response = _post(client, auth_headers, f"{card.id}/approve", {"choice": 0})

    assert response.status_code == 200  # type: ignore[attr-defined]
    body = response.get_json()  # type: ignore[attr-defined]
    assert (body["state"], body["result"], body["chosen"]) == (
        "approved",
        "Reminder set - Thu 8:00.",
        0,
    )
    assert _APPLIED == [{"n": 1}]


def test_decline(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    card = _card(test_database, test_conversation)

    response = _post(client, auth_headers, f"{card.id}/decline")

    assert response.get_json()["state"] == "declined"  # type: ignore[attr-defined]
    assert _APPLIED == []


def test_second_approve_is_409(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    card = _card(test_database, test_conversation)
    _post(client, auth_headers, f"{card.id}/approve")

    again = _post(client, auth_headers, f"{card.id}/approve")

    assert again.status_code == 409  # type: ignore[attr-defined]
    assert _APPLIED == [{"n": 1}]


def test_unlinked_proposal_is_409(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    card = _card(test_database, test_conversation, linked=False)

    assert _post(client, auth_headers, f"{card.id}/approve").status_code == 409  # type: ignore[attr-defined]


def test_other_users_proposal_is_404(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
) -> None:
    other: User = test_database.get_or_create_user(email="other@example.com", name="Other")
    card = _card(test_database, test_database.create_conversation(other.id))

    assert _post(client, auth_headers, f"{card.id}/approve").status_code == 404  # type: ignore[attr-defined]
    assert _post(client, auth_headers, "nope/decline").status_code == 404  # type: ignore[attr-defined]


def test_choice_out_of_range_is_400(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    card = _card(test_database, test_conversation)

    response = _post(client, auth_headers, f"{card.id}/approve", {"choice": 3})

    assert response.status_code == 400  # type: ignore[attr-defined]
    found = test_database.get_proposal(card.id, card.user_id)
    assert found is not None and found.state == "pending"
