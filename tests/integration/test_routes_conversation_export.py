"""GET /api/conversations/<id>/export: the conversation as a Markdown file."""

from flask.testing import FlaskClient

from src.db.models import Database
from src.db.models.dataclasses import Conversation


def test_downloads_the_conversation_as_markdown(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    test_database.update_conversation(
        test_conversation.id, test_conversation.user_id, title="Zadní světlo"
    )
    test_database.add_message(test_conversation.id, "user", "Which mount?")
    test_database.add_message(test_conversation.id, "assistant", "The **quarter-turn** one.")

    response = client.get(f"/api/conversations/{test_conversation.id}/export", headers=auth_headers)

    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "filename*=UTF-8''Zadn%C3%AD" in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert body.startswith("# Zadní světlo")
    assert "Which mount?" in body and "The **quarter-turn** one." in body


def test_another_users_conversation_is_not_found(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database
) -> None:
    other = test_database.get_or_create_user("other@example.com", "Other")
    conv = test_database.create_conversation(other.id)

    response = client.get(f"/api/conversations/{conv.id}/export", headers=auth_headers)

    assert response.status_code == 404


def test_requires_auth(client: FlaskClient, test_conversation: Conversation) -> None:
    response = client.get(f"/api/conversations/{test_conversation.id}/export")
    assert response.status_code == 401
