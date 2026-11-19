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


def _setup_program(test_database: Database, user_id: str, program_id: str = "pushups") -> None:
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
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return programs and indicate which have conversations."""
        _setup_program(test_database, test_user.id)
        # Create a conversation for the program
        test_database.get_or_create_program_conversation("sports", test_user.id, "pushups")

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
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should show has_conversation=False for programs without conversations."""
        _setup_program(test_database, test_user.id)

        response = client.get("/api/sports/programs", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["programs"]) == 1
        assert data["programs"][0]["has_conversation"] is False


class TestProgramActivity:
    """The card's "Last session 2d ago · 12 sessions" (Nov 19 2026): sessions are
    the local days the user wrote in the program's chat; the last one is when
    the coach last logged a session, else the user's last message there."""

    def _chat(self, test_database: Database, user_id: str) -> str:
        _setup_program(test_database, user_id)
        conv = test_database.get_or_create_program_conversation("sports", user_id, "pushups")
        return conv.id

    def _say(self, test_database: Database, conv_id: str, text: str, at: str) -> None:
        from src.db.models.timestamps import from_db

        msg = test_database.add_message(conv_id, "user", text)
        test_database.set_message_created_at(msg.id, from_db(at))

    def _program(self, client: FlaskClient, auth_headers: dict[str, str]) -> dict:
        response = client.get("/api/sports/programs", headers=auth_headers)
        assert response.status_code == 200
        return json.loads(response.data)["programs"][0]

    def test_counts_local_days_with_a_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv_id = self._chat(test_database, test_user.id)
        # Nov 17 twice, then 23:30 UTC on Nov 18 = Nov 19 00:30 in Prague
        self._say(test_database, conv_id, "done 3x12", "2026-11-17T07:00:00Z")
        self._say(test_database, conv_id, "and stretching", "2026-11-17T18:00:00Z")
        self._say(test_database, conv_id, "late one", "2026-11-18T23:30:00Z")
        self._say(test_database, conv_id, "[System: session-start]", "2026-11-16T07:00:00Z")

        program = self._program(client, auth_headers)
        assert program["session_count"] == 2
        assert program["last_session_at"].startswith("2026-11-18T23:30:00")

    def test_the_coachs_log_is_the_last_session(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv_id = self._chat(test_database, test_user.id)
        self._say(test_database, conv_id, "done", "2026-11-10T07:00:00Z")
        test_database.kv_set(test_user.id, "sports", "pushups:last_session", "3x12 at 60 kg")

        program = self._program(client, auth_headers)
        assert program["session_count"] == 1
        assert program["last_session_at"] > "2026-11-10T07:00:00"

    def test_a_new_program_has_none(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        _setup_program(test_database, test_user.id)
        program = self._program(client, auth_headers)
        assert (program["session_count"], program["last_session_at"]) == (0, None)


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
        test_database: Database,
        test_user: User,
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
        test_database: Database,
        test_user: User,
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
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should delete program, conversation, and KV data."""
        _setup_program(test_database, test_user.id)
        test_database.get_or_create_program_conversation("sports", test_user.id, "pushups")
        test_database.kv_set(test_user.id, "sports", "pushups:goals", '{"goal": "100"}')

        response = client.delete("/api/sports/programs/pushups", headers=auth_headers)
        assert response.status_code == 200

        # Verify program removed from KV
        raw = test_database.kv_get(test_user.id, "sports", "programs")
        programs = json.loads(raw) if raw else []
        assert len(programs) == 0

        # Verify conversation deleted
        assert test_database.list_program_conversations("sports", test_user.id) == []

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
        test_database: Database,
        test_user: User,
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
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return existing conversation with messages."""
        _setup_program(test_database, test_user.id)
        conv = test_database.get_or_create_program_conversation("sports", test_user.id, "pushups")
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
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should clear messages and return success."""
        _setup_program(test_database, test_user.id)
        conv = test_database.get_or_create_program_conversation("sports", test_user.id, "pushups")
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
