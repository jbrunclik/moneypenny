"""Unit tests for sports tracking database operations.

Tests cover:
- get_sports_conversation
- get_or_create_sports_conversation
- reset_sports_conversation
- list_sports_conversations
- delete_sports_conversation
"""

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from src.db.models import Database, User


class TestGetSportsConversation:
    """Tests for get_sports_conversation."""

    def test_returns_none_when_no_conversation(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should return None if no sports conversation exists."""
        result = test_database.get_sports_conversation(test_user.id, "pushups")
        assert result is None

    def test_returns_conversation_when_exists(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should return the conversation when it exists."""
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        result = test_database.get_sports_conversation(test_user.id, "pushups")
        assert result is not None
        assert result.is_sports is True
        assert result.sports_program == "pushups"

    def test_different_programs_are_independent(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Different programs should have separate conversations."""
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        result = test_database.get_sports_conversation(test_user.id, "running")
        assert result is None


class TestGetOrCreateSportsConversation:
    """Tests for get_or_create_sports_conversation."""

    def test_creates_new_conversation(self, test_database: "Database", test_user: "User") -> None:
        """Should create a new conversation for a program."""
        conv = test_database.get_or_create_sports_conversation(test_user.id, "running")
        assert conv.is_sports is True
        assert conv.sports_program == "running"
        assert conv.user_id == test_user.id
        assert "running" in conv.title.lower()

    def test_returns_existing_conversation(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should return existing conversation on second call."""
        conv1 = test_database.get_or_create_sports_conversation(test_user.id, "cycling")
        conv2 = test_database.get_or_create_sports_conversation(test_user.id, "cycling")
        assert conv1.id == conv2.id

    def test_uses_default_model(self, test_database: "Database", test_user: "User") -> None:
        """Should use default model when none specified."""
        from src.config import Config

        conv = test_database.get_or_create_sports_conversation(test_user.id, "swim")
        assert conv.model == Config.DEFAULT_MODEL

    def test_uses_specified_model(self, test_database: "Database", test_user: "User") -> None:
        """Should use specified model when provided."""
        conv = test_database.get_or_create_sports_conversation(
            test_user.id, "yoga", model="custom-model"
        )
        assert conv.model == "custom-model"

    def test_user_isolation(self, test_database: "Database", test_user: "User") -> None:
        """Different users should have independent conversations."""
        user2 = test_database.get_or_create_user(
            email="other@example.com", name="Other", picture=""
        )
        conv1 = test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        conv2 = test_database.get_or_create_sports_conversation(user2.id, "pushups")
        assert conv1.id != conv2.id


class TestResetSportsConversation:
    """Tests for reset_sports_conversation."""

    def test_returns_none_when_no_conversation(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should return None if conversation doesn't exist."""
        result = test_database.reset_sports_conversation(test_user.id, "nonexistent")
        assert result is None

    @patch("src.db.models.sports.Config.AGENT_CHECKPOINTING_ENABLED", False)
    def test_deletes_messages(self, test_database: "Database", test_user: "User") -> None:
        """Should delete all messages but keep the conversation."""
        conv = test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Hello",
        )
        test_database.add_message(
            conversation_id=conv.id,
            role="assistant",
            content="Hi there",
        )

        messages_before = test_database.get_messages(conv.id)
        assert len(messages_before) == 2

        result = test_database.reset_sports_conversation(test_user.id, "pushups")
        assert result is not None

        messages_after = test_database.get_messages(conv.id)
        assert len(messages_after) == 0

        # Conversation should still exist
        conv_after = test_database.get_sports_conversation(test_user.id, "pushups")
        assert conv_after is not None
        assert conv_after.id == conv.id


class TestListSportsConversations:
    """Tests for list_sports_conversations."""

    def test_empty_list(self, test_database: "Database", test_user: "User") -> None:
        """Should return empty list when no conversations exist."""
        result = test_database.list_sports_conversations(test_user.id)
        assert result == []

    def test_lists_all_programs(self, test_database: "Database", test_user: "User") -> None:
        """Should list all sports conversations for the user."""
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.get_or_create_sports_conversation(test_user.id, "running")

        result = test_database.list_sports_conversations(test_user.id)
        assert len(result) == 2
        programs = {c.sports_program for c in result}
        assert programs == {"pushups", "running"}

    def test_excludes_other_users(self, test_database: "Database", test_user: "User") -> None:
        """Should only return conversations for the specified user."""
        user2 = test_database.get_or_create_user(
            email="other@example.com", name="Other", picture=""
        )
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.get_or_create_sports_conversation(user2.id, "running")

        result = test_database.list_sports_conversations(test_user.id)
        assert len(result) == 1
        assert result[0].sports_program == "pushups"


class TestDeleteSportsConversation:
    """Tests for delete_sports_conversation."""

    def test_returns_false_when_not_found(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should return False if conversation doesn't exist."""
        result = test_database.delete_sports_conversation(test_user.id, "nonexistent")
        assert result is False

    @patch("src.db.models.sports.Config.AGENT_CHECKPOINTING_ENABLED", False)
    def test_deletes_conversation_and_messages(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Should delete the conversation and all its messages."""
        conv = test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.add_message(
            conversation_id=conv.id,
            role="user",
            content="Hello",
        )

        result = test_database.delete_sports_conversation(test_user.id, "pushups")
        assert result is True

        # Conversation should be gone
        conv_after = test_database.get_sports_conversation(test_user.id, "pushups")
        assert conv_after is None

        # Messages should be gone
        messages = test_database.get_messages(conv.id)
        assert len(messages) == 0

    @patch("src.db.models.sports.Config.AGENT_CHECKPOINTING_ENABLED", False)
    def test_does_not_affect_other_programs(
        self, test_database: "Database", test_user: "User"
    ) -> None:
        """Deleting one program should not affect others."""
        test_database.get_or_create_sports_conversation(test_user.id, "pushups")
        test_database.get_or_create_sports_conversation(test_user.id, "running")

        test_database.delete_sports_conversation(test_user.id, "pushups")

        remaining = test_database.list_sports_conversations(test_user.id)
        assert len(remaining) == 1
        assert remaining[0].sports_program == "running"
