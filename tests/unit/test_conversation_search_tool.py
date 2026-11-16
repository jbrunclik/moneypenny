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

    def test_finds_summarized_part_of_the_current_conversation(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Messages compaction replaced with a summary are no longer verbatim in
        context, so their exact details must stay searchable."""
        import json

        import src.agent.conversation_compaction as compaction

        monkeypatch.setattr(compaction, "db", search_context[0])
        database, user = search_context
        conv = database.create_conversation(user.id, "Long trip chat")
        database.add_message(conv.id, "user", "receipt total was 87 EUR zebrafinch")
        database.add_message(conv.id, "assistant", "noted")
        database.add_message(conv.id, "user", "still verbatim zebrafinch")
        database.kv_set(
            user.id,
            compaction.KV_NAMESPACE,
            conv.id,
            json.dumps({"segments": [{"text": "S", "end": 2, "passes": 1}], "covered_count": 2}),
        )
        set_conversation_context(conv.id, user.id)

        result = str(search_conversations.invoke({"query": "zebrafinch"}))

        assert "87 EUR" in result
        assert "this conversation" in result
        # The verbatim tail is already in the prompt - not repeated
        assert "still verbatim" not in result

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

    def test_empty_query_lists_recent_chats(self, search_context: tuple[Database, User]) -> None:
        """An empty query lists the most recent chats (not the current one)."""
        database, user = search_context
        _conversation_with_message(database, user, "Older chat", "first question")
        _conversation_with_message(database, user, "Newer chat", "second question")
        result = str(search_conversations.invoke({"query": "   "}))
        assert result.index("Newer chat") < result.index("Older chat")
        assert "first question" in result

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
        monkeypatch.setattr(
            "src.db.models.embeddings.EmbeddingsMixin.embed_and_store_async", lambda *args: None
        )
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
        assert "(meaning)" in result

    def test_embed_failure_degrades_to_fts_only(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        # Silence the add_message embedding hook (no live API attempts)
        monkeypatch.setattr(
            "src.db.models.embeddings.EmbeddingsMixin.embed_and_store_async", lambda *args: None
        )
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
        monkeypatch.setattr(
            "src.db.models.embeddings.EmbeddingsMixin.embed_and_store_async", lambda *args: None
        )
        database, user = search_context
        conv = _conversation_with_message(database, user, "Tiles", "hexagonal tiles decision")
        message = database.get_messages(conv.id)[0]
        database.upsert_embedding(
            user.id, "message", message.id, "test-model", 2, pack_vector([1.0, 0.0])
        )
        monkeypatch.setattr(module, "embed_text", lambda text: [1.0, 0.0])

        result = str(search_conversations.invoke({"query": "hexagonal tiles"}))

        assert result.count("Tiles") == 1


class TestSearchAdditions:
    """Hits name their message, agent runs rank below the family's chats, and a
    hit deep in a long chat can be read in its context."""

    def test_hits_carry_their_message_id(self, search_context: tuple[Database, User]) -> None:
        database, user = search_context
        conv = database.create_conversation(user.id, "Garden")
        message = database.add_message(conv.id, "user", "The apricot tree needs pruning in March")

        result = str(search_conversations.invoke({"query": "apricot pruning"}))

        assert f"message_id={message.id}" in result

    def test_scheduled_agent_conversations_rank_below_and_are_labelled(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agent runs are not in the keyword index, but their messages are
        embedded: in the semantic matches they come after the family's chats."""
        import src.agent.tools.conversation_search as module
        from src.utils.embeddings import pack_vector

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        monkeypatch.setattr(
            "src.db.models.embeddings.EmbeddingsMixin.embed_and_store_async", lambda *args: None
        )
        database, user = search_context
        agent = database.create_standing_chat(user.id, "Zoo watcher")
        run = database.add_message(agent.conversation_id, "assistant", "Zoo opening hours today")
        human = _conversation_with_message(database, user, "Weekend", "Shall we visit the animals?")
        human_msg = database.get_messages(human.id)[0]
        # The agent's run is the closer semantic match
        database.upsert_embedding(user.id, "message", run.id, "m", 2, pack_vector([1.0, 0.0]))
        database.upsert_embedding(user.id, "message", human_msg.id, "m", 2, pack_vector([0.8, 0.6]))
        monkeypatch.setattr(module, "embed_text", lambda text: [1.0, 0.0])

        result = str(search_conversations.invoke({"query": "where to take the kids"}))

        assert result.index(f"conversation_id={human.id}") < result.index(
            f"conversation_id={agent.conversation_id}"
        )
        assert "(scheduled agent)" in result

    def test_search_description_says_to_search_before_asking_again(self) -> None:
        assert "Before asking the user to repeat" in search_conversations.description

    def test_read_around_a_message_shows_its_neighbourhood(
        self, search_context: tuple[Database, User]
    ) -> None:
        database, user = search_context
        conv = database.create_conversation(user.id, "Long chat")
        ids = [database.add_message(conv.id, "user", f"message number {i}").id for i in range(60)]

        result = str(
            read_conversation.invoke(
                {"conversation_id": conv.id, "around_message_id": ids[5], "max_messages": 10}
            )
        )

        assert "message number 5" in result
        assert "message number 59" not in result
        assert "around" in result

    def test_read_around_a_message_of_another_conversation_is_refused(
        self, search_context: tuple[Database, User]
    ) -> None:
        database, user = search_context
        conv = _conversation_with_message(database, user, "A", "hello")
        other = database.create_conversation(user.id, "B")
        stray = database.add_message(other.id, "user", "elsewhere")

        result = str(
            read_conversation.invoke({"conversation_id": conv.id, "around_message_id": stray.id})
        )

        assert "not in this conversation" in result


# --- Nov 16 2026: one ranked list, dates, the listing ----------------------
# (docs/superpowers/specs/2026-11-16-past-chat-search-design.md)


def _at(database: Database, conv: Conversation, when: str) -> None:
    """Move every message of a conversation to an ISO UTC instant."""
    with database._pool.get_connection() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE conversation_id = ?", (when, conv.id)
        )
        conn.commit()


