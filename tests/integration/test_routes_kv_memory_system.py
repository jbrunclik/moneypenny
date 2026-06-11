"""Integration tests for the kv_store, memory and system route modules (T2)."""

from flask.testing import FlaskClient

from src.db.models import Database, User


class TestKVStoreRoutes:
    def test_set_get_roundtrip(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        put = client.put(
            "/api/kv/notes/today",
            headers=auth_headers,
            json={"value": '{"items": [1, 2]}'},
        )
        assert put.status_code == 200

        get = client.get("/api/kv/notes/today", headers=auth_headers)
        assert get.status_code == 200
        data = get.get_json()
        assert data["namespace"] == "notes"
        assert data["key"] == "today"
        assert data["value"] == '{"items": [1, 2]}'

    def test_set_rejects_invalid_json(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.put(
            "/api/kv/notes/bad",
            headers=auth_headers,
            json={"value": "not json"},
        )
        assert response.status_code == 400

    def test_set_rejects_long_key(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.put(
            f"/api/kv/notes/{'k' * 257}",
            headers=auth_headers,
            json={"value": "{}"},
        )
        assert response.status_code == 400

    def test_get_missing_key_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.get("/api/kv/notes/missing", headers=auth_headers).status_code == 404

    def test_list_namespaces_and_keys(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        client.put("/api/kv/proj/a", headers=auth_headers, json={"value": "1"})
        client.put("/api/kv/proj/b", headers=auth_headers, json={"value": "2"})

        namespaces = client.get("/api/kv", headers=auth_headers).get_json()["namespaces"]
        assert {"namespace": "proj", "key_count": 2} in namespaces

        keys = client.get("/api/kv/proj", headers=auth_headers).get_json()["keys"]
        assert sorted(k["key"] for k in keys) == ["a", "b"]

    def test_delete_key_and_404_on_missing(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        client.put("/api/kv/proj/a", headers=auth_headers, json={"value": "1"})
        assert client.delete("/api/kv/proj/a", headers=auth_headers).status_code == 200
        assert client.delete("/api/kv/proj/a", headers=auth_headers).status_code == 404

    def test_clear_namespace(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        client.put("/api/kv/tmp/a", headers=auth_headers, json={"value": "1"})
        client.put("/api/kv/tmp/b", headers=auth_headers, json={"value": "2"})

        response = client.delete("/api/kv/tmp", headers=auth_headers)
        assert response.status_code == 200
        assert "2" in response.get_json()["status"]
        assert client.get("/api/kv/tmp", headers=auth_headers).get_json()["keys"] == []

    def test_kv_is_per_user(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
    ) -> None:
        """Another user's keys must not be visible."""
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        test_database.kv_set(other.id, "notes", "secret", '"theirs"')

        assert client.get("/api/kv/notes/secret", headers=auth_headers).status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/kv").status_code == 401


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

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/memories").status_code == 401


class TestSystemRoutes:
    def test_health(self, client: FlaskClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_ready(self, client: FlaskClient) -> None:
        response = client.get("/api/ready")
        assert response.status_code == 200

    def test_version(self, client: FlaskClient) -> None:
        response = client.get("/api/version")
        assert response.status_code == 200
        assert "version" in response.get_json()

    def test_models_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/models").status_code == 401

    def test_models_lists_configured_models(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/models", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["models"]) > 0
        assert data["default"]

    def test_upload_config(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/api/config/upload", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data["maxFileSize"] > 0
        assert len(data["allowedFileTypes"]) > 0
