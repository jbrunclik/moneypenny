"""The background memory review's label on a reply (messages.memory_note)."""

from typing import TYPE_CHECKING

import pytest

from src.enums import MessageRole

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database


def test_set_memory_note_round_trips(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")
    test_database.set_memory_note(msg.id, "Ema - ballet on Tuesdays")

    [stored] = test_database.get_messages(test_conversation.id)
    assert stored.memory_note == "Ema - ballet on Tuesdays"


def test_set_memory_note_bumps_sync_change(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")
    before = test_database.get_sync_cursor()

    test_database.set_memory_note(msg.id, "Ema - ballet on Tuesdays")

    assert test_database.get_sync_cursor() > before


def test_add_message_cost_usd_tops_up(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")
    test_database.save_message_cost(
        msg.id, test_conversation.id, test_conversation.user_id, "m", 10, 5, 0.01
    )

    test_database.add_message_cost_usd(msg.id, 0.002)

    cost = test_database.get_message_cost(msg.id)
    assert cost is not None
    assert cost["cost_usd"] == pytest.approx(0.012)


def test_add_message_cost_usd_without_a_row_is_a_noop(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")
    test_database.add_message_cost_usd(msg.id, 0.002)
    assert test_database.get_message_cost(msg.id) is None


def test_conversation_messages_carry_memory_note(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "Sure.")
    test_database.set_memory_note(msg.id, "Ema - ballet on Tuesdays")

    body = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers).get_json()

    [message] = body["messages"]
    assert message["memory_note"] == "Ema - ballet on Tuesdays"