@pytest.fixture
def embedded(
    search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
) -> tuple[Database, User]:
    """Semantic search on, the query embedding fixed at [1, 0]."""
    import src.agent.tools.conversation_search as module

    monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
    monkeypatch.setattr(
        "src.db.models.embeddings.EmbeddingsMixin.embed_and_store_async", lambda *args: None
    )
    monkeypatch.setattr(module, "embed_text", lambda text: [1.0, 0.0])
    return search_context


def _embed_first(database: Database, user: User, conv: Conversation, vec: list[float]) -> None:
    from src.utils.embeddings import pack_vector

    message = database.get_messages(conv.id)[0]
    database.upsert_embedding(user.id, "message", message.id, "test-model", 2, pack_vector(vec))


class TestFusedSearch:
    def test_hits_from_both_passes_rank_first_and_say_how(
        self, embedded: tuple[Database, User]
    ) -> None:
        database, user = embedded
        both = _conversation_with_message(database, user, "Both chat", "kitchen tiles grout")
        words = _conversation_with_message(database, user, "Words chat", "tiles for the hallway")
        meaning = _conversation_with_message(database, user, "Meaning chat", "ceramic floor")
        _embed_first(database, user, both, [1.0, 0.0])
        _embed_first(database, user, meaning, [0.9, 0.1])
        del words

        result = str(search_conversations.invoke({"query": "tiles"}))

        assert result.index("Both chat") < result.index("Words chat")
        assert result.index("Both chat") < result.index("Meaning chat")
        assert result.count("Both chat") == 1
        assert "Both chat (conversation_id=" in result
        line = next(line for line in result.splitlines() if "Both chat" in line)
        assert line.endswith("(words + meaning)")
        assert next(ln for ln in result.splitlines() if "Words chat" in ln).endswith("(words)")
        assert next(ln for ln in result.splitlines() if "Meaning chat" in ln).endswith("(meaning)")

    def test_one_line_per_conversation(self, search_context: tuple[Database, User]) -> None:
        database, user = search_context
        conv = _conversation_with_message(database, user, "Tiles", "hexagonal tiles decision")
        database.add_message(conv.id, "assistant", "hexagonal tiles it is")
        result = str(search_conversations.invoke({"query": "hexagonal tiles"}))
        assert result.count("\n- [") == 1


class TestDateBounds:
    def test_after_and_before_filter_both_passes(self, embedded: tuple[Database, User]) -> None:
        database, user = embedded
        conv = _conversation_with_message(database, user, "Bike chat", "bike service")
        _embed_first(database, user, conv, [1.0, 0.0])
        _at(database, conv, "2026-11-10T12:00:00.000000Z")

        late = str(search_conversations.invoke({"query": "bike", "after": "2026-11-12"}))
        early = str(search_conversations.invoke({"query": "bike", "before": "2026-11-11"}))
        same_day = str(search_conversations.invoke({"query": "bike", "before": "2026-11-10"}))

        assert "Bike chat" not in late
        assert "Bike chat" in early
        assert "Bike chat" in same_day  # before is inclusive of its day

    def test_empty_query_with_dates_lists_the_range(
        self, search_context: tuple[Database, User]
    ) -> None:
        database, user = search_context
        old = _conversation_with_message(database, user, "Old chat", "old question")
        new = _conversation_with_message(database, user, "Yesterday chat", "what to cook")
        _at(database, old, "2026-11-01T12:00:00.000000Z")
        _at(database, new, "2026-11-15T12:00:00.000000Z")

        result = str(search_conversations.invoke({"after": "2026-11-15", "before": "2026-11-15"}))

        assert "Yesterday chat" in result
        assert "what to cook" in result
        assert f"conversation_id={new.id}" in result
        assert "Old chat" not in result

    @pytest.mark.parametrize(
        ("after", "before"), [("2026-11-14", "2026-11-12"), ("yesterday", None), (None, "15.11.")]
    )
    def test_bad_dates_are_a_retriable_error(
        self, search_context: tuple[Database, User], after: str | None, before: str | None
    ) -> None:
        import json

        args = (
            {"query": "x"}
            | ({"after": after} if after else {})
            | ({"before": before} if before else {})
        )
        payload = json.loads(str(search_conversations.invoke(args)))
        assert payload["error"]
        assert payload.get("retriable", True) is True


