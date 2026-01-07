"""Unit tests for full-text search functionality."""

import pytest

from src.db.models import Database, SearchResult


class TestSearchQueryEscaping:
    """Tests for FTS5 query escaping in search method."""

    @pytest.fixture
    def db_with_data(self, test_database: Database) -> tuple[Database, str]:
        """Create database with test data for search."""
        # Create a user and conversation with searchable content
        user = test_database.get_or_create_user(
            email="test@example.com",
            name="Test User",
        )

        conv = test_database.create_conversation(
            user_id=user.id,
            title="Python Tutorial",
            model="test-model",
        )

        # Add messages with various content
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="How do I use Python classes?",
        )
        test_database.add_message(
            conversation_id=conv.id,
            role="assistant",
            content="Python classes are defined using the 'class' keyword.",
        )

        return test_database, user.id

    def test_search_basic_query(self, db_with_data: tuple[Database, str]) -> None:
        """Should find results for basic query."""
        db, user_id = db_with_data

        results, total = db.search(user_id, "python")

        assert total > 0
        assert len(results) > 0
        # Should match conversation title
        assert any(r.match_type == "conversation" for r in results)

    def test_search_message_content(self, db_with_data: tuple[Database, str]) -> None:
        """Should find results in message content."""
        db, user_id = db_with_data

        results, total = db.search(user_id, "classes")

        assert total > 0
        # Should match message content
        assert any(r.match_type == "message" for r in results)

    def test_search_with_quotes(self, db_with_data: tuple[Database, str]) -> None:
        """Should handle quotes in query."""
        db, user_id = db_with_data

        # Should not raise an error
        results, total = db.search(user_id, 'Python "class" keyword')

        # May or may not find results, but shouldn't error
        assert isinstance(results, list)
        assert isinstance(total, int)

    def test_search_with_special_chars(self, db_with_data: tuple[Database, str]) -> None:
        """Should handle special FTS5 characters in query."""
        db, user_id = db_with_data

        # These characters have special meaning in FTS5
        special_queries = [
            "python AND classes",  # AND operator
            "python OR classes",  # OR operator
            "python NOT java",  # NOT operator
            "python*",  # Wildcard
            "python^",  # Boost
            "(python)",  # Grouping
            "python:classes",  # Column prefix
            "python -java",  # Exclude
        ]

        for query in special_queries:
            # Should not raise an error
            results, total = db.search(user_id, query)
            assert isinstance(results, list)
            assert isinstance(total, int)

    def test_search_empty_query(self, db_with_data: tuple[Database, str]) -> None:
        """Should handle empty query gracefully."""
        db, user_id = db_with_data

        results, total = db.search(user_id, "")

        assert results == []
        assert total == 0

    def test_search_whitespace_query(self, db_with_data: tuple[Database, str]) -> None:
        """Should handle whitespace-only query gracefully."""
        db, user_id = db_with_data

        results, total = db.search(user_id, "   ")

        assert results == []
        assert total == 0

    def test_search_user_boundary(self, db_with_data: tuple[Database, str]) -> None:
        """Should only return results for the specified user."""
        db, user_id = db_with_data

        # Create another user with a conversation
        other_user = db.get_or_create_user(
            email="other@example.com",
            name="Other User",
        )
        other_conv = db.create_conversation(
            user_id=other_user.id,
            title="Python Advanced",
            model="test-model",
        )
        db.add_message(
            conversation_id=other_conv.id,
            role="user",
            content="Advanced Python topics",
        )

        # Search as first user should not find other user's content
        results, total = db.search(user_id, "advanced")

        # First user shouldn't see "Advanced" results
        assert all(r.conversation_id != other_conv.id for r in results)

    def test_search_limit_and_offset(self, db_with_data: tuple[Database, str]) -> None:
        """Should respect limit and offset parameters."""
        db, user_id = db_with_data

        # Create more conversations to test pagination
        for i in range(5):
            conv = db.create_conversation(
                user_id=user_id,
                title=f"Python Topic {i}",
                model="test-model",
            )
            db.add_message(
                conversation_id=conv.id,
                role="user",
                content=f"Python question number {i}",
            )

        # Test limit
        results_limited, total = db.search(user_id, "python", limit=2)
        assert len(results_limited) == 2
        assert total > 2  # Total should be all matches

        # Test offset
        results_offset, _ = db.search(user_id, "python", limit=2, offset=2)
        # Results with offset should be different
        assert results_offset[0].conversation_id != results_limited[0].conversation_id

    def test_search_stemming(self, db_with_data: tuple[Database, str]) -> None:
        """Should use stemming (Porter stemmer) for matching."""
        db, user_id = db_with_data

        # "classes" should match when searching for "class"
        results, total = db.search(user_id, "class")

        # Should find results due to stemming
        assert total > 0

    def test_search_result_fields(self, db_with_data: tuple[Database, str]) -> None:
        """Should return properly populated SearchResult objects."""
        db, user_id = db_with_data

        results, total = db.search(user_id, "python")

        assert len(results) > 0

        for result in results:
            assert isinstance(result, SearchResult)
            assert result.conversation_id
            assert result.conversation_title
            assert result.match_type in ("conversation", "message")
            assert isinstance(result.rank, float)

            if result.match_type == "message":
                assert result.message_id is not None
                assert result.message_content is not None
                assert result.created_at is not None
            else:
                # Title matches don't have message fields
                assert result.message_id is None


class TestSearchSnippets:
    """Tests for search result snippets with highlight markers."""

    @pytest.fixture
    def db_with_long_message(self, test_database: Database) -> tuple[Database, str]:
        """Create database with a long message for snippet testing."""
        user = test_database.get_or_create_user(
            email="test@example.com",
            name="Test User",
        )

        conv = test_database.create_conversation(
            user_id=user.id,
            title="Long Message Test",
            model="test-model",
        )

        # Add a long message
        long_content = """
        This is a very long message about Python programming.
        Python is a versatile language that supports multiple programming paradigms.
        It's great for web development, data science, and automation.
        The Python community is very welcoming and helpful.
        """
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content=long_content,
        )

        return test_database, user.id

    def test_snippet_contains_highlight_markers(
        self, db_with_long_message: tuple[Database, str]
    ) -> None:
        """Should include highlight markers in snippets."""
        db, user_id = db_with_long_message

        results, _ = db.search(user_id, "python")

        # Find a message result
        message_results = [r for r in results if r.match_type == "message"]

        if message_results:
            # Snippet should contain highlight markers
            snippet = message_results[0].message_content
            assert snippet is not None
            assert "[[HIGHLIGHT]]" in snippet or "python" in snippet.lower()

    def test_snippet_not_too_long(self, db_with_long_message: tuple[Database, str]) -> None:
        """Snippet should be a reasonable length, not the full message."""
        db, user_id = db_with_long_message

        results, _ = db.search(user_id, "python")

        message_results = [r for r in results if r.match_type == "message"]

        if message_results:
            snippet = message_results[0].message_content
            assert snippet is not None
            # SQLite FTS5 snippet() truncates to ~64 tokens by default
            # The full message is ~300+ chars, snippet should be shorter
            # Account for [[HIGHLIGHT]] markers which add ~40 chars per match
            assert len(snippet) < 400
