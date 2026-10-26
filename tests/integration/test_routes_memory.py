"""Integration tests for the memory routes (list, delete, restore, protect)."""

from flask.testing import FlaskClient

from src.db.models import Database, User


class TestMemoryRoutes:
    def test_list_memories(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        test_database.add_memory(test_user.id, "Likes tea", category="preference")

        response = client.get("/api/memories", headers=auth_headers)
        assert response.status_code == 200
        memories = response.get_json()["memories"]
        assert len(memories) == 1
        assert memories[0]["content"] == "Likes tea"
        assert memories[0]["category"] == "preference"

    def test_delete_memory(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Temp fact")

        assert client.delete(f"/api/memories/{memory.id}", headers=auth_headers).status_code == 200
        assert client.get("/api/memories", headers=auth_headers).get_json()["memories"] == []

    def test_delete_missing_memory_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.delete("/api/memories/mem-nope", headers=auth_headers).status_code == 404

    def test_cannot_delete_other_users_memory(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
    ) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        memory = test_database.add_memory(other.id, "Their secret")

        assert client.delete(f"/api/memories/{memory.id}", headers=auth_headers).status_code == 404
        assert test_database.list_memories(other.id)  # untouched

    def test_list_reports_the_server_side_limit(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """The UI reads the cap from the API instead of hardcoding its own copy."""
        from src.config import Config

        response = client.get("/api/memories", headers=auth_headers)

        assert response.get_json()["limit"] == Config.MEMORY_MAX_ENTRIES

    def test_deleted_memory_can_be_listed_and_restored(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Deletes are recoverable during the retention window."""
        memory = test_database.add_memory(test_user.id, "Deleted by mistake")
        client.delete(f"/api/memories/{memory.id}", headers=auth_headers)

        deleted = client.get("/api/memories/deleted", headers=auth_headers).get_json()["memories"]
        assert [m["id"] for m in deleted] == [memory.id]
        assert deleted[0]["deleted_at"] is not None

        restore = client.post(f"/api/memories/{memory.id}/restore", headers=auth_headers)
        assert restore.status_code == 200

        live = client.get("/api/memories", headers=auth_headers).get_json()["memories"]
        assert [m["id"] for m in live] == [memory.id]

    def test_restoring_a_live_memory_is_404(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        memory = test_database.add_memory(test_user.id, "Never deleted")

        response = client.post(f"/api/memories/{memory.id}/restore", headers=auth_headers)

        assert response.status_code == 404

    def test_protection_can_be_toggled(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Protecting a memory blocks LLM/defrag deletion but not the user's own."""
        memory = test_database.add_memory(test_user.id, "Allergic to shellfish")

        response = client.patch(
            f"/api/memories/{memory.id}/protection",
            json={"protected": True},
            headers=auth_headers,
        )
        assert response.status_code == 200

        listed = client.get("/api/memories", headers=auth_headers).get_json()["memories"]
        assert listed[0]["protected"] is True

        # The LLM path is refused...
        assert test_database.delete_memory(memory.id, test_user.id) is False
        # ...but the user's own delete goes through
        assert client.delete(f"/api/memories/{memory.id}", headers=auth_headers).status_code == 200

    def test_cannot_protect_other_users_memory(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
    ) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        memory = test_database.add_memory(other.id, "Their fact")

        response = client.patch(
            f"/api/memories/{memory.id}/protection",
            json={"protected": True},
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_source_conversation_is_exposed(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Provenance answers "why do you know this?"."""
        conv = test_database.create_conversation(test_user.id, "Where it came from")
        test_database.add_memory(test_user.id, "Runs marathons", source_conversation_id=conv.id)

        listed = client.get("/api/memories", headers=auth_headers).get_json()["memories"]

        assert listed[0]["source_conversation_id"] == conv.id

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/memories").status_code == 401
        assert client.get("/api/memories/deleted").status_code == 401
