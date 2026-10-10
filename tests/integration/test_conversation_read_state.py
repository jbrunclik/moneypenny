"""Server-side read state: unread badges shared across a user's devices.

A device that has seen a conversation records its message count; unread is
message_count - read_count everywhere. Recording it is a conversation write,
so the change log carries it to the other devices (their badge clears).
"""

import json

from flask.testing import FlaskClient

from src.api.schemas.common import MessageRole
from src.db.models import Conversation, Database, User


def _seed(db: Database, conv: Conversation, n: int) -> None:
    for i in range(n):
        db.add_message(conv.id, MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT, f"m{i}")


class TestReadState:
    def test_marking_read_is_reported_in_list_and_sync(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        _seed(test_database, test_conversation, 4)

        response = client.post(
            f"/api/conversations/{test_conversation.id}/read",
            json={"message_count": 4},
            headers=auth_headers,
        )
        assert response.status_code == 200

        listed = json.loads(client.get("/api/conversations", headers=auth_headers).data)
        conv = next(c for c in listed["conversations"] if c["id"] == test_conversation.id)
        assert conv["read_count"] == 4
        synced = json.loads(
            client.get("/api/conversations/sync?full=true", headers=auth_headers).data
        )
        assert synced["conversations"][0]["read_count"] == 4

    def test_marking_read_reaches_other_devices_through_the_change_log(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        _seed(test_database, test_conversation, 2)
        cursor = test_database.get_sync_cursor()

        client.post(
            f"/api/conversations/{test_conversation.id}/read",
            json={"message_count": 2},
            headers=auth_headers,
        )

        changes = json.loads(
            client.get(f"/api/conversations/sync?cursor={cursor}", headers=auth_headers).data
        )
        assert [(c["id"], c["read_count"]) for c in changes["conversations"]] == [
            (test_conversation.id, 2)
        ]

    def test_read_count_is_clamped_to_the_real_count_and_never_reorders(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        _seed(test_database, test_conversation, 2)
        before = test_database.get_conversation(test_conversation.id, test_user.id)

        client.post(
            f"/api/conversations/{test_conversation.id}/read",
            json={"message_count": 99},
            headers=auth_headers,
        )

        after = test_database.get_conversation(test_conversation.id, test_user.id)
        assert after is not None and before is not None
        assert after.read_message_count == 2
        assert after.updated_at == before.updated_at

    def test_unchanged_read_state_records_no_change(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        _seed(test_database, test_conversation, 2)
        client.post(
            f"/api/conversations/{test_conversation.id}/read",
            json={"message_count": 2},
            headers=auth_headers,
        )
        cursor = test_database.get_sync_cursor()

        client.post(
            f"/api/conversations/{test_conversation.id}/read",
            json={"message_count": 2},
            headers=auth_headers,
        )

        assert test_database.get_sync_cursor() == cursor

    def test_other_users_cannot_mark_read(
        self, client: FlaskClient, auth_headers: dict[str, str], test_database: Database
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        theirs = test_database.create_conversation(other.id, "Theirs")

        response = client.post(
            f"/api/conversations/{theirs.id}/read", json={"message_count": 1}, headers=auth_headers
        )

        assert response.status_code == 404


class TestReadStateRaces:
    def test_a_lower_report_never_undoes_a_higher_one(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Device B (chat open) read 4; device A, switched away during its own
        turn, then reports 3 - the reply B saw must stay read."""
        _seed(test_database, test_conversation, 4)
        for count in (4, 3):
            client.post(
                f"/api/conversations/{test_conversation.id}/read",
                json={"message_count": count},
                headers=auth_headers,
            )

        conv = test_database.get_conversation(test_conversation.id, test_user.id)
        assert conv is not None and conv.read_message_count == 4

    def test_deleting_messages_clamps_the_read_count(
        self, test_database: Database, test_user: User, test_conversation: Conversation
    ) -> None:
        """Left above the real count, the next messages from another device
        got no badge anywhere."""
        _seed(test_database, test_conversation, 4)
        test_database.mark_conversation_read(test_conversation.id, test_user.id, 4)
        last = test_database.get_messages(test_conversation.id)[-1]

        test_database.delete_message(last.id, test_user.id)

        conv = test_database.get_conversation(test_conversation.id, test_user.id)
        assert conv is not None and conv.read_message_count == 3

    def test_sync_summary_carries_anonymous_mode(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        cursor = test_database.get_sync_cursor()
        test_database.set_conversation_anonymous_mode(test_conversation.id, test_user.id, True)

        changes = json.loads(
            client.get(f"/api/conversations/sync?cursor={cursor}", headers=auth_headers).data
        )
        assert changes["conversations"][0]["anonymous_mode"] is True
