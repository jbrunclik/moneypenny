"""The What's new chat over the API: marked in the list and detail, and
read-only - no chat turns, interjections or truncation in it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.enums import MessageRole

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, User


@pytest.fixture
def whats_new(test_database: Database, test_user: User) -> str:
    conv_id = test_database.whats_new_conversation_for_post(test_user.id, "Novinky")
    test_database.add_message(conv_id, MessageRole.ASSISTANT, "# Novinka\nText.", language="cs")
    return conv_id


def test_detail_and_list_mark_the_chat(
    client: FlaskClient, auth_headers: dict[str, str], whats_new: str
) -> None:
    detail = client.get(f"/api/conversations/{whats_new}", headers=auth_headers).get_json()
    listing = client.get("/api/conversations", headers=auth_headers).get_json()

    assert detail["is_whats_new"] is True
    [item] = [c for c in listing["conversations"] if c["id"] == whats_new]
    assert item["is_whats_new"] is True


@pytest.mark.parametrize("mode", ["batch", "stream"])
def test_no_chat_turn_in_the_chat(
    client: FlaskClient, auth_headers: dict[str, str], whats_new: str, mode: str
) -> None:
    response = client.post(
        f"/api/conversations/{whats_new}/chat/{mode}",
        headers=auth_headers,
        json={"message": "Hi"},
    )

    assert response.status_code == 400
    assert "read-only" in response.get_json()["error"]["message"]


def test_no_interjection_in_the_chat(
    client: FlaskClient, auth_headers: dict[str, str], whats_new: str
) -> None:
    response = client.post(
        f"/api/conversations/{whats_new}/chat/interject",
        headers=auth_headers,
        json={"message": "Hi"},
    )

    assert response.status_code == 400


def test_no_truncation_in_the_chat(
    client: FlaskClient,
    auth_headers: dict[str, str],
    whats_new: str,
    test_database: Database,
    test_user: User,
) -> None:
    [message] = test_database.get_messages(whats_new)

    response = client.post(
        f"/api/conversations/{whats_new}/truncate",
        headers=auth_headers,
        json={"message_id": message.id},
    )

    assert response.status_code == 400
    assert len(test_database.get_messages(whats_new)) == 1


def test_no_message_delete_in_the_chat(
    client: FlaskClient,
    auth_headers: dict[str, str],
    whats_new: str,
    test_database: Database,
) -> None:
    """Regenerate starts with DELETE /messages/<id>: the announcement must stay."""
    [message] = test_database.get_messages(whats_new)

    response = client.delete(f"/api/messages/{message.id}", headers=auth_headers)

    assert response.status_code == 400
    assert len(test_database.get_messages(whats_new)) == 1


def test_one_live_whats_new_chat_per_user(test_database: Database, test_user: User) -> None:
    """Two workers posting two announcements at once cannot make two chats."""
    import sqlite3

    test_database.whats_new_conversation_for_post(test_user.id, "Novinky")
    with test_database._pool.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at,
                       is_whats_new) VALUES ('dup', ?, 'Novinky', 'm', 'x', 'x', 1)""",
                (test_user.id,),
            )
        conn.rollback()
