"""Unit tests for placeholder message DB operations.

Tests update_message_content() and delete_message_by_id() methods
used by the stream recovery placeholder pattern.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

from src.api.schemas.common import MessageRole


class TestUpdateMessageContent:
    """Tests for update_message_content method."""

    def test_updates_all_fields(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should update content, sources, generated_images, and language."""
        # Create a placeholder message
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")
        assert placeholder.content == ""

        # Update with real content
        updated = test_database.update_message_content(
            placeholder.id,
            "Hello, world!",
            sources=[{"title": "Test", "url": "https://example.com"}],
            generated_images=[{"prompt": "a cat"}],
            language="en",
        )

        assert updated is not None
        assert updated.id == placeholder.id
        assert updated.content == "Hello, world!"
        assert updated.sources == [{"title": "Test", "url": "https://example.com"}]
        assert updated.generated_images == [{"prompt": "a cat"}]
        assert updated.language == "en"

    def test_tool_outputs_round_trip(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Tool output digests persist through the placeholder update and reload."""
        digest = [{"tool": "garmin_connect", "args": "{}", "result": '{"hrv":62}'}]
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        updated = test_database.update_message_content(
            placeholder.id, "HRV is 62", tool_outputs=digest
        )

        assert updated is not None
        assert updated.tool_outputs == digest
        assert test_database.get_messages(test_conversation.id)[-1].tool_outputs == digest

    def test_stop_reason_saved_with_the_content(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """A stopped reply's content and stop_reason land in one write."""
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        updated = test_database.update_message_content(
            placeholder.id, "Partial", stop_reason="user"
        )

        assert updated is not None
        assert updated.stop_reason == "user"

    def test_add_message_stores_stop_reason(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Placeholder deleted mid-turn: the INSERT fallback keeps stop_reason too."""
        message = test_database.add_message(
            test_conversation.id, MessageRole.ASSISTANT, "Partial", stop_reason="user"
        )

        saved = test_database.get_message_by_id(message.id)
        assert saved is not None
        assert saved.stop_reason == "user"

    def test_add_message_stores_tool_outputs(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        digest = [{"tool": "todoist", "args": "{}", "result": "[]"}]
        test_database.add_message(
            test_conversation.id, MessageRole.ASSISTANT, "ok", tool_outputs=digest
        )
        assert test_database.get_messages(test_conversation.id)[-1].tool_outputs == digest

    def test_returns_none_for_nonexistent_message(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return None when message doesn't exist."""
        result = test_database.update_message_content(
            "nonexistent-id",
            "content",
        )
        assert result is None

    def test_updates_conversation_updated_at(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should update the conversation's updated_at timestamp."""
        original_updated = test_conversation.updated_at

        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        import time

        time.sleep(0.01)  # Ensure distinct timestamp

        test_database.update_message_content(placeholder.id, "updated content")

        # Re-fetch conversation to check updated_at
        conv = test_database.get_conversation(test_conversation.id, test_conversation.user_id)
        assert conv is not None
        assert conv.updated_at >= original_updated

    def test_preserves_message_role_and_created_at(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should not change role or created_at when updating content."""
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        updated = test_database.update_message_content(placeholder.id, "real content")

        assert updated is not None
        assert updated.role == MessageRole.ASSISTANT
        assert updated.created_at == placeholder.created_at

    def test_updates_content_only(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should update just content when no optional fields provided."""
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        updated = test_database.update_message_content(placeholder.id, "just content")

        assert updated is not None
        assert updated.content == "just content"
        assert updated.sources is None
        assert updated.generated_images is None
        assert updated.language is None
        assert updated.files == []

    def test_handles_files_with_blob_store(
        self, test_database: Database, test_conversation: Conversation, test_blob_store
    ) -> None:
        """Should save file data to blob store and store metadata."""
        placeholder = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

        files = [
            {
                "name": "test.txt",
                "type": "text/plain",
                "data": "SGVsbG8gV29ybGQ=",  # base64 "Hello World"
            }
        ]

        updated = test_database.update_message_content(
            placeholder.id, "content with file", files=files
        )

        assert updated is not None
        assert len(updated.files) == 1
        assert updated.files[0]["name"] == "test.txt"
        assert updated.files[0]["type"] == "text/plain"
        # Binary data should NOT be in metadata
        assert "data" not in updated.files[0]


class TestDeleteMessageById:
    """Tests for delete_message_by_id method."""

    def test_deletes_existing_message(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should delete message and return True."""
        msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "to delete")

        result = test_database.delete_message_by_id(msg.id)

        assert result is True
        # Verify message is gone
        assert test_database.get_message_by_id(msg.id) is None

    def test_returns_false_for_nonexistent(self, test_database: Database) -> None:
        """Should return False when message doesn't exist."""
        result = test_database.delete_message_by_id("nonexistent-id")
        assert result is False

    def test_does_not_affect_other_messages(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should only delete the specified message."""
        msg1 = test_database.add_message(test_conversation.id, MessageRole.USER, "keep this")
        msg2 = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "delete this")

        test_database.delete_message_by_id(msg2.id)

        # msg1 should still exist
        assert test_database.get_message_by_id(msg1.id) is not None
        # msg2 should be gone
        assert test_database.get_message_by_id(msg2.id) is None
