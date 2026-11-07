"""Unit tests for the manage_memory tool.

The point of this tool is that it performs its writes and reports the real
outcome, so these tests assert on what the *model* is told, not just on the
resulting database state. A rejection the model cannot read is a bug: it can
neither retry nor tell the user.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.memory import manage_memory
from src.config import Config

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def memory_context(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[Database, User]]:
    """Point the tool's module-level db at the test database and set context."""
    import src.agent.tools.memory as memory_module

    monkeypatch.setattr(memory_module, "db", test_database)
    set_conversation_context("conv-1", test_user.id)
    yield test_database, test_user
    set_conversation_context(None, None)


def _invoke(operations: list[dict]) -> str:
    """Call the tool the way the graph does."""
    return str(manage_memory.invoke({"operations": operations}))


class TestAddOperation:
    """Adds report the new ID so the model can reference it."""

    def test_add_returns_new_id(self, memory_context: tuple[Database, User]) -> None:
        """Should persist the memory and report its ID."""
        database, user = memory_context

        result = _invoke([{"action": "add", "content": "Likes espresso", "category": "preference"}])

        memories = database.list_memories(user.id)
        assert len(memories) == 1
        assert f"added id={memories[0].id}" in result

    def test_add_records_source_conversation(self, memory_context: tuple[Database, User]) -> None:
        """Should attribute the memory to the conversation it was learned in."""
        database, user = memory_context

        _invoke([{"action": "add", "content": "Runs marathons", "category": "context"}])

        assert database.list_memories(user.id)[0].source_conversation_id == "conv-1"

    def test_add_without_content_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """Should tell the model what was missing instead of silently skipping."""
        database, user = memory_context

        result = _invoke([{"action": "add", "category": "fact"}])

        assert "REJECTED (add)" in result
        assert "content" in result
        assert database.list_memories(user.id) == []

    def test_oversized_content_is_rejected_with_the_limit(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """Should state the actual and allowed size so the model can shorten it."""
        database, user = memory_context
        oversized = "x" * (Config.MEMORY_MAX_ENTRY_CHARS + 1)

        result = _invoke([{"action": "add", "content": oversized, "category": "fact"}])

        assert "REJECTED (add)" in result
        assert str(Config.MEMORY_MAX_ENTRY_CHARS) in result
        assert database.list_memories(user.id) == []

    def test_unknown_category_is_rejected(self, memory_context: tuple[Database, User]) -> None:
        """Should list the valid categories rather than storing a bad one."""
        database, user = memory_context

        result = _invoke([{"action": "add", "content": "Something", "category": "nonsense"}])

        assert "REJECTED (add)" in result
        assert "preference" in result
        assert database.list_memories(user.id) == []

    def test_full_bank_rejection_explains_the_remedy(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A full bank must be reported so the model consolidates instead of retrying blindly."""
        database, user = memory_context
        monkeypatch.setattr(Config, "MEMORY_MAX_ENTRIES", 1)
        database.add_memory(user.id, "The only memory", "fact")

        result = _invoke([{"action": "add", "content": "One too many", "category": "fact"}])

        assert "REJECTED (add)" in result
        assert "full" in result.lower()
        assert len(database.list_memories(user.id)) == 1


class TestPatchOperation:
    """Patch edits a span, so details outside it cannot be lost by a rewrite."""

    def test_patch_replaces_a_unique_span(self, memory_context: tuple[Database, User]) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Drinks oat milk lattes every morning", "preference")

        result = _invoke(
            [
                {
                    "action": "patch",
                    "id": memory.id,
                    "old_text": "oat milk lattes",
                    "new_text": "black coffee",
                }
            ]
        )

        assert result.startswith(f"patched id={memory.id}")
        assert "Drinks black coffee every morning" in result
        assert database.list_memories(user.id)[0].content == "Drinks black coffee every morning"

    def test_empty_new_text_removes_the_span(self, memory_context: tuple[Database, User]) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea and coffee", "preference")

        _invoke([{"action": "patch", "id": memory.id, "old_text": " and coffee", "new_text": ""}])

        assert database.list_memories(user.id)[0].content == "Likes tea"

    def test_missing_span_returns_the_current_text(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """The model's copy may be stale: show it the real text so it can retry."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Has a golden retriever named Max", "fact")

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "a labrador", "new_text": "x"}]
        )

        assert "REJECTED (patch)" in result
        assert "not found" in result
        assert "Has a golden retriever named Max" in result
        assert database.list_memories(user.id)[0].content == "Has a golden retriever named Max"

    def test_ambiguous_span_asks_for_more_context(
        self, memory_context: tuple[Database, User]
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Son plays tennis; daughter plays tennis", "fact")

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "tennis", "new_text": "golf"}]
        )

        assert "REJECTED (patch)" in result
        assert "2 times" in result
        assert (
            database.list_memories(user.id)[0].content == "Son plays tennis; daughter plays tennis"
        )

    def test_category_only_change(self, memory_context: tuple[Database, User]) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Training for a marathon", "context")

        result = _invoke([{"action": "patch", "id": memory.id, "category": "goal"}])

        assert result.startswith(f"patched id={memory.id}")
        stored = database.list_memories(user.id)[0]
        assert (stored.content, stored.category) == ("Training for a marathon", "goal")

    @pytest.mark.parametrize(
        ("op", "field"),
        [
            ({"old_text": "a", "new_text": "b"}, "id"),
            ({"id": "ID"}, "old_text"),
            ({"id": "ID", "old_text": "tea"}, "new_text"),
        ],
    )
    def test_missing_field_is_named(
        self, memory_context: tuple[Database, User], op: dict, field: str
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")
        op = {k: (memory.id if v == "ID" else v) for k, v in op.items()}

        result = _invoke([{"action": "patch", **op}])

        assert "REJECTED (patch)" in result
        assert field in result
        assert database.list_memories(user.id)[0].content == "Likes tea"

    def test_new_text_without_old_text_is_rejected(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """Not a silent category-only change: the model meant to edit the text."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke(
            [{"action": "patch", "id": memory.id, "new_text": "Likes coffee", "category": "fact"}]
        )

        assert "REJECTED (patch)" in result
        assert "old_text" in result
        stored = database.list_memories(user.id)[0]
        assert (stored.content, stored.category) == ("Likes tea", "preference")

    def test_unknown_category_is_rejected(self, memory_context: tuple[Database, User]) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke([{"action": "patch", "id": memory.id, "category": "nonsense"}])

        assert "REJECTED (patch)" in result
        assert "preference" in result

    def test_patch_that_empties_the_memory_points_to_delete(
        self, memory_context: tuple[Database, User]
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "Likes tea", "new_text": ""}]
        )

        assert "REJECTED (patch)" in result
        assert "'delete'" in result
        assert database.list_memories(user.id)[0].content == "Likes tea"

    def test_oversized_result_steers_to_a_separate_memory(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """Prod logs (Oct 2026): 74 of 272 updates were over the limit, mostly
        catch-all memories absorbing unrelated facts - steer to 'add' instead."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")
        oversized = "x" * Config.MEMORY_MAX_ENTRY_CHARS

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "tea", "new_text": oversized}]
        )

        assert "REJECTED (patch)" in result
        assert "one topic" in result
        assert "'add'" in result
        assert database.list_memories(user.id)[0].content == "Likes tea"

    def test_result_near_the_limit_suggests_add(
        self, memory_context: tuple[Database, User]
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")
        near = "x" * int(Config.MEMORY_MAX_ENTRY_CHARS * Config.MEMORY_ENTRY_NEAR_LIMIT_RATIO)

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "Likes tea", "new_text": near}]
        )

        assert f"{len(near)}/{Config.MEMORY_MAX_ENTRY_CHARS} chars" in result
        assert "'add'" in result

    def test_small_patch_has_no_nudge(self, memory_context: tuple[Database, User]) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke(
            [{"action": "patch", "id": memory.id, "old_text": "tea", "new_text": "green tea"}]
        )

        assert "'add'" not in result

    def test_unknown_id_is_reported(self, memory_context: tuple[Database, User]) -> None:
        result = _invoke(
            [{"action": "patch", "id": "no-such-id", "old_text": "a", "new_text": "b"}]
        )

        assert "REJECTED (patch)" in result
        assert "no-such-id" in result

    def test_another_users_memory_is_rejected(self, memory_context: tuple[Database, User]) -> None:
        database, _user = memory_context
        other = database.get_or_create_user(email="other@example.com", name="Other")
        theirs = database.add_memory(other.id, "Their secret", "fact")

        result = _invoke(
            [{"action": "patch", "id": theirs.id, "old_text": "secret", "new_text": "x"}]
        )

        assert "REJECTED (patch)" in result
        assert database.list_memories(other.id)[0].content == "Their secret"

    def test_protected_memory_can_be_patched(self, memory_context: tuple[Database, User]) -> None:
        """Protection blocks deletes only: a changed fact must still be correctable."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Lives in Brno", "fact", protected=True)

        _invoke([{"action": "patch", "id": memory.id, "old_text": "Brno", "new_text": "Prague"}])

        assert database.list_memories(user.id)[0].content == "Lives in Prague"

    def test_two_patches_to_one_memory_apply_in_order(
        self, memory_context: tuple[Database, User]
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea and jazz", "preference")

        result = _invoke(
            [
                {"action": "patch", "id": memory.id, "old_text": "tea", "new_text": "coffee"},
                {"action": "patch", "id": memory.id, "old_text": "jazz", "new_text": "blues"},
            ]
        )

        assert "REJECTED" not in result
        assert database.list_memories(user.id)[0].content == "Likes coffee and blues"

    def test_update_action_points_to_patch(self, memory_context: tuple[Database, User]) -> None:
        """Old conversations still show 'update' calls the model may imitate."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke([{"action": "update", "id": memory.id, "content": "Likes coffee"}])

        assert "REJECTED (update)" in result
        assert "'patch'" in result
        assert database.list_memories(user.id)[0].content == "Likes tea"


