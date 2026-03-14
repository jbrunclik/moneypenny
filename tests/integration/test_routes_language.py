"""Integration tests for language learning routes.

Tests cover:
- GET /api/language/programs — List programs
- POST /api/language/programs — Create program
- DELETE /api/language/programs/<id> — Delete program
- GET /api/language/<program>/conversation — Get/create conversation
- POST /api/language/<program>/reset — Reset conversation
"""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, User


def _setup_program(test_database: "Database", user_id: str, program_id: str = "spanish") -> None:
    """Helper to set up a language program in KV store."""
    programs = [
        {
            "id": program_id,
            "name": "Spanish",
            "emoji": "\U0001f1ea\U0001f1f8",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    test_database.kv_set(user_id, "language", "programs", json.dumps(programs))


class TestListPrograms:
    """Tests for GET /api/language/programs."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/language/programs")
        assert response.status_code == 401

    def test_returns_empty_programs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return empty list when no programs exist."""
        response = client.get("/api/language/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["programs"] == []

    def test_returns_programs_with_conversation_status(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should return programs and indicate which have conversations."""
        _setup_program(test_database, test_user.id)
        # Create a conversation for the program
        test_database.get_or_create_language_conversation(test_user.id, "spanish")

        response = client.get("/api/language/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["id"] == "spanish"
        assert data["programs"][0]["has_conversation"] is True

    def test_program_without_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should show has_conversation=False for programs without conversations."""
        _setup_program(test_database, test_user.id)

        response = client.get("/api/language/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["has_conversation"] is False


class TestCreateProgram:
    """Tests for POST /api/language/programs."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/api/language/programs",
            json={"name": "Test", "emoji": "\U0001f1ec\U0001f1e7"},
        )
        assert response.status_code == 401

    def test_creates_program(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should create a new program."""
        response = client.post(
            "/api/language/programs",
            headers=auth_headers,
            json={
                "name": "Spanish",
                "emoji": "\U0001f1ea\U0001f1f8",
            },
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["name"] == "Spanish"
        assert data["programs"][0]["id"] == "spanish"

    def test_creates_unique_slugs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should create unique slugs for duplicate names."""
        client.post(
            "/api/language/programs",
            headers=auth_headers,
            json={"name": "French", "emoji": "\U0001f1eb\U0001f1f7"},
        )
        response = client.post(
            "/api/language/programs",
            headers=auth_headers,
            json={"name": "French", "emoji": "\U0001f1eb\U0001f1f7"},
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["programs"][0]["id"] == "french-2"

    def test_missing_required_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 when required fields are missing."""
        response = client.post(
            "/api/language/programs",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 400


class TestDeleteProgram:
    """Tests for DELETE /api/language/programs/<id>."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/language/programs/spanish")
        assert response.status_code == 401

    def test_deletes_program(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should delete program, conversation, and KV data."""
        _setup_program(test_database, test_user.id)
        test_database.get_or_create_language_conversation(test_user.id, "spanish")
        test_database.kv_set(test_user.id, "language", "spanish:vocabulary", '{"words": []}')

        response = client.delete("/api/language/programs/spanish", headers=auth_headers)
        assert response.status_code == 200

        # Verify program removed from KV
        raw = test_database.kv_get(test_user.id, "language", "programs")
        programs = json.loads(raw) if raw else []
        assert len(programs) == 0

        # Verify conversation deleted
        conv = test_database.get_language_conversation(test_user.id, "spanish")
        assert conv is None

        # Verify KV data cleaned up
        assert test_database.kv_get(test_user.id, "language", "spanish:vocabulary") is None

    def test_returns_404_for_nonexistent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 for non-existent program."""
        response = client.delete("/api/language/programs/nonexistent", headers=auth_headers)
        assert response.status_code == 404


class TestGetLanguageConversation:
    """Tests for GET /api/language/<program>/conversation."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/language/spanish/conversation")
        assert response.status_code == 401

    def test_returns_404_for_nonexistent_program(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when program doesn't exist in KV."""
        response = client.get("/api/language/nonexistent/conversation", headers=auth_headers)
        assert response.status_code == 404

    def test_creates_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should create conversation if it doesn't exist."""
        _setup_program(test_database, test_user.id)

        response = client.get("/api/language/spanish/conversation", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["program"] == "spanish"
        assert data["messages"] == []
        assert "id" in data

    def test_returns_existing_conversation_with_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should return existing conversation with messages."""
        _setup_program(test_database, test_user.id)
        conv = test_database.get_or_create_language_conversation(test_user.id, "spanish")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Start my language assessment",
        )

        response = client.get("/api/language/spanish/conversation", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["messages"]) == 1
        assert data["id"] == conv.id


class TestResetLanguageConversation:
    """Tests for POST /api/language/<program>/reset."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/language/spanish/reset")
        assert response.status_code == 401

    def test_returns_404_when_no_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when conversation doesn't exist."""
        response = client.post("/api/language/nonexistent/reset", headers=auth_headers)
        assert response.status_code == 404

    def test_resets_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should clear messages and return success."""
        _setup_program(test_database, test_user.id)
        conv = test_database.get_or_create_language_conversation(test_user.id, "spanish")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Hello",
        )

        response = client.post("/api/language/spanish/reset", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify messages deleted
        messages = test_database.get_messages(conv.id)
        assert len(messages) == 0
