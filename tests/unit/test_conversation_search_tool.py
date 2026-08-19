"""Unit tests for the conversation search / read tools (episodic recall)."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.conversation_search import read_conversation, search_conversations
from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


@pytest.fixture
def search_context(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[Database, User]]:
    """Point the tools' module-level db at the test database."""
    import src.agent.tools.conversation_search as module

    monkeypatch.setattr(module, "db", test_database)
    set_conversation_context("current-conv", test_user.id)
    yield test_database, test_user
    set_conversation_context(None, None)


def _conversation_with_message(
    database: Database, user: User, title: str, content: str
) -> Conversation:
    """Create a conversation holding one user message."""
    conv = database.create_conversation(user.id, title)
    database.add_message(conv.id, "user", content)
    return conv


class TestSearchConversations:
    """Searching the user's own history."""

    def test_finds_message_content(self, search_context: tuple[Database, User]) -> None:
        """Should find a conversation by words in its messages."""
        database, user = search_context
        _conversation_with_message(
            database, user, "Bathroom reno", "We picked the hexagonal tiles for the bathroom"
        )

        result = str(search_conversations.invoke({"query": "hexagonal tiles"}))

        assert "Bathroom reno" in result
        assert "Found 1 match" in result

    def test_excludes_the_current_conversation(self, search_context: tuple[Database, User]) -> None:
        """The current conversation is already in context, so it is noise here."""
        database, user = search_context
        conv = database.create_conversation(user.id, "Ongoing chat")
        database.add_message(conv.id, "user", "unmistakable-keyword-xyz")
        set_conversation_context(conv.id, user.id)

        result = str(search_conversations.invoke({"query": "unmistakable-keyword-xyz"}))

        assert "Ongoing chat" not in result

    def test_no_matches_suggests_rephrasing(self, search_context: tuple[Database, User]) -> None:
        """A miss should be actionable, not just empty."""
        result = str(search_conversations.invoke({"query": "nothing-here-at-all"}))

        assert "No past conversations matched" in result

    def test_does_not_leak_other_users_conversations(
        self, search_context: tuple[Database, User]
    ) -> None:
        """Search is scoped to the calling user."""
        database, _user = search_context
        other = database.get_or_create_user(email="other@example.com", name="Other")
        _conversation_with_message(database, other, "Their chat", "their-private-keyword")

        result = str(search_conversations.invoke({"query": "their-private-keyword"}))

        assert "Their chat" not in result

    def test_empty_query_is_rejected(self, search_context: tuple[Database, User]) -> None:
        """Should ask for a query rather than dumping everything."""
        assert "required" in str(search_conversations.invoke({"query": "   "}))

    def test_limit_is_clamped(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An over-large limit must not pull unbounded history into context."""
        database, user = search_context
        monkeypatch.setattr(Config, "CONVERSATION_SEARCH_MAX_RESULTS", 2)
        for i in range(5):
            _conversation_with_message(database, user, f"Chat {i}", "shared-keyword here")

        result = str(search_conversations.invoke({"query": "shared-keyword", "limit": 99}))

        assert result.count("conversation_id=") == 2

    def test_requires_user_context(self) -> None:
        """Should refuse without a user rather than searching globally."""
        set_conversation_context(None, None)

        assert "no user context" in str(search_conversations.invoke({"query": "anything"})).lower()


class TestReadConversation:
    """Reading a specific past conversation."""

    def test_returns_messages_in_order(self, search_context: tuple[Database, User]) -> None:
        """Should render the exchange chronologically with roles."""
        database, user = search_context
        conv = database.create_conversation(user.id, "Recipe chat")
        database.add_message(conv.id, "user", "How do I make pesto?")
        database.add_message(conv.id, "assistant", "Blend basil, pine nuts and parmesan.")

        result = str(read_conversation.invoke({"conversation_id": conv.id}))

        assert "Recipe chat" in result
        assert result.index("How do I make pesto?") < result.index("Blend basil")

    def test_refuses_another_users_conversation(
        self, search_context: tuple[Database, User]
    ) -> None:
        """Ownership is enforced; a foreign ID looks like a missing one."""
        database, _user = search_context
        other = database.get_or_create_user(email="other@example.com", name="Other")
        theirs = _conversation_with_message(database, other, "Private", "secret content")

        result = str(read_conversation.invoke({"conversation_id": theirs.id}))

        assert "was found" in result
        assert "secret content" not in result

    def test_unknown_conversation_is_reported(self, search_context: tuple[Database, User]) -> None:
        """Should report a missing conversation rather than erroring."""
        assert "was found" in str(read_conversation.invoke({"conversation_id": "nope"}))

    def test_truncates_long_history(self, search_context: tuple[Database, User]) -> None:
        """Should return the most recent messages and say it truncated."""
        database, user = search_context
        conv = database.create_conversation(user.id, "Long chat")
        for i in range(10):
            database.add_message(conv.id, "user", f"message number {i}")

        result = str(read_conversation.invoke({"conversation_id": conv.id, "max_messages": 3}))

        assert "earlier messages omitted" in result
        assert "message number 9" in result
        assert "message number 0" not in result

    def test_truncates_oversized_message_bodies(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One huge message must not blow up the context window."""
        database, user = search_context
        monkeypatch.setattr(Config, "CONVERSATION_READ_MAX_CHARS_PER_MESSAGE", 20)
        conv = database.create_conversation(user.id, "Verbose")
        database.add_message(conv.id, "user", "y" * 500)

        result = str(read_conversation.invoke({"conversation_id": conv.id}))

        assert "(truncated)" in result
        assert "y" * 500 not in result


class TestSemanticConversationSearch:
    """Embedding-based matches complement FTS keyword matches."""

    def test_semantic_match_found_without_keyword_overlap(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module
        from src.utils.embeddings import pack_vector

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        # Silence the add_message embedding hook (no live API attempts)
        monkeypatch.setattr("src.utils.embeddings.embed_and_store_async", lambda *args: None)
        database, user = search_context
        conv = _conversation_with_message(
            database, user, "Pet chat", "Max loves playing fetch in the park"
        )
        message = database.get_messages(conv.id)[0]
        database.upsert_embedding(
            user.id, "message", message.id, "test-model", 2, pack_vector([1.0, 0.0])
        )
        monkeypatch.setattr(module, "embed_text", lambda text: [1.0, 0.1])

        result = str(search_conversations.invoke({"query": "what does my dog enjoy"}))

        assert "Pet chat" in result
        assert "semantic match" in result

    def test_embed_failure_degrades_to_fts_only(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        # Silence the add_message embedding hook (no live API attempts)
        monkeypatch.setattr("src.utils.embeddings.embed_and_store_async", lambda *args: None)
        monkeypatch.setattr(module, "embed_text", lambda text: None)
        database, user = search_context
        _conversation_with_message(database, user, "Keyword chat", "contains magicword here")

        result = str(search_conversations.invoke({"query": "magicword"}))

        assert "Keyword chat" in result

    def test_semantic_does_not_duplicate_fts_hit(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module
        from src.utils.embeddings import pack_vector

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        # Silence the add_message embedding hook (no live API attempts)
        monkeypatch.setattr("src.utils.embeddings.embed_and_store_async", lambda *args: None)
        database, user = search_context
        conv = _conversation_with_message(database, user, "Tiles", "hexagonal tiles decision")
        message = database.get_messages(conv.id)[0]
        database.upsert_embedding(
            user.id, "message", message.id, "test-model", 2, pack_vector([1.0, 0.0])
        )
        monkeypatch.setattr(module, "embed_text", lambda text: [1.0, 0.0])

        result = str(search_conversations.invoke({"query": "hexagonal tiles"}))

        assert result.count("Tiles") == 1
