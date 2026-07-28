"""Unit tests for the manage_memory tool.

The point of this tool is that it performs its writes and reports the real
outcome, so these tests assert on what the *model* is told, not just on the
resulting database state. A rejection the model cannot read is a bug: it can
neither retry nor tell the user.
"""

from __future__ import annotations

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


class TestUpdateOperation:
    """Updates distinguish a successful edit from a stale ID."""

    def test_update_changes_content(self, memory_context: tuple[Database, User]) -> None:
        """Should apply the new content and confirm the ID."""
        database, user = memory_context
        memory = database.add_memory(user.id, "Likes tea", "preference")

        result = _invoke([{"action": "update", "id": memory.id, "content": "Likes green tea"}])

        assert f"updated id={memory.id}" in result
        assert database.list_memories(user.id)[0].content == "Likes green tea"

    def test_unknown_id_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """A stale ID must surface, not vanish into the logs."""
        _invoke([{"action": "add", "content": "Anything", "category": "fact"}])

        result = _invoke([{"action": "update", "id": "no-such-id", "content": "New"}])

        assert "REJECTED (update)" in result
        assert "no-such-id" in result

    def test_update_of_another_users_memory_is_rejected(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """Ownership is enforced below the tool; the model still gets told."""
        database, _user = memory_context
        other = database.get_or_create_user(email="other@example.com", name="Other")
        theirs = database.add_memory(other.id, "Their secret", "fact")

        result = _invoke([{"action": "update", "id": theirs.id, "content": "Hijacked"}])

        assert "REJECTED (update)" in result
        assert database.list_memories(other.id)[0].content == "Their secret"

    def test_missing_id_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """Should name the missing field."""
        result = _invoke([{"action": "update", "content": "No id given"}])

        assert "REJECTED (update)" in result
        assert "id" in result


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

    def test_partial_failure_reports_each_operation(
        self, memory_context: tuple[Database, User]
    ) -> None:
        """One bad operation must not hide the good ones, or vice versa."""
        database, user = memory_context

        result = _invoke(
            [
                {"action": "add", "content": "Good one", "category": "fact"},
                {"action": "update", "id": "missing", "content": "Bad one"},
                {"action": "add", "content": "Another good one", "category": "goal"},
            ]
        )

        lines = result.splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("added id=")
        assert lines[1].startswith("REJECTED (update)")
        assert lines[2].startswith("added id=")
        assert len(database.list_memories(user.id)) == 2

    def test_unknown_action_is_reported(self, memory_context: tuple[Database, User]) -> None:
        """Should name the valid actions."""
        result = _invoke([{"action": "frobnicate", "content": "?"}])

        assert "REJECTED" in result
        assert "add" in result and "update" in result and "delete" in result

    def test_per_call_budget_caps_applied_operations(
        self, memory_context: tuple[Database, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mass rewrite is refused, and the refusal is visible.

        The operation list can be shaped by fetched web content, so one turn
        must not be able to rewrite the whole bank.
        """
        database, user = memory_context
        monkeypatch.setattr(Config, "MEMORY_MAX_OPS_PER_CALL", 2)

        result = _invoke(
            [{"action": "add", "content": f"Memory {i}", "category": "fact"} for i in range(5)]
        )

        assert "only the first 2" in result
        assert len(database.list_memories(user.id)) == 2

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
