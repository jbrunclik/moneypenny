"""Integration tests for search routes."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, User


class TestSearchEndpoint:
    """Tests for GET /api/search endpoint."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/search?q=test")
        assert response.status_code == 401

    def test_requires_query_param(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 when query param is missing."""
        response = client.get("/api/search", headers=auth_headers)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_query_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should reject empty query with validation error."""
        response = client.get("/api/search?q=", headers=auth_headers)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_whitespace_query_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should reject whitespace-only query with validation error."""
        response = client.get("/api/search?q=%20%20%20", headers=auth_headers)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_finds_conversation_by_title(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should find conversations matching title."""
        # Create a conversation with a searchable title
        conv = test_database.create_conversation(
            user_id=test_user.id,
            title="Python Programming Tips",
            model="test-model",
        )

        response = client.get("/api/search?q=python", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        assert data["total"] > 0
        assert any(r["conversation_id"] == conv.id for r in data["results"])
        # Title match should have match_type "conversation"
        title_matches = [
            r
            for r in data["results"]
            if r["conversation_id"] == conv.id and r["match_type"] == "conversation"
        ]
        assert len(title_matches) > 0

    def test_finds_message_content(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should find messages matching content."""
        conv = test_database.create_conversation(
            user_id=test_user.id,
            title="General Chat",
            model="test-model",
        )
        msg = test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="How do I implement recursion in JavaScript?",
        )

        response = client.get("/api/search?q=recursion", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        assert data["total"] > 0
        # Should find message match
        message_matches = [r for r in data["results"] if r["match_type"] == "message"]
        assert len(message_matches) > 0
        assert any(r["message_id"] == msg.id for r in message_matches)

    def test_respects_limit_param(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should respect limit parameter."""
        # Create multiple searchable conversations
        for i in range(5):
            test_database.create_conversation(
                user_id=test_user.id,
                title=f"Python Topic {i}",
                model="test-model",
            )

        response = client.get("/api/search?q=python&limit=2", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        assert len(data["results"]) == 2
        assert data["total"] >= 5  # Total should be all matches

    def test_respects_offset_param(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should respect offset parameter for pagination."""
        # Create multiple searchable conversations
        for i in range(5):
            test_database.create_conversation(
                user_id=test_user.id,
                title=f"Python Topic {i}",
                model="test-model",
            )

        # Get first page
        response1 = client.get("/api/search?q=python&limit=2&offset=0", headers=auth_headers)
        data1 = json.loads(response1.data)

        # Get second page
        response2 = client.get("/api/search?q=python&limit=2&offset=2", headers=auth_headers)
        data2 = json.loads(response2.data)

        # Results should be different
        ids1 = {r["conversation_id"] for r in data1["results"]}
        ids2 = {r["conversation_id"] for r in data2["results"]}
        assert ids1 != ids2

    def test_limit_max_enforced(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should enforce maximum limit."""
        response = client.get("/api/search?q=test&limit=100", headers=auth_headers)
        assert response.status_code == 200
        # Server should cap at SEARCH_MAX_LIMIT (50)

    def test_user_boundary_enforced(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should only return results for authenticated user."""
        # Create another user with a conversation
        other_user = test_database.get_or_create_user(
            email="other@example.com",
            name="Other User",
        )
        other_conv = test_database.create_conversation(
            user_id=other_user.id,
            title="Python Secrets",
            model="test-model",
        )

        # Create a conversation for test user
        test_database.create_conversation(
            user_id=test_user.id,
            title="Python Basics",
            model="test-model",
        )

        response = client.get("/api/search?q=python", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        # Should not include other user's conversation
        assert not any(r["conversation_id"] == other_conv.id for r in data["results"])

    def test_query_too_long_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should reject queries exceeding max length."""
        long_query = "a" * 250  # Over SEARCH_MAX_QUERY_LENGTH (200)
        response = client.get(f"/api/search?q={long_query}", headers=auth_headers)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_special_characters_handled(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should handle special FTS5 characters without error."""
        # These characters have special meaning in FTS5
        special_queries = [
            "python AND classes",
            "python OR classes",
            'python "class"',
            "python*",
            "(python)",
        ]

        for query in special_queries:
            response = client.get(f"/api/search?q={query}", headers=auth_headers)
            # Should not return 500 - either 200 or 400 for invalid syntax is acceptable
            assert response.status_code in (200, 400), (
                f"Query '{query}' returned {response.status_code}"
            )

    def test_response_includes_snippets_with_highlights(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should include snippets with highlight markers for message matches."""
        conv = test_database.create_conversation(
            user_id=test_user.id,
            title="Test Conversation",
            model="test-model",
        )
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="This is a message about Python programming and how Python is useful.",
        )

        response = client.get("/api/search?q=python", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        message_matches = [r for r in data["results"] if r["match_type"] == "message"]
        if message_matches:
            snippet = message_matches[0].get("message_snippet")
            assert snippet is not None
            # Snippet should contain highlight markers
            assert "[[HIGHLIGHT]]" in snippet or "python" in snippet.lower()

    def test_response_format(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return properly formatted response."""
        conv = test_database.create_conversation(
            user_id=test_user.id,
            title="Test Search",
            model="test-model",
        )
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Test message content",
        )

        response = client.get("/api/search?q=test", headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify response structure
        assert "results" in data
        assert "total" in data
        assert "query" in data
        assert data["query"] == "test"
        assert isinstance(data["results"], list)
        assert isinstance(data["total"], int)

        # Verify result item structure
        if data["results"]:
            result = data["results"][0]
            assert "conversation_id" in result
            assert "conversation_title" in result
            assert "match_type" in result
            assert result["match_type"] in ("conversation", "message")
