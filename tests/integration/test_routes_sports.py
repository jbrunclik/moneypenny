"""Integration tests for sports tracking routes.

Tests cover:
- GET /api/sports/programs — List programs
- POST /api/sports/programs — Create program
- DELETE /api/sports/programs/<id> — Delete program
- GET /api/sports/<program>/conversation — Get/create conversation
- POST /api/sports/<program>/reset — Reset conversation
"""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, User


def _setup_program(test_database: "Database", user_id: str, program_id: str = "pushups") -> None:
    """Helper to set up a program in KV store."""
    programs = [
        {
            "id": program_id,
            "name": "Push-ups",
            "emoji": "\U0001f4aa",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    test_database.kv_set(user_id, "sports", "programs", json.dumps(programs))


class TestListPrograms:
    """Tests for GET /api/sports/programs."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/sports/programs")
        assert response.status_code == 401

    def test_returns_empty_programs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return empty list when no programs exist."""
        response = client.get("/api/sports/programs", headers=auth_headers)
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
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")

        response = client.get("/api/sports/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["id"] == "pushups"
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

        response = client.get("/api/sports/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["has_conversation"] is False


class TestCreateProgram:
    """Tests for POST /api/sports/programs."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post(
            "/api/sports/programs",
            json={"name": "Test", "emoji": "\U0001f4aa"},
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
            "/api/sports/programs",
            headers=auth_headers,
            json={
                "name": "Push-ups",
                "emoji": "\U0001f4aa",
            },
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["name"] == "Push-ups"
        assert data["programs"][0]["id"] == "push-ups"

    def test_creates_unique_slugs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: "Database",
        test_user: "User",
    ) -> None:
        """Should create unique slugs for duplicate names."""
        client.post(
            "/api/sports/programs",
            headers=auth_headers,
            json={"name": "Running", "emoji": "\U0001f3c3"},
        )
        response = client.post(
            "/api/sports/programs",
            headers=auth_headers,
            json={"name": "Running", "emoji": "\U0001f3c3"},
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["programs"][0]["id"] == "running-2"

    def test_missing_required_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 when required fields are missing."""
        response = client.post(
            "/api/sports/programs",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 400


class TestDeleteProgram:
    """Tests for DELETE /api/sports/programs/<id>."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/sports/programs/pushups")
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
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.kv_set(test_user.id, "sports", "pushups:goals", '{"goal": "100"}')

        response = client.delete("/api/sports/programs/pushups", headers=auth_headers)
        assert response.status_code == 200

        # Verify program removed from KV
        raw = test_database.kv_get(test_user.id, "sports", "programs")
        programs = json.loads(raw) if raw else []
        assert len(programs) == 0

        # Verify conversation deleted
        conv = test_database.get_sports_conversation(test_user.id, "pushups")
        assert conv is None

        # Verify KV data cleaned up
        assert test_database.kv_get(test_user.id, "sports", "pushups:goals") is None

    def test_returns_404_for_nonexistent(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 for non-existent program."""
        response = client.delete("/api/sports/programs/nonexistent", headers=auth_headers)
        assert response.status_code == 404


class TestGetSportsConversation:
    """Tests for GET /api/sports/<program>/conversation."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/sports/pushups/conversation")
        assert response.status_code == 401

    def test_returns_404_for_nonexistent_program(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when program doesn't exist in KV."""
        response = client.get("/api/sports/nonexistent/conversation", headers=auth_headers)
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

        response = client.get("/api/sports/pushups/conversation", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["program"] == "pushups"
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
        conv = test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Start my training",
        )

        response = client.get("/api/sports/pushups/conversation", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["messages"]) == 1
        assert data["id"] == conv.id


class TestResetSportsConversation:
    """Tests for POST /api/sports/<program>/reset."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/sports/pushups/reset")
        assert response.status_code == 401

    def test_returns_404_when_no_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when conversation doesn't exist."""
        response = client.post("/api/sports/nonexistent/reset", headers=auth_headers)
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
        conv = test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Hello",
        )

        response = client.post("/api/sports/pushups/reset", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify messages deleted
        messages = test_database.get_messages(conv.id)
        assert len(messages) == 0