class TestWriteLogging:
    """The logs must show whether updates shrink memories (losing details) and
    why writes are refused - the TODO's lossy-write check needs both."""

    def test_patch_logs_old_and_new_length(
        self, memory_context: tuple[Database, User], caplog: pytest.LogCaptureFixture
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea and coffee", "preference")

        with caplog.at_level(logging.INFO):
            _invoke(
                [{"action": "patch", "id": memory.id, "old_text": " and coffee", "new_text": ""}]
            )

        record = next(r for r in caplog.records if r.getMessage() == "Memory updated via tool")
        assert (record.old_chars, record.new_chars) == (20, 9)

    def test_rejection_is_logged_with_its_reason(
        self, memory_context: tuple[Database, User], caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            _invoke([{"action": "patch", "id": "no-such-id", "old_text": "a", "new_text": "b"}])

        record = next(r for r in caplog.records if r.getMessage() == "Memory write rejected")
        assert record.action == "patch"
        assert record.reason.startswith("no memory with id=no-such-id")


class TestDeleteOperation:
    """Deletes are soft, and protection is enforced rather than requested."""

    def test_delete_soft_deletes_and_says_so(self, memory_context: tuple[Database, User]) -> None:
        """Should confirm the delete and mention it is recoverable."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Temporary note", "context")

        result = _invoke([{"action": "delete", "id": memory.id}])

        assert f"deleted id={memory.id}" in result
        assert database.list_memories(user.id) == []
        assert len(database.list_deleted_memories(user.id)) == 1

    def test_protected_memory_refusal_is_explained(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """The model must learn it cannot delete this, and what to do instead."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Allergic to shellfish", "fact", protected=True)

        result = _invoke([{"action": "delete", "id": memory.id}])

        assert "REJECTED (delete)" in result
        assert "protected" in result.lower()
        assert len(database.list_memories(user.id)) == 1

    def test_unknown_id_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """Should report a delete of something that is not there."""
        result = _invoke([{"action": "delete", "id": "ghost"}])

        assert "REJECTED (delete)" in result
        assert "ghost" in result


class TestBatchBehaviour:
    """Batch semantics: partial success, ordering, and the write budget."""

    def test_one_rejection_applies_nothing(self, memory_context: tuple[Database, User]) -> None:
        """A merge is add + delete: applying half of it loses or duplicates a fact."""
        database, user = memory_context
        old = database.add_memory(user.id, "Has a dog", "fact")

        result = _invoke(
            [
                {"action": "add", "content": "Has a dog named Max", "category": "fact"},
                {"action": "patch", "id": "missing", "old_text": "a", "new_text": "b"},
                {"action": "delete", "id": old.id},
            ]
        )

        lines = result.splitlines()
        assert len(lines) == 4
        assert lines[0].startswith("Nothing was applied")
        assert lines[1].startswith("not applied (add)")
        assert lines[2].startswith("REJECTED (patch)")
        assert lines[3].startswith("not applied (delete)")
        assert [m.content for m in database.list_memories(user.id)] == ["Has a dog"]

    def test_limits_are_checked_on_the_final_state(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On a full bank, delete-one-add-one is fine whatever the order."""
        database, user = memory_context
        monkeypatch.setattr(Config, "MEMORY_MAX_ENTRIES", 1)
        old = database.add_memory(user.id, "Has a dog", "fact")

        result = _invoke(
            [
                {"action": "add", "content": "Has a dog named Max", "category": "fact"},
                {"action": "delete", "id": old.id},
            ]
        )

        assert "REJECTED" not in result
        assert [m.content for m in database.list_memories(user.id)] == ["Has a dog named Max"]

    def test_overflowing_adds_are_rejected_together(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        database, user = memory_context
        monkeypatch.setattr(Config, "MEMORY_MAX_ENTRIES", 1)

        result = _invoke(
            [
                {"action": "add", "content": "One", "category": "fact"},
                {"action": "add", "content": "Two", "category": "fact"},
            ]
        )

        assert "full" in result.lower()
        assert database.list_memories(user.id) == []

    def test_patch_after_delete_in_one_batch_is_rejected(
        self, memory_context: tuple[Database, User]
    ) -> None:
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke(
            [
                {"action": "delete", "id": memory.id},
                {"action": "patch", "id": memory.id, "old_text": "tea", "new_text": "coffee"},
            ]
        )

        assert "REJECTED (patch)" in result
        assert database.list_memories(user.id)[0].content == "Likes tea"

    def test_memory_changed_meanwhile_is_reported(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parallel edit between planning and writing rolls the batch back."""
        import src.agent.tools.memory as memory_module

        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")
        real_apply = database.apply_memory_batch

        def edit_first(*args: object, **kwargs: object) -> object:
            with database._pool.get_connection() as conn:
                conn.execute(
                    "UPDATE user_memories SET content = 'Likes juice' WHERE id = ?", (memory.id,)
                )
                conn.commit()
            return real_apply(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(memory_module.db, "apply_memory_batch", edit_first)

        result = _invoke(
            [
                {"action": "add", "content": "Has a cat", "category": "fact"},
                {"action": "patch", "id": memory.id, "old_text": "tea", "new_text": "coffee"},
            ]
        )

        assert "Nothing was applied" in result
        assert memory.id in result
        assert [m.content for m in database.list_memories(user.id)] == ["Likes juice"]

    def test_unknown_action_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """Should name the valid actions."""
        result = _invoke([{"action": "frobnicate", "content": "?"}])

        assert "REJECTED" in result
        assert "add" in result and "patch" in result and "delete" in result

    def test_oversized_batch_is_rejected_whole(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mass rewrite is refused, and the refusal is visible.

        The operation list can be shaped by fetched web content, so one turn
        must not be able to rewrite the whole bank. Cutting the batch instead
        would apply half a merge and skip validating the rest.
        """
        database, user = memory_context
        monkeypatch.setattr(Config, "MEMORY_MAX_OPS_PER_CALL", 2)

        result = _invoke(
            [
                {"action": "add", "content": "One", "category": "fact"},
                {"action": "add", "content": "Two", "category": "fact"},
                {"action": "delete", "id": "nope"},
            ]
        )

        assert "REJECTED" in result
        assert "3 operations" in result and "2" in result
        assert "Nothing was applied" in result
        assert database.list_memories(user.id) == []

    def test_failure_after_the_commit_does_not_claim_nothing_was_applied(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The writes landed: saying otherwise makes the model resubmit duplicates."""
        import src.agent.tools.memory as memory_module

        database, user = memory_context
        gone = database.add_memory(user.id, "Old note", "context")

        def locked(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("database is locked")

        monkeypatch.setattr(memory_module.db, "delete_embedding", locked)

        result = _invoke(
            [
                {"action": "add", "content": "New note", "category": "context"},
                {"action": "delete", "id": gone.id},
            ]
        )

        assert "Nothing was applied" not in result
        assert "REJECTED" not in result
        assert f"deleted id={gone.id}" in result
        assert [m.content for m in database.list_memories(user.id)] == ["New note"]

    def test_empty_operations_list(self, memory_context: tuple[Database, User]) -> None:
        """Should not error on an empty batch."""
        assert "No operations" in _invoke([])

    def test_storage_error_is_surfaced_to_the_model(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A DB failure must reach the model, not just the log."""
        import src.agent.tools.memory as memory_module

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(memory_module.db, "get_memory_count", boom)

        result = _invoke([{"action": "add", "content": "Never stored", "category": "fact"}])

        assert "REJECTED" in result
        assert "disk on fire" in result


class TestMissingContext:
    """Without a user there is nothing to write to."""

    def test_no_user_context_reports_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should refuse rather than write to a guessed user."""
        set_conversation_context(None, None)

        result = _invoke([{"action": "add", "content": "Orphan", "category": "fact"}])

        assert "no user context" in result.lower()


class TestSearchMemory:
    """search_memory finds entries not shown in the tiered injection."""

    def test_substring_match_returns_entries(self, memory_context) -> None:
        from src.agent.tools.memory import search_memory

        test_database, test_user = memory_context
        kept = test_database.add_memory(test_user.id, "Allergic to shellfish", "fact")
        test_database.add_memory(test_user.id, "Prefers dark mode", "preference")

        result = str(search_memory.invoke({"query": "shellfish"}))

        assert kept.id in result
        assert "Allergic to shellfish" in result
        assert "dark mode" not in result

    def test_no_match_returns_guidance(self, memory_context) -> None:
        from src.agent.tools.memory import search_memory

        result = str(search_memory.invoke({"query": "nonexistent-topic-xyz"}))

        assert "No stored memories matched" in result

    def test_semantic_match_via_embeddings(self, memory_context, monkeypatch) -> None:
        import src.agent.tools.memory as memory_module
        from src.agent.tools.memory import search_memory
        from src.utils.embeddings import pack_vector

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        test_database, test_user = memory_context
        memory = test_database.add_memory(test_user.id, "Has a golden retriever named Max", "fact")
        test_database.upsert_embedding(
            test_user.id, "memory", memory.id, "test-model", 2, pack_vector([1.0, 0.0])
        )
        monkeypatch.setattr(memory_module, "embed_text", lambda text: [1.0, 0.1])

        result = str(search_memory.invoke({"query": "what pet do I own"}))

        assert "golden retriever" in result

    def test_empty_query_rejected(self, memory_context) -> None:
        from src.agent.tools.memory import search_memory

        result = str(search_memory.invoke({"query": "  "}))

        assert json.loads(result) == {"error": "'query' is required."}


class TestMemoryEmbeddingHook:
    """Memory writes schedule background embeddings; deletes clean them up."""

    def test_add_schedules_embedding(self, memory_context, monkeypatch) -> None:
        calls: list[tuple] = []
        test_database, test_user = memory_context
        monkeypatch.setattr(
            test_database, "embed_and_store_async", lambda *args: calls.append(args)
        )

        result = _invoke([{"action": "add", "content": "Loves hiking", "category": "fact"}])

        memory_id = result.split("id=")[1].split(" ")[0]
        assert calls == [(test_user.id, "memory", memory_id, "Loves hiking")]

    def test_patch_schedules_embedding(self, memory_context, monkeypatch) -> None:
        calls: list[tuple] = []
        test_database, test_user = memory_context
        monkeypatch.setattr(
            test_database, "embed_and_store_async", lambda *args: calls.append(args)
        )
        memory = test_database.add_memory(test_user.id, "Old fact", "fact")

        _invoke([{"action": "patch", "id": memory.id, "old_text": "Old", "new_text": "New"}])

        assert (test_user.id, "memory", memory.id, "New fact") in calls

    def test_delete_removes_embedding(self, memory_context) -> None:
        from src.utils.embeddings import pack_vector

        test_database, test_user = memory_context
        memory = test_database.add_memory(test_user.id, "Ephemeral", "context")
        test_database.upsert_embedding(
            test_user.id, "memory", memory.id, "test-model", 2, pack_vector([1.0, 0.0])
        )

        _invoke([{"action": "delete", "id": memory.id}])

        assert test_database.get_embeddings(test_user.id, "memory") == []