class TestSearchLog:
    def test_log_line_carries_mode_dates_and_time(
        self, search_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module

        database, user = search_context
        _conversation_with_message(database, user, "Škola", "Matematické olympiády")
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            module.logger, "info", lambda msg, extra=None, **kw: calls.append(extra or {})
        )

        search_conversations.invoke({"query": "Matematická olympiáda", "after": "2026-01-01"})

        [extra] = calls
        assert extra["mode"] == "any"
        assert extra["after"] == "2026-01-01"
        assert extra["before"] is None
        assert isinstance(extra["ms"], int)


class TestReviewFixes:
    """Final review, Nov 16 2026."""

    def test_current_chat_hits_do_not_suppress_the_fallback(
        self, search_context: tuple[Database, User]
    ) -> None:
        database, user = search_context
        current = database.create_conversation(user.id, "Current")
        for text in ("olympiáda zítra", "olympiáda výsledky", "olympiáda body"):
            database.add_message(current.id, "user", text)
        older = _conversation_with_message(database, user, "Older", "olympiády se účastní")
        from src.agent.tools.context import set_conversation_context

        set_conversation_context(current.id, user.id)
        result = str(search_conversations.invoke({"query": "olympiáda"}))
        assert f"conversation_id={older.id}" in result

    def test_dated_meaning_search_ranks_within_the_period(
        self, embedded: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        database, user = embedded
        monkeypatch.setattr(Config, "CONVERSATION_SEARCH_MAX_RESULTS", 1)
        # Older chats closer in meaning fill the all-time top candidates
        for i in range(5):
            old = _conversation_with_message(database, user, f"Old {i}", f"zzz old {i}")
            _embed_first(database, user, old, [1.0, 0.0])
            _at(database, old, "2026-10-01T12:00:00.000000Z")
        recent = _conversation_with_message(database, user, "Bike last week", "servis")
        _embed_first(database, user, recent, [0.8, 0.2])
        _at(database, recent, "2026-11-10T12:00:00.000000Z")

        result = str(
            search_conversations.invoke({"query": "qqq", "limit": 1, "after": "2026-11-09"})
        )
        assert "Bike last week" in result


class TestReviewMinors:
    """Deferred minors from the Nov 16 2026 review."""

    def test_agent_runs_do_not_crowd_the_listing(
        self, search_context: tuple[Database, User]
    ) -> None:
        database, user = search_context
        human = _conversation_with_message(database, user, "Family chat", "what to cook")
        _at(database, human, "2026-11-15T08:00:00.000000Z")
        for i in range(3):
            agent = database.create_standing_chat(user.id, f"Watcher {i}")
            database.add_message(agent.conversation_id, "assistant", f"report {i}")
        result = str(search_conversations.invoke({"limit": 2}))
        assert "Family chat" in result

    def test_agent_runs_do_not_crowd_search_hits(self, embedded: tuple[Database, User]) -> None:
        database, user = embedded
        human = _conversation_with_message(database, user, "Family chat", "zoo visit")
        _embed_first(database, user, human, [0.8, 0.6])
        for i in range(3):
            agent = database.create_standing_chat(user.id, f"Watcher {i}")
            run = database.add_message(agent.conversation_id, "assistant", f"zoo report {i}")
            from src.utils.embeddings import pack_vector

            database.upsert_embedding(user.id, "message", run.id, "m", 2, pack_vector([1.0, 0.0]))
        result = str(search_conversations.invoke({"query": "qqq", "limit": 2}))
        assert "Family chat" in result

    def test_log_counts_hits_found_both_ways(
        self, embedded: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agent.tools.conversation_search as module

        database, user = embedded
        both = _conversation_with_message(database, user, "Both", "kitchen tiles")
        _embed_first(database, user, both, [1.0, 0.0])
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            module.logger, "info", lambda msg, extra=None, **kw: calls.append(extra or {})
        )
        search_conversations.invoke({"query": "tiles"})
        assert calls[-1]["fused"] == 1
