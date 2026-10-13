"""Integration tests for the conversation trash routes."""

from datetime import UTC, datetime, timedelta

from flask.testing import FlaskClient

from src.config import Config
from src.db.models import Conversation, Database, User


def _trash(client: FlaskClient, headers: dict[str, str], conv_id: str) -> None:
    response = client.delete(f"/api/conversations/{conv_id}", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["status"] == "trashed"


class TestTrashRoutes:
    def test_delete_moves_to_trash(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)

        get_response = client.get(
            f"/api/conversations/{test_conversation.id}", headers=auth_headers
        )
        assert get_response.status_code == 404
        data = client.get("/api/conversations/trash", headers=auth_headers).get_json()
        assert [c["id"] for c in data["conversations"]] == [test_conversation.id]
        item = data["conversations"][0]
        deleted_at = datetime.fromisoformat(item["deleted_at"])
        assert datetime.fromisoformat(item["purge_at"]) - deleted_at == timedelta(days=14)
        assert data["pagination"]["total_count"] == 1

    def test_delete_twice_is_ok(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)
        _trash(client, auth_headers, test_conversation.id)

    def test_delete_missing_404(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        assert client.delete("/api/conversations/nope", headers=auth_headers).status_code == 404

    def test_restore(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _trash(client, auth_headers, test_conversation.id)
        response = client.post(
            f"/api/conversations/{test_conversation.id}/restore", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.get_json()["status"] == "restored"
        get_response = client.get(
            f"/api/conversations/{test_conversation.id}", headers=auth_headers
        )
        assert get_response.status_code == 200

    def test_restore_missing_404(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        assert (
            client.post("/api/conversations/nope/restore", headers=auth_headers).status_code == 404
        )

    def test_permanent_delete_requires_trash(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        url = f"/api/conversations/{test_conversation.id}/permanent"
        assert client.delete(url, headers=auth_headers).status_code == 404
        _trash(client, auth_headers, test_conversation.id)
        assert client.delete(url, headers=auth_headers).status_code == 200
        trash = client.get("/api/conversations/trash", headers=auth_headers).get_json()
        assert trash["conversations"] == []

    def test_empty_trash(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        for title in ("A", "B"):
            conv = test_database.create_conversation(test_user.id, title)
            _trash(client, auth_headers, conv.id)
        response = client.delete("/api/conversations/trash", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"deleted": 2}

    def test_delete_agent_conversation_is_hard_delete(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Agent")
        with test_database._pool.get_connection() as conn:
            conn.execute("UPDATE conversations SET is_agent = 1 WHERE id = ?", (conv.id,))
            conn.commit()
        response = client.delete(f"/api/conversations/{conv.id}", headers=auth_headers)
        assert response.get_json()["status"] == "deleted"
        assert test_database.list_trashed_conversations_paginated(test_user.id)[3] == 0

    def test_routes_require_auth(
        self, client: FlaskClient, test_conversation: Conversation
    ) -> None:
        assert client.get("/api/conversations/trash").status_code == 401
        assert client.post(f"/api/conversations/{test_conversation.id}/restore").status_code == 401
        permanent = f"/api/conversations/{test_conversation.id}/permanent"
        assert client.delete(permanent).status_code == 401
        assert client.delete("/api/conversations/trash").status_code == 401

    def test_trash_listing_carries_archived_and_pinned(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Pinned and archived")
        test_database.set_conversation_pinned(conv.id, test_user.id, True)
        test_database.archive_conversation(conv.id, test_user.id)
        _trash(client, auth_headers, conv.id)

        item = client.get("/api/conversations/trash", headers=auth_headers).get_json()[
            "conversations"
        ][0]

        assert (item["archived"], item["pinned"]) == (True, True)


class TestBulkTrashRoutes:
    def test_bulk_trash_ids(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        a = test_database.create_conversation(test_user.id, "A")
        b = test_database.create_conversation(test_user.id, "B")
        keep = test_database.create_conversation(test_user.id, "Keep")

        response = client.post(
            "/api/conversations/bulk-trash", json={"ids": [a.id, b.id]}, headers=auth_headers
        )

        assert response.status_code == 200
        assert sorted(response.get_json()["trashed_ids"]) == sorted([a.id, b.id])
        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        assert [c["id"] for c in listed["conversations"]] == [keep.id]

    def test_bulk_trash_all_with_exclusions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        a = test_database.create_conversation(test_user.id, "A")
        keep = test_database.create_conversation(test_user.id, "Keep")
        body = {
            "all": True,
            "exclude_ids": [keep.id],
            "created_before": (datetime.now() + timedelta(seconds=5)).isoformat(),
        }

        response = client.post("/api/conversations/bulk-trash", json=body, headers=auth_headers)

        assert response.get_json() == {"trashed_ids": [a.id]}

    def test_trash_all_accepts_utc_created_before(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        # The browser sends toISOString() (UTC, "Z"); the DB stores naive local time
        conv = test_database.create_conversation(test_user.id, "A")
        utc_now = datetime.now(UTC) + timedelta(seconds=5)
        body = {"all": True, "created_before": utc_now.isoformat().replace("+00:00", "Z")}

        response = client.post("/api/conversations/bulk-trash", json=body, headers=auth_headers)

        assert response.get_json() == {"trashed_ids": [conv.id]}

    def test_bulk_trash_rejects_bad_shapes(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        url = "/api/conversations/bulk-trash"
        too_many = [f"id-{i}" for i in range(Config.CONVERSATIONS_BULK_MAX_IDS + 1)]
        for body in (
            {},
            {"ids": []},
            {"all": True},
            {"ids": ["a"], "exclude_ids": ["b"]},
            {"ids": ["a"], "created_before": "2026-01-01T00:00:00"},
            {"ids": too_many},
        ):
            response = client.post(url, json=body, headers=auth_headers)
            assert response.status_code == 400, body

    def test_bulk_restore(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "A")
        test_database.trash_conversation(conv.id, test_user.id)

        response = client.post(
            "/api/conversations/bulk-restore", json={"ids": [conv.id]}, headers=auth_headers
        )

        assert response.get_json() == {"restored_ids": [conv.id]}
        assert client.get(f"/api/conversations/{conv.id}", headers=auth_headers).status_code == 200

    def test_bulk_routes_require_auth(self, client: FlaskClient) -> None:
        assert client.post("/api/conversations/bulk-trash", json={"ids": ["a"]}).status_code == 401
        assert (
            client.post("/api/conversations/bulk-restore", json={"ids": ["a"]}).status_code == 401
        )
