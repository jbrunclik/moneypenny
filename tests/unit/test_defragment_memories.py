"""Unit tests for memory defragmentation script."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.defragment_memories import (
    format_memories_for_llm,
    parse_llm_response,
    validate_changes,
)
from src.db.models import Memory


class TestFormatMemoriesForLlm:
    """Test formatting memories for LLM input."""

    def test_formats_single_memory(self):
        """Test formatting a single memory."""
        memory = Memory(
            id="mem-123",
            user_id="user-1",
            content="User likes coffee",
            category="preference",
            created_at=datetime(2024, 1, 15),
            updated_at=datetime(2024, 1, 15),
        )

        result = format_memories_for_llm([memory])

        assert "1. [preference] User likes coffee" in result
        assert "ID: mem-123" in result
        assert "Created: 2024-01-15" in result

    def test_formats_multiple_memories(self):
        """Test formatting multiple memories."""
        memories = [
            Memory(
                id="mem-1",
                user_id="user-1",
                content="User likes coffee",
                category="preference",
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2024, 1, 1),
            ),
            Memory(
                id="mem-2",
                user_id="user-1",
                content="User works as developer",
                category="fact",
                created_at=datetime(2024, 1, 2),
                updated_at=datetime(2024, 1, 2),
            ),
        ]

        result = format_memories_for_llm(memories)

        assert "1. [preference] User likes coffee" in result
        assert "2. [fact] User works as developer" in result

    def test_handles_memory_without_category(self):
        """Test formatting memory with no category."""
        memory = Memory(
            id="mem-123",
            user_id="user-1",
            content="Some memory",
            category=None,
            created_at=datetime(2024, 1, 15),
            updated_at=datetime(2024, 1, 15),
        )

        result = format_memories_for_llm([memory])

        # Should not have category brackets
        assert "1. Some memory" in result
        assert "[" not in result.split("\n")[0]

    def test_empty_list(self):
        """Test formatting empty list of memories."""
        result = format_memories_for_llm([])
        assert result == ""


class TestParseLlmResponse:
    """Test parsing LLM response JSON."""

    def test_parses_plain_json(self):
        """Test parsing plain JSON response."""
        response = '{"reasoning": "Test", "delete": ["mem-1"]}'
        result = parse_llm_response(response)

        assert result is not None
        assert result["reasoning"] == "Test"
        assert result["delete"] == ["mem-1"]

    def test_parses_json_with_code_block(self):
        """Test parsing JSON wrapped in code block."""
        response = """Here are my suggestions:
```json
{"reasoning": "Consolidating", "delete": ["mem-1"]}
```
"""
        result = parse_llm_response(response)

        assert result is not None
        assert result["reasoning"] == "Consolidating"

    def test_parses_json_with_generic_code_block(self):
        """Test parsing JSON wrapped in generic code block."""
        response = """
