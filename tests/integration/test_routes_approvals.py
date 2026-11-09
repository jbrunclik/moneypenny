"""Runs waiting on the user's card: GET /api/approvals lists them, and the
card is answered like any proposal (/api/proposals/<id>/approve|decline),
which resumes or ends that run (docs/features/proposals.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, User


def test_pending_run_cards_are_listed_with_their_agent(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    card = make_run_card(agent, summary="Todoist: add task")

    [listed] = client.get("/api/approvals", headers=auth_headers).get_json()["pending_approvals"]

    assert (listed["id"], listed["job_id"], listed["job_name"], listed["summary"]) == (
        card.id,
        agent.id,
        "Coach",
        "Todoist: add task",
    )
    assert listed["conversation_id"] == agent.conversation_id
    assert "payload" not in str(listed)


def test_approving_a_run_card_resumes_its_run(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    waiting = test_database.add_message(agent.conversation_id or "", "assistant", "Waiting")
    card = make_run_card(agent, message_id=waiting.id)

    with patch("src.agent.run_approvals._resume") as resume:
        response = client.post(f"/api/proposals/{card.id}/approve", headers=auth_headers, json={})

    assert response.status_code == 200
    assert response.get_json()["state"] == "approved"
    resume.assert_called_once()
    assert client.get("/api/approvals", headers=auth_headers).get_json()["pending_approvals"] == []


def test_declining_a_run_card_ends_its_run(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    waiting = test_database.add_message(agent.conversation_id or "", "assistant", "Waiting")
    card = make_run_card(agent, message_id=waiting.id)

    with patch("src.agent.run_approvals._resume") as resume:
        response = client.post(f"/api/proposals/{card.id}/decline", headers=auth_headers)

    assert response.get_json()["state"] == "declined"
    resume.assert_not_called()
    assert test_database.get_messages(agent.conversation_id or "")[-1].content.startswith(
        "[Action rejected:"
    )
