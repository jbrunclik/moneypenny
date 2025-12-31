"""Integration tests for src/db/models.py Database class."""

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestUserOperations:
    """Tests for User CRUD operations."""

    def test_create_user(self, test_database: Database) -> None:
        """Should create a new user with all fields."""
        user = test_database.get_or_create_user(
            email="new@example.com",
            name="New User",
            picture="https://example.com/pic.jpg",
        )

        assert user.id is not None
        assert len(user.id) == 36  # UUID format
        assert user.email == "new@example.com"
        assert user.name == "New User"
        assert user.picture == "https://example.com/pic.jpg"
        assert isinstance(user.created_at, datetime)

    def test_get_existing_user(self, test_database: Database) -> None:
        """Should return existing user without creating duplicate."""
        user1 = test_database.get_or_create_user(
            email="existing@example.com",
            name="First Name",
        )

        # Get same user again with different name
        user2 = test_database.get_or_create_user(
            email="existing@example.com",
            name="Different Name",  # Should be ignored
        )

        assert user1.id == user2.id
        assert user2.name == "First Name"  # Original name preserved

    def test_get_user_by_id(self, test_database: Database, test_user: User) -> None:
        """Should find user by ID."""
        found_user = test_database.get_user_by_id(test_user.id)

        assert found_user is not None
        assert found_user.id == test_user.id
        assert found_user.email == test_user.email

    def test_get_nonexistent_user_returns_none(self, test_database: Database) -> None:
        """Should return None for non-existent user ID."""
        user = test_database.get_user_by_id("nonexistent-user-id")
        assert user is None

    def test_user_without_picture(self, test_database: Database) -> None:
        """Should create user without picture."""
        user = test_database.get_or_create_user(
            email="nopic@example.com",
            name="No Picture",
        )

        assert user.picture is None

    def test_user_custom_instructions_default_none(self, test_database: Database) -> None:
        """New user should have custom_instructions as None."""
        user = test_database.get_or_create_user(
            email="new_instructions@example.com",
            name="New User",
        )

        assert user.custom_instructions is None

    def test_update_user_custom_instructions(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should update custom instructions."""
        success = test_database.update_user_custom_instructions(test_user.id, "Be concise.")

        assert success is True

        # Verify the update
        updated_user = test_database.get_user_by_id(test_user.id)
        assert updated_user is not None
        assert updated_user.custom_instructions == "Be concise."

    def test_update_user_custom_instructions_clear(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should clear custom instructions with None."""
        # First set some instructions
        test_database.update_user_custom_instructions(test_user.id, "Be concise.")

        # Then clear them
        success = test_database.update_user_custom_instructions(test_user.id, None)

        assert success is True

        # Verify they were cleared
        updated_user = test_database.get_user_by_id(test_user.id)
        assert updated_user is not None
        assert updated_user.custom_instructions is None

    def test_update_user_custom_instructions_nonexistent_user(
        self, test_database: Database
    ) -> None:
        """Should return False for non-existent user."""
        success = test_database.update_user_custom_instructions(
            "nonexistent-user-id", "Be concise."
        )

        assert success is False


class TestConversationOperations:
    """Tests for Conversation CRUD operations."""

    def test_create_conversation(self, test_database: Database, test_user: User) -> None:
        """Should create conversation with all fields."""
        conv = test_database.create_conversation(
            user_id=test_user.id,
            title="Test Chat",
            model="gemini-3-flash-preview",
        )

        assert conv.id is not None
        assert len(conv.id) == 36  # UUID format
        assert conv.title == "Test Chat"
        assert conv.model == "gemini-3-flash-preview"
        assert conv.user_id == test_user.id
        assert isinstance(conv.created_at, datetime)
        assert isinstance(conv.updated_at, datetime)

    def test_create_conversation_default_model(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should use default model when not specified."""
        from src.config import Config

        conv = test_database.create_conversation(user_id=test_user.id)

        assert conv.model == Config.DEFAULT_MODEL

    def test_get_conversation(self, test_database: Database, test_user: User) -> None:
        """Should get conversation by ID and user."""
        conv = test_database.create_conversation(test_user.id, "Test")

        found = test_database.get_conversation(conv.id, test_user.id)

        assert found is not None
        assert found.id == conv.id
        assert found.title == "Test"

    def test_get_conversation_wrong_user(self, test_database: Database, test_user: User) -> None:
        """Should not return conversation for wrong user."""
        conv = test_database.create_conversation(test_user.id)

        found = test_database.get_conversation(conv.id, "different-user-id")

        assert found is None

    def test_list_conversations_ordered_by_updated(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should list conversations ordered by updated_at DESC."""
        conv1 = test_database.create_conversation(test_user.id, "Conv 1")
        _conv2 = test_database.create_conversation(test_user.id, "Conv 2")

        # Update conv1 to make it more recent
        test_database.update_conversation(conv1.id, test_user.id, title="Conv 1 Updated")

        conversations = test_database.list_conversations(test_user.id)

        assert len(conversations) == 2
        assert conversations[0].id == conv1.id  # Most recently updated first

    def test_list_conversations_empty(self, test_database: Database, test_user: User) -> None:
        """Should return empty list when user has no conversations."""
        conversations = test_database.list_conversations(test_user.id)
        assert conversations == []

    def test_update_conversation_title(self, test_database: Database, test_user: User) -> None:
        """Should update conversation title."""
        conv = test_database.create_conversation(test_user.id, "Original")

        result = test_database.update_conversation(conv.id, test_user.id, title="New Title")

        assert result is True
        updated = test_database.get_conversation(conv.id, test_user.id)
        assert updated is not None
        assert updated.title == "New Title"

    def test_update_conversation_model(self, test_database: Database, test_user: User) -> None:
        """Should update conversation model."""
        conv = test_database.create_conversation(test_user.id, model="gemini-3-flash-preview")

        result = test_database.update_conversation(
            conv.id, test_user.id, model="gemini-3-pro-preview"
        )

        assert result is True
        updated = test_database.get_conversation(conv.id, test_user.id)
        assert updated is not None
        assert updated.model == "gemini-3-pro-preview"

    def test_update_nonexistent_conversation(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return False for non-existent conversation."""
        result = test_database.update_conversation("nonexistent-id", test_user.id, title="Test")
        assert result is False

    def test_delete_conversation(self, test_database: Database, test_user: User) -> None:
        """Should delete conversation."""
        conv = test_database.create_conversation(test_user.id)

        result = test_database.delete_conversation(conv.id, test_user.id)

        assert result is True
        assert test_database.get_conversation(conv.id, test_user.id) is None

    def test_delete_conversation_cascades_messages(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should delete related messages when conversation is deleted."""
        conv = test_database.create_conversation(test_user.id)
        test_database.add_message(conv.id, "user", "Hello")
        test_database.add_message(conv.id, "assistant", "Hi there")

        result = test_database.delete_conversation(conv.id, test_user.id)

        assert result is True
        assert test_database.get_messages(conv.id) == []

    def test_delete_nonexistent_conversation(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return False for non-existent conversation."""
        result = test_database.delete_conversation("nonexistent-id", test_user.id)
        assert result is False


class TestMessageOperations:
    """Tests for Message CRUD operations."""

    def test_add_message(self, test_database: Database, test_conversation: Conversation) -> None:
        """Should add message to conversation."""
        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="Hello!",
        )

        assert msg.id is not None
        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert msg.conversation_id == test_conversation.id
        assert isinstance(msg.created_at, datetime)

    def test_add_message_with_files(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should store file attachments."""
        files = [{"name": "test.png", "type": "image/png", "data": "base64data"}]

        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="See attachment",
            files=files,
        )

        assert msg.files == files

    def test_add_message_with_sources(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should store web sources for assistant messages."""
        sources = [{"title": "Wikipedia", "url": "https://wikipedia.org"}]

        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="assistant",
            content="Based on sources...",
            sources=sources,
        )

        assert msg.sources == sources

    def test_add_message_with_generated_images(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should store generated image metadata."""
        generated_images = [{"prompt": "A sunset over mountains"}]

        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="assistant",
            content="Here's your image",
            generated_images=generated_images,
        )

        assert msg.generated_images == generated_images

    def test_add_message_updates_conversation(
        self, test_database: Database, test_conversation: Conversation, test_user: User
    ) -> None:
        """Adding message should update conversation's updated_at."""
        original_updated = test_conversation.updated_at

        test_database.add_message(test_conversation.id, "user", "New message")

        updated_conv = test_database.get_conversation(test_conversation.id, test_user.id)
        assert updated_conv is not None
        assert updated_conv.updated_at >= original_updated

    def test_get_messages_ordered_by_time(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return messages ordered by creation time."""
        test_database.add_message(test_conversation.id, "user", "First")
        test_database.add_message(test_conversation.id, "assistant", "Second")
        test_database.add_message(test_conversation.id, "user", "Third")

        messages = test_database.get_messages(test_conversation.id)

        assert len(messages) == 3
        assert messages[0].content == "First"
        assert messages[1].content == "Second"
        assert messages[2].content == "Third"

    def test_get_messages_empty(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return empty list for conversation with no messages."""
        messages = test_database.get_messages(test_conversation.id)
        assert messages == []

    def test_get_message_by_id(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should find message by ID."""
        msg = test_database.add_message(test_conversation.id, "user", "Test")

        found = test_database.get_message_by_id(msg.id)

        assert found is not None
        assert found.id == msg.id
        assert found.content == "Test"

    def test_get_nonexistent_message(self, test_database: Database) -> None:
        """Should return None for non-existent message."""
        msg = test_database.get_message_by_id("nonexistent-id")
        assert msg is None


class TestCostOperations:
    """Tests for cost tracking operations."""

    def test_save_message_cost(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should save message cost data."""
        msg = test_database.add_message(test_conversation.id, "assistant", "Response")

        test_database.save_message_cost(
            message_id=msg.id,
            conversation_id=test_conversation.id,
            user_id=test_user.id,
            model="gemini-3-flash-preview",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )

        cost = test_database.get_message_cost(msg.id)

        assert cost is not None
        assert cost["cost_usd"] == pytest.approx(0.05)
        assert cost["input_tokens"] == 1000
        assert cost["output_tokens"] == 500
        assert cost["model"] == "gemini-3-flash-preview"

    def test_save_message_cost_with_image_generation(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should save cost including image generation cost."""
        msg = test_database.add_message(test_conversation.id, "assistant", "Image")

        test_database.save_message_cost(
            message_id=msg.id,
            conversation_id=test_conversation.id,
            user_id=test_user.id,
            model="gemini-3-flash-preview",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.10,
            image_generation_cost_usd=0.08,
        )

        cost = test_database.get_message_cost(msg.id)

        assert cost is not None
        assert cost["image_generation_cost_usd"] == pytest.approx(0.08)

    def test_get_conversation_cost(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should sum all message costs in conversation."""
        msg1 = test_database.add_message(test_conversation.id, "assistant", "R1")
        msg2 = test_database.add_message(test_conversation.id, "assistant", "R2")

        test_database.save_message_cost(
            msg1.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.01
        )
        test_database.save_message_cost(
            msg2.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 200, 100, 0.02
        )

        total = test_database.get_conversation_cost(test_conversation.id)

        assert total == pytest.approx(0.03)

    def test_get_conversation_cost_empty(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return 0 for conversation with no cost data."""
        total = test_database.get_conversation_cost(test_conversation.id)
        assert total == 0.0

    def test_get_user_monthly_cost(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should get monthly cost breakdown."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R1")
        test_database.save_message_cost(
            msg.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.05
        )

        now = datetime.now()
        result = test_database.get_user_monthly_cost(test_user.id, now.year, now.month)

        assert result["total_usd"] == pytest.approx(0.05)
        assert result["message_count"] == 1
        assert "gemini-3-flash-preview" in result["breakdown"]

    def test_get_user_monthly_cost_invalid_month(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should raise ValueError for invalid month."""
        with pytest.raises(ValueError, match="Month must be between"):
            test_database.get_user_monthly_cost(test_user.id, 2024, 13)

        with pytest.raises(ValueError, match="Month must be between"):
            test_database.get_user_monthly_cost(test_user.id, 2024, 0)

    def test_get_user_cost_history(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should return monthly cost history."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R1")
        test_database.save_message_cost(
            msg.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.05
        )

        history = test_database.get_user_cost_history(test_user.id)

        assert len(history) >= 1
        now = datetime.now()
        assert any(h["year"] == now.year and h["month"] == now.month for h in history)

    def test_delete_conversation_preserves_costs(
        self,
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Deleting conversation should preserve cost data for accurate reporting."""
        msg = test_database.add_message(test_conversation.id, "assistant", "R1")
        test_database.save_message_cost(
            msg.id, test_conversation.id, test_user.id, "gemini-3-flash-preview", 100, 50, 0.05
        )

        test_database.delete_conversation(test_conversation.id, test_user.id)

        # Cost should still exist (money was already spent)
        cost = test_database.get_message_cost(msg.id)
        assert cost is not None
        assert cost["cost_usd"] == 0.05
        assert cost["input_tokens"] == 100
        assert cost["output_tokens"] == 50


class TestSyncOperations:
    """Tests for sync-related operations (list with message count, updated_since)."""

    def test_list_conversations_with_message_count_empty(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return empty list when user has no conversations."""
        result = test_database.list_conversations_with_message_count(test_user.id)
        assert result == []

    def test_list_conversations_with_message_count_no_messages(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return conversations with zero message count."""
        conv = test_database.create_conversation(test_user.id, "Empty Chat")

        result = test_database.list_conversations_with_message_count(test_user.id)

        assert len(result) == 1
        conversation, message_count = result[0]
        assert conversation.id == conv.id
        assert conversation.title == "Empty Chat"
        assert message_count == 0

    def test_list_conversations_with_message_count_with_messages(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return correct message counts."""
        conv1 = test_database.create_conversation(test_user.id, "Chat 1")
        conv2 = test_database.create_conversation(test_user.id, "Chat 2")

        # Add messages to conv1
        test_database.add_message(conv1.id, "user", "Hello")
        test_database.add_message(conv1.id, "assistant", "Hi there")
        test_database.add_message(conv1.id, "user", "How are you?")

        # Add messages to conv2
        test_database.add_message(conv2.id, "user", "One message")

        result = test_database.list_conversations_with_message_count(test_user.id)

        assert len(result) == 2
        # Results should be ordered by updated_at DESC (conv2 is most recent since we added message last)
        conv2_result = next((r for r in result if r[0].id == conv2.id), None)
        conv1_result = next((r for r in result if r[0].id == conv1.id), None)

        assert conv1_result is not None
        assert conv2_result is not None
        assert conv1_result[1] == 3  # 3 messages in conv1
        assert conv2_result[1] == 1  # 1 message in conv2

    def test_list_conversations_with_message_count_ordered_by_updated(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return conversations ordered by updated_at DESC."""
        conv1 = test_database.create_conversation(test_user.id, "First")
        conv2 = test_database.create_conversation(test_user.id, "Second")

        # Update conv1 to make it most recent
        test_database.add_message(conv1.id, "user", "Update")

        result = test_database.list_conversations_with_message_count(test_user.id)

        assert len(result) == 2
        assert result[0][0].id == conv1.id  # Most recently updated first
        assert result[1][0].id == conv2.id

    def test_get_conversations_updated_since_none_updated(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return empty list when no conversations updated since timestamp."""
        # Create conversation (not used directly, needs to exist for test)
        test_database.create_conversation(test_user.id, "Old Chat")

        # Get conversations updated after the conversation was created
        future_time = datetime(2099, 1, 1)
        result = test_database.get_conversations_updated_since(test_user.id, future_time)

        assert result == []

    def test_get_conversations_updated_since_all_updated(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should return all conversations when all are updated since timestamp."""
        past_time = datetime(2000, 1, 1)
        conv = test_database.create_conversation(test_user.id, "Recent Chat")
        test_database.add_message(conv.id, "user", "Hello")

        result = test_database.get_conversations_updated_since(test_user.id, past_time)

        assert len(result) == 1
        conversation, message_count = result[0]
        assert conversation.id == conv.id
        assert message_count == 1

    def test_get_conversations_updated_since_selective(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should only return conversations updated after the given timestamp."""
        import time

        # Create first conversation (not used directly, needs to exist before checkpoint)
        test_database.create_conversation(test_user.id, "Conv 1")

        # Wait a tiny bit and capture the time
        time.sleep(0.01)
        checkpoint_time = datetime.now()

        # Wait again and create second conversation (will be after checkpoint)
        time.sleep(0.01)
        conv2 = test_database.create_conversation(test_user.id, "Conv 2")
        test_database.add_message(conv2.id, "user", "New message")

        result = test_database.get_conversations_updated_since(test_user.id, checkpoint_time)

        # Only conv2 should be returned (created after checkpoint)
        assert len(result) == 1
        assert result[0][0].id == conv2.id
        assert result[0][1] == 1  # message count

    def test_get_conversations_updated_since_includes_updated_old_conv(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should include old conversations that were updated after the timestamp."""
        import time

        # Create conversation
        conv = test_database.create_conversation(test_user.id, "Old Conv")

        # Wait and capture checkpoint
        time.sleep(0.01)
        checkpoint_time = datetime.now()

        # Wait and add message to update the conversation
        time.sleep(0.01)
        test_database.add_message(conv.id, "user", "New message updates conv")

        result = test_database.get_conversations_updated_since(test_user.id, checkpoint_time)

        # Conv should be returned because it was updated (message added) after checkpoint
        assert len(result) == 1
        assert result[0][0].id == conv.id
        assert result[0][1] == 1

    def test_list_conversations_with_message_count_different_user(
        self, test_database: Database, test_user: User
    ) -> None:
        """Should not return conversations from other users."""
        # Create conversation for test user
        test_database.create_conversation(test_user.id, "Test User Conv")

        # Create conversation for different user
        other_user = test_database.get_or_create_user("other@example.com", "Other")
        test_database.create_conversation(other_user.id, "Other User Conv")

        result = test_database.list_conversations_with_message_count(test_user.id)

        assert len(result) == 1
        assert result[0][0].title == "Test User Conv"