```
{"reasoning": "Test", "no_changes": true}
```
"""
        result = parse_llm_response(response)

        assert result is not None
        assert result["no_changes"] is True

    def test_returns_none_for_invalid_json(self):
        """Test that invalid JSON returns None."""
        response = "This is not JSON at all"
        result = parse_llm_response(response)
        assert result is None

    def test_returns_none_for_malformed_json(self):
        """Test that malformed JSON returns None."""
        response = '{"reasoning": "missing quote}'
        result = parse_llm_response(response)
        assert result is None

    def test_handles_whitespace(self):
        """Test parsing JSON with extra whitespace."""
        response = """

        {"reasoning": "Test"}

        """
        result = parse_llm_response(response)
        assert result is not None
        assert result["reasoning"] == "Test"


class TestValidateChanges:
    """Test validation of LLM-proposed changes."""

    def test_validates_deletions(self):
        """Test that valid deletions are accepted."""
        changes = {"delete": ["mem-1", "mem-2"]}
        existing_ids = {"mem-1", "mem-2", "mem-3"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == ["mem-1", "mem-2"]
        assert to_update == []
        assert to_add == []

    def test_rejects_nonexistent_deletions(self):
        """Test that deletions of non-existent IDs are rejected."""
        changes = {"delete": ["mem-1", "mem-999"]}
        existing_ids = {"mem-1", "mem-2"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == ["mem-1"]  # Only valid ID

    def test_validates_updates(self):
        """Test that valid updates are accepted."""
        changes = {"update": [{"id": "mem-1", "content": "New content", "category": "fact"}]}
        existing_ids = {"mem-1", "mem-2"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_update == [{"id": "mem-1", "content": "New content", "category": "fact"}]

    def test_rejects_update_without_content(self):
        """Test that updates without content are rejected."""
        changes = {"update": [{"id": "mem-1"}]}  # Missing content
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_update == []

    def test_rejects_update_of_nonexistent_memory(self):
        """Test that updates to non-existent IDs are rejected."""
        changes = {"update": [{"id": "mem-999", "content": "Content"}]}
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_update == []

    def test_rejects_update_of_deleted_memory(self):
        """Test that updating a memory being deleted is rejected."""
        changes = {
            "delete": ["mem-1"],
            "update": [{"id": "mem-1", "content": "Updated"}],
        }
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == ["mem-1"]
        assert to_update == []  # Can't update what's being deleted

    def test_validates_additions(self):
        """Test that valid additions are accepted."""
        changes = {"add": [{"content": "New memory", "category": "preference"}]}
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_add == [{"content": "New memory", "category": "preference"}]

    def test_rejects_addition_without_content(self):
        """Test that additions without content are rejected."""
        changes = {"add": [{"category": "fact"}]}  # Missing content
        existing_ids = set()

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_add == []

    def test_handles_no_changes(self):
        """Test that no_changes flag is handled."""
        changes = {"reasoning": "All good", "no_changes": True}
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == []
        assert to_update == []
        assert to_add == []

    def test_handles_empty_changes(self):
        """Test handling of empty changes dict."""
        changes = {}
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == []
        assert to_update == []
        assert to_add == []

    def test_handles_missing_arrays(self):
        """Test handling when arrays are missing from changes."""
        changes = {"reasoning": "Only reasoning provided"}
        existing_ids = {"mem-1"}

        to_delete, to_update, to_add = validate_changes(changes, existing_ids)

        assert to_delete == []
        assert to_update == []
        assert to_add == []


class TestDefragmentUserMemories:
    """Test the main defragmentation function."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
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
            Memory(
                id="mem-1",
                user_id="user-123",
                content="User likes coffee",
                category="preference",
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2024, 1, 1),
            ),
            Memory(
                id="mem-2",
                user_id="user-123",
                content="User prefers dark roast coffee",
                category="preference",
                created_at=datetime(2024, 1, 2),
                updated_at=datetime(2024, 1, 2),
            ),
        ]

    def test_returns_skipped_for_empty_memories(self, mock_llm, mock_user):
        """Test that empty memory list is skipped."""
        from scripts.defragment_memories import defragment_user_memories

        result = defragment_user_memories(mock_user, [], mock_llm)

        assert result["skipped"] is True
        mock_llm.invoke.assert_not_called()

    def test_calls_llm_with_formatted_memories(self, mock_llm, mock_user, sample_memories):
        """Test that LLM is called with properly formatted memories."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.return_value = MagicMock(
            content='{"reasoning": "Test", "no_changes": true}'
        )

        defragment_user_memories(mock_user, sample_memories, mock_llm)

        mock_llm.invoke.assert_called_once()
        call_args = mock_llm.invoke.call_args[0][0]

        # Should have system and user messages
        assert len(call_args) == 2
        assert call_args[0]["role"] == "system"
        assert call_args[1]["role"] == "user"

        # User message should contain formatted memories
        assert "User likes coffee" in call_args[1]["content"]

    @patch("scripts.defragment_memories.db")
    def test_dry_run_does_not_modify_database(self, mock_db, mock_llm, mock_user, sample_memories):
        """Test that dry run doesn't modify the database."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.return_value = MagicMock(
            content='{"reasoning": "Test", "delete": ["mem-1"]}'
        )

        result = defragment_user_memories(mock_user, sample_memories, mock_llm, dry_run=True)

        assert result["deleted"] == 1  # Reports what would be deleted
        mock_db.bulk_update_memories.assert_not_called()

    @patch("scripts.defragment_memories.db")
    def test_applies_changes_to_database(self, mock_db, mock_llm, mock_user, sample_memories):
        """Test that changes are applied to database in non-dry-run mode."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.return_value = MagicMock(
            content='{"reasoning": "Consolidating", "delete": ["mem-1"], "update": [{"id": "mem-2", "content": "User loves dark roast coffee"}]}'
        )
        mock_db.bulk_update_memories.return_value = {
            "deleted": 1,
            "updated": 1,
            "added": 0,
        }

        result = defragment_user_memories(mock_user, sample_memories, mock_llm, dry_run=False)

        mock_db.bulk_update_memories.assert_called_once()
        assert result["deleted"] == 1
        assert result["updated"] == 1

    def test_handles_llm_error(self, mock_llm, mock_user, sample_memories):
        """Test that LLM errors are handled gracefully."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.side_effect = Exception("API error")

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True

    def test_handles_unparseable_response(self, mock_llm, mock_user, sample_memories):
        """Test that unparseable LLM responses are handled."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.return_value = MagicMock(content="Not valid JSON at all")

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True

    def test_handles_no_changes_response(self, mock_llm, mock_user, sample_memories):
        """Test handling of no_changes response from LLM."""
        from scripts.defragment_memories import defragment_user_memories

        mock_llm.invoke.return_value = MagicMock(
            content='{"reasoning": "Memories are well organized", "no_changes": true}'
        )

        result = defragment_user_memories(mock_user, sample_memories, mock_llm)

        assert result["skipped"] is True
        assert result["deleted"] == 0
        assert result["updated"] == 0
        assert result["added"] == 0
