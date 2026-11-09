"""A typed answer to a run's card in the agent's chat: the card resolves and
the run resumes (or ends), with no chat turn of its own - the run's report is
the reply (one approval mechanism, step 2; docs/features/proposals.md)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, User


def _waiting_agent(db: Database, user: User, make_run_card: Any) -> tuple[Any, Any]:
    agent = db.create_standing_chat(user.id, "Coach", schedule="0 20 * * *")
    waiting = db.add_message(
        agent.conversation_id or "", "assistant", "**Waiting for your approval**"
    )
    return agent, make_run_card(agent, message_id=waiting.id)


def _post(client: FlaskClient, headers: dict[str, str], conv_id: str, text: str, mode: str) -> Any:
    return client.post(
        f"/api/conversations/{conv_id}/chat/{mode}", headers=headers, json={"message": text}
    )


def test_a_typed_yes_resumes_the_run_without_a_turn(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent, _card = _waiting_agent(test_database, test_user, make_run_card)

    with (
        patch("src.api.helpers.chat_turn.ChatAgent") as agent_class,
        patch("src.agent.run_approvals._resume") as resume,
    ):
        response = _post(client, auth_headers, agent.conversation_id, "ano", "batch")

    body = response.get_json()
    assert response.status_code == 200
    assert body["answer_only"] is True and body.get("id") is None
    assert [p["state"] for p in body["answered_proposals"]] == ["approved"]
    agent_class.assert_not_called()  # no chat turn: the resumed run reports
    resume.assert_called_once()
    roles = [m.role for m in test_database.get_messages(agent.conversation_id or "")]
    assert roles[-1] == "user"  # the approval note; no assistant reply was added


def test_the_stream_ends_with_an_answer_only_done(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent, _card = _waiting_agent(test_database, test_user, make_run_card)

    with (
        patch("src.api.helpers.chat_turn.ChatAgent") as agent_class,
        patch("src.agent.run_approvals._resume"),
    ):
        response = _post(client, auth_headers, agent.conversation_id, "Ne", "stream")
        events = [
            json.loads(line[len("data: ") :])
            for line in response.get_data(as_text=True).splitlines()
            if line.startswith("data: ")
        ]

    agent_class.assert_not_called()
    assert [e["type"] for e in events] == ["user_message_saved", "done"]
    done = events[-1]
    assert done["answer_only"] is True
    assert [p["state"] for p in done["answered_proposals"]] == ["declined"]
    assert "expected_assistant_message_id" not in events[0]


def test_a_second_yes_is_a_normal_turn(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    make_run_card: Any,
) -> None:
    agent, _card = _waiting_agent(test_database, test_user, make_run_card)
    with patch("src.agent.run_approvals._resume"), patch("src.api.helpers.chat_turn.ChatAgent"):
        _post(client, auth_headers, agent.conversation_id, "ano", "batch")

    reply = MagicMock()
    reply.chat_batch.return_value = ("Sure.", [], {"input_tokens": 1}, [])
    with patch("src.api.helpers.chat_turn.ChatAgent", return_value=reply):
        response = _post(client, auth_headers, agent.conversation_id, "ano", "batch")

    assert response.get_json().get("answer_only") is not True
    reply.chat_batch.assert_called_once()
