"""Unit tests for memory defragmentation script."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.defragment_memories import (
    DefragPlan,
    format_memories_for_llm,
    plan_grows_bank,
    validate_changes,
)
from src.config import Config
from src.db.models import Memory


def _memory(
    memory_id: str,
    content: str = "Some content",
    category: str | None = "fact",
    protected: bool = False,
) -> Memory:
    """Build a Memory for validation tests."""
    return Memory(
        id=memory_id,
        user_id="user-123",
        content=content,
        category=category,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
        protected=protected,
    )


def _existing(*memories: Memory) -> dict[str, Memory]:
    """Index memories by ID, the shape validate_changes expects."""
    return {m.id: m for m in memories}


class TestFormatMemoriesForLlm:
    """Test formatting memories for LLM input."""

    def test_formats_single_memory(self):
        """Test formatting a single memory."""
        memories = [_memory("mem-1", "User likes coffee", "preference")]

        result = format_memories_for_llm(memories)

        assert "User likes coffee" in result
        assert "[preference]" in result
        assert "ID: mem-1" in result

    def test_formats_multiple_memories(self):
        """Test formatting several memories."""
        memories = [_memory("mem-1", "First"), _memory("mem-2", "Second")]

        result = format_memories_for_llm(memories)

        assert "1. " in result
        assert "2. " in result
        assert "First" in result
        assert "Second" in result

    def test_handles_memory_without_category(self):
        """Test formatting a memory with no category."""
        result = format_memories_for_llm([_memory("mem-1", "No category", None)])

        assert "No category" in result
        assert "[None]" not in result

    def test_marks_protected_memories(self):
        """The LLM must be told which memories it cannot delete.

        Otherwise it wastes its plan on deletes that the DB layer refuses.
        """
        memories = [
            _memory("mem-1", "Wife's name is Sarah", protected=True),
            _memory("mem-2", "Asked about weather"),
        ]

        result = format_memories_for_llm(memories)

        protected_line = [line for line in result.splitlines() if "mem-1" in line][0]
        ordinary_line = [line for line in result.splitlines() if "mem-2" in line][0]
        assert "PROTECTED" in protected_line
        assert "PROTECTED" not in ordinary_line

    def test_empty_list(self):
        """Test formatting an empty list."""
        assert format_memories_for_llm([]) == ""


class TestValidateChanges:
    """Test validation of LLM-proposed changes."""

    def test_validates_deletions(self):
        """Test that valid deletions are accepted."""
        changes = {"delete": ["mem-1", "mem-2"]}
        existing = _existing(_memory("mem-1"), _memory("mem-2"), _memory("mem-3"))

        to_delete, to_update, to_add = validate_changes(changes, existing)

        assert to_delete == ["mem-1", "mem-2"]
        assert to_update == []
        assert to_add == []

    def test_rejects_nonexistent_deletions(self):
        """Test that deletions of non-existent IDs are rejected."""
        changes = {"delete": ["mem-1", "mem-999"]}
        existing = _existing(_memory("mem-1"), _memory("mem-2"))

        to_delete, _to_update, _to_add = validate_changes(changes, existing)

        assert to_delete == ["mem-1"]

    def test_rejects_deletion_of_protected_memory(self):
        """Protected memories must survive defragmentation."""
        changes = {"delete": ["mem-1", "mem-2"]}
        existing = _existing(_memory("mem-1", protected=True), _memory("mem-2"))

        to_delete, _to_update, _to_add = validate_changes(changes, existing)

        assert to_delete == ["mem-2"]

    def test_validates_updates(self):
        """Test that valid updates are accepted."""
        changes = {"update": [{"id": "mem-1", "content": "New content", "category": "fact"}]}
        existing = _existing(_memory("mem-1"), _memory("mem-2"))

        _to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert to_update == [{"id": "mem-1", "content": "New content", "category": "fact"}]

    def test_protected_memories_can_still_be_updated(self):
        """Protection blocks deletion, not correction."""
        changes = {
            "update": [{"id": "mem-1", "content": "Wife's name is Sara", "category": "fact"}]
        }
        existing = _existing(_memory("mem-1", protected=True))

        _to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert len(to_update) == 1

    def test_rejects_update_without_content(self):
        """Test that updates without content are rejected."""
        changes = {"update": [{"id": "mem-1", "content": ""}]}
        existing = _existing(_memory("mem-1"))

        _to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert to_update == []

    def test_rejects_update_of_nonexistent_memory(self):
        """Test that updates to non-existent IDs are rejected."""
        changes = {"update": [{"id": "mem-999", "content": "Content"}]}
        existing = _existing(_memory("mem-1"))

        _to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert to_update == []

    def test_rejects_update_of_deleted_memory(self):
        """Test that updating a memory being deleted is rejected."""
        changes = {
            "delete": ["mem-1"],
            "update": [{"id": "mem-1", "content": "Updated"}],
        }
        existing = _existing(_memory("mem-1"))

        to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert to_delete == ["mem-1"]
        assert to_update == []

    def test_validates_additions(self):
        """Test that valid additions are accepted."""
        changes = {"add": [{"content": "New memory", "category": "preference"}]}
        existing = _existing(_memory("mem-1"))

        _to_delete, _to_update, to_add = validate_changes(changes, existing)

        assert to_add == [{"content": "New memory", "category": "preference"}]

    def test_rejects_addition_without_content(self):
        """Test that additions without content are rejected."""
        changes = {"add": [{"content": "", "category": "fact"}]}

        _to_delete, _to_update, to_add = validate_changes(changes, {})

        assert to_add == []

    def test_rejects_oversized_addition(self):
        """The nightly job is not a privileged path around the size bound.

        Memories are injected into every request, so an oversized entry written
        by defrag costs the same as one written by the tool.
        """
        changes = {"add": [{"content": "x" * (Config.MEMORY_MAX_ENTRY_CHARS + 1)}]}

        _to_delete, _to_update, to_add = validate_changes(changes, {})

        assert to_add == []

    def test_rejects_oversized_update(self):
        """Same bound applies to rewrites."""
        changes = {
            "update": [{"id": "mem-1", "content": "x" * (Config.MEMORY_MAX_ENTRY_CHARS + 1)}]
        }
        existing = _existing(_memory("mem-1"))

        _to_delete, to_update, _to_add = validate_changes(changes, existing)

        assert to_update == []

    def test_drops_invented_categories(self):
        """An unknown category is dropped rather than stored."""
        changes = {"add": [{"content": "Valid content", "category": "vibes"}]}

        _to_delete, _to_update, to_add = validate_changes(changes, {})

        assert to_add == [{"content": "Valid content", "category": None}]

    def test_handles_no_changes(self):
        """Test that no_changes flag is handled."""
        changes = {"reasoning": "All good", "no_changes": True, "delete": ["mem-1"]}
        existing = _existing(_memory("mem-1"))

        to_delete, to_update, to_add = validate_changes(changes, existing)

        assert to_delete == []
        assert to_update == []
        assert to_add == []

    def test_handles_empty_changes(self):
        """Test handling of an empty plan."""
        to_delete, to_update, to_add = validate_changes({}, _existing(_memory("mem-1")))

        assert to_delete == []
        assert to_update == []
        assert to_add == []

    def test_accepts_a_plan_object(self):
        """Should accept the structured plan directly, not only a dict."""
        plan = DefragPlan(delete=["mem-1"])
        existing = _existing(_memory("mem-1"))

        to_delete, _to_update, _to_add = validate_changes(plan, existing)

        assert to_delete == ["mem-1"]


class TestPlanGrowsBank:
    """The net-reduction guard."""

    def test_more_adds_than_deletes_is_rejected(self):
        """Consolidation that forgets to delete the originals grows the bank."""
        assert plan_grows_bank([], [{"content": "merged"}]) is True

    def test_balanced_plan_is_allowed(self):
        """Replacing two memories with one is the normal case."""
        assert plan_grows_bank(["mem-1", "mem-2"], [{"content": "merged"}]) is False

    def test_pure_deletion_is_allowed(self):
        """Deleting stale memories with no additions is fine."""
        assert plan_grows_bank(["mem-1"], []) is False

    def test_update_only_plan_is_allowed(self):
        """Rewrites do not change the count at all."""
        assert plan_grows_bank([], []) is False


class TestDefragmentUserMemories:
    """Test the main defragmentation function."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM whose structured call returns a plan."""
        llm = MagicMock()
        llm.with_structured_output.return_value.invoke.return_value = DefragPlan(
            reasoning="Test", no_changes=True
        )
        return llm

    @pytest.fixture
    def mock_user(self):
        """Create a mock user."""
        from src.db.models import User

        return User(
            id="user-123",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            custom_instructions=None,
        )

    @pytest.fixture
    def sample_memories(self):
        """Create sample memories for testing."""
        return [
            _memory("mem-1", "User likes coffee", "preference"),
            _memory("mem-2", "User prefers dark roast coffee", "preference"),
        ]

    @staticmethod
    def _set_plan(mock_llm, plan: DefragPlan) -> None:
        """Point the mock's structured-output call at a specific plan."""
        mock_llm.with_structured_output.return_value.invoke.return_value = plan

    def test_returns_skipped_for_empty_memories(self, mock_llm, mock_user):
        """Test that empty memory list is skipped."""
        from scripts.defragment_memories import defragment_user_memories

        result = defragment_user_memories(mock_user, [], mock_llm)

        assert result["skipped"] is True
        mock_llm.with_structured_output.assert_not_called()

    def test_requests_a_schema_validated_plan(self, mock_llm, mock_user, sample_memories):
        """The plan is requested as a schema, not parsed out of prose.

        Regression: the old text parser skipped the whole user whenever the
        model's JSON formatting surprised it, silently and nightly.
        """
        from scripts.defragment_memories import defragment_user_memories

        defragment_user_memories(mock_user, sample_memories, mock_llm)

        mock_llm.with_structured_output.assert_called_once_with(DefragPlan)
        call_args = mock_llm.with_structured_output.return_value.invoke.call_args[0][0]
        assert len(call_args) == 2
        assert call_args[0]["role"] == "system"
        assert call_args[1]["role"] == "user"
        assert "User likes coffee" in call_args[1]["content"]

    @patch("scripts.defragment_memories.db")
    def test_dry_run_does_not_modify_database(self, mock_db, mock_llm, mock_user, sample_memories):
        """Test that dry run doesn't modify the database."""
        from scripts.defragment_memories import defragment_user_memories

        self._set_plan(mock_llm, DefragPlan(reasoning="Merge", delete=["mem-2"]))

        result = defragment_user_memories(mock_user, sample_memories, mock_llm, dry_run=True)

        mock_db.bulk_update_memories.assert_not_called()
        assert result["deleted"] == 1

    @patch("scripts.defragment_memories.db")
    def test_applies_changes_to_database(self, mock_db, mock_llm, mock_user, sample_memories):
        """Test that changes are applied when not a dry run."""
        from scripts.defragment_memories import defragment_user_memories

        mock_db.bulk_update_memories.return_value = {"deleted": 1, "updated": 1, "added": 0}
        self._set_plan(
            mock_llm,
            DefragPlan(
                reasoning="Merge",
                delete=["mem-2"],
                update=[{"id": "mem-1", "content": "Likes dark roast coffee"}],
            ),
        )

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        mock_db.bulk_update_memories.assert_called_once()
        assert result["deleted"] == 1
        assert result["updated"] == 1

    @patch("scripts.defragment_memories.db")
    def test_refuses_a_plan_that_would_grow_the_bank(
        self, mock_db, mock_llm, mock_user, sample_memories
    ):
        """A plan that adds without deleting must not be applied.

        This is the most likely way for the job to misbehave: the model writes
        the consolidated memory and forgets to remove the originals, so the
        bank grows every night.
        """
        from scripts.defragment_memories import defragment_user_memories

        self._set_plan(
            mock_llm,
            DefragPlan(
                reasoning="Consolidating",
                add=[{"content": "Likes dark roast coffee"}, {"content": "Something else"}],
            ),
        )

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        mock_db.bulk_update_memories.assert_not_called()
        assert result["skipped"] is True

    def test_handles_llm_error(self, mock_llm, mock_user, sample_memories):
        """Test that LLM errors are handled gracefully."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.with_structured_output.return_value.invoke.side_effect = Exception("API error")

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True

    def test_handles_missing_plan(self, mock_llm, mock_user, sample_memories):
        """Test that a None plan is handled gracefully."""
        from scripts.defragment_memories import defragment_user_memories

        self._set_plan(mock_llm, None)

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True

    def test_handles_no_changes_response(self, mock_llm, mock_user, sample_memories):
        """Test handling of a no-op plan."""
        from scripts.defragment_memories import defragment_user_memories

        self._set_plan(mock_llm, DefragPlan(reasoning="Already tidy", no_changes=True))

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True

    @patch("scripts.defragment_memories.db")
    def test_handles_plan_returned_as_dict(self, mock_db, mock_llm, mock_user, sample_memories):
        """Some model/provider combinations return a plain dict."""
        from scripts.defragment_memories import defragment_user_memories

        mock_db.bulk_update_memories.return_value = {"deleted": 1, "updated": 0, "added": 0}
        self._set_plan(mock_llm, {"reasoning": "Merge", "delete": ["mem-2"]})

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["deleted"] == 1
