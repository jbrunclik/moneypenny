"""Unit tests for Database.get_messages_around() method."""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestGetMessagesAround:
    """Tests for get_messages_around method."""

    def test_message_in_middle(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return messages before and after target message."""
        # Create 10 messages with distinct timestamps
        messages = []
        for i in range(10):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)  # Ensure distinct timestamps

        # Get messages around the 5th message (index 4)
        target_msg = messages[4]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=3,  # Should get messages 2, 3, 4 (including target)
            after_limit=3,  # Should get messages 5, 6, 7
        )

        assert result is not None
        result_msgs, pagination = result

        # Should have 6 messages: 3 before (including target) + 3 after
        assert len(result_msgs) == 6

        # Verify messages are in chronological order
        result_ids = [m.id for m in result_msgs]
        expected_ids = [messages[i].id for i in [2, 3, 4, 5, 6, 7]]
        assert result_ids == expected_ids

        # Verify pagination flags
        assert pagination.has_older is True  # Messages 0, 1 exist
        assert pagination.has_newer is True  # Messages 8, 9 exist
        assert pagination.total_count == 10

        # Verify cursors are set
        assert pagination.older_cursor is not None
        assert pagination.newer_cursor is not None

    def test_message_at_beginning(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should handle target message at the beginning (no older messages)."""
        # Create 5 messages
        messages = []
        for i in range(5):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Get messages around the first message
        target_msg = messages[0]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=5,
            after_limit=3,
        )

        assert result is not None
        result_msgs, pagination = result

        # Should have 4 messages: 1 (target) + 3 after
        assert len(result_msgs) == 4
        assert result_msgs[0].id == target_msg.id

        # No older messages
        assert pagination.has_older is False
        assert pagination.older_cursor is None

        # Has newer messages
        assert pagination.has_newer is True
        assert pagination.newer_cursor is not None

    def test_message_at_end(self, test_database: Database, test_conversation: Conversation) -> None:
        """Should handle target message at the end (no newer messages)."""
        # Create 5 messages
        messages = []
        for i in range(5):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Get messages around the last message
        target_msg = messages[4]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=3,
            after_limit=5,
        )

        assert result is not None
        result_msgs, pagination = result

        # Should have 3 messages (before including target)
        assert len(result_msgs) == 3
        assert result_msgs[-1].id == target_msg.id

        # Has older messages
        assert pagination.has_older is True
        assert pagination.older_cursor is not None

        # No newer messages
        assert pagination.has_newer is False
        assert pagination.newer_cursor is None

    def test_nonexistent_message_returns_none(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return None when target message doesn't exist."""
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id="nonexistent-message-id",
            before_limit=5,
            after_limit=5,
        )

        assert result is None

    def test_message_from_different_conversation_returns_none(
        self, test_database: Database, test_user: User, test_conversation: Conversation
    ) -> None:
        """Should return None when message is from a different conversation."""
        # Create a message in the test conversation
        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="Test message",
        )

        # Create a different conversation
        other_conv = test_database.create_conversation(test_user.id, title="Other Conv")

        # Try to get message using the other conversation's ID
        result = test_database.get_messages_around(
            conversation_id=other_conv.id,
            message_id=msg.id,
            before_limit=5,
            after_limit=5,
        )

        assert result is None

    def test_single_message_conversation(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should handle conversation with only one message."""
        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="Only message",
        )

        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=msg.id,
            before_limit=10,
            after_limit=10,
        )

        assert result is not None
        result_msgs, pagination = result

        assert len(result_msgs) == 1
        assert result_msgs[0].id == msg.id

        # No pagination in either direction
        assert pagination.has_older is False
        assert pagination.has_newer is False
        assert pagination.older_cursor is None
        assert pagination.newer_cursor is None
        assert pagination.total_count == 1

    def test_cursors_are_correct_for_continued_pagination(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return correct cursors for continuing pagination."""
        # Create 20 messages
        messages = []
        for i in range(20):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Get messages around message 10 with small limits
        target_msg = messages[10]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=3,
            after_limit=3,
        )

        assert result is not None
        result_msgs, pagination = result

        # Should have messages 8, 9, 10, 11, 12, 13
        assert len(result_msgs) == 6

        # Use older_cursor to load more older messages
        from src.api.schemas import PaginationDirection

        older_msgs, older_pagination = test_database.get_messages_paginated(
            conversation_id=test_conversation.id,
            cursor=pagination.older_cursor,
            direction=PaginationDirection.OLDER,
            limit=5,
        )

        # Should get messages 3, 4, 5, 6, 7 (before message 8)
        assert len(older_msgs) == 5
        assert older_msgs[-1].content == "Message 7"

        # Use newer_cursor to load more newer messages
        newer_msgs, newer_pagination = test_database.get_messages_paginated(
            conversation_id=test_conversation.id,
            cursor=pagination.newer_cursor,
            direction=PaginationDirection.NEWER,
            limit=5,
        )

        # Should get messages 14, 15, 16, 17, 18 (after message 13)
        assert len(newer_msgs) == 5
        assert newer_msgs[0].content == "Message 14"

    def test_target_message_included_in_results(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should always include the target message in results."""
        # Create messages
        messages = []
        for i in range(5):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        target_msg = messages[2]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=2,
            after_limit=2,
        )

        assert result is not None
        result_msgs, _ = result

        # Verify target message is in the results
        result_ids = [m.id for m in result_msgs]
        assert target_msg.id in result_ids

    def test_messages_chronological_order(
        self, test_database: Database, test_conversation: Conversation
    ) -> None:
        """Should return messages in chronological order (oldest first)."""
        messages = []
        for i in range(10):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        target_msg = messages[5]
        result = test_database.get_messages_around(
            conversation_id=test_conversation.id,
            message_id=target_msg.id,
            before_limit=3,
            after_limit=3,
        )

        assert result is not None
        result_msgs, _ = result

        # Verify chronological order
        for i in range(1, len(result_msgs)):
            assert result_msgs[i].created_at >= result_msgs[i - 1].created_at
