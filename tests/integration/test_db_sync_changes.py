"""Tests for the cross-device sync change log (migration 0061 triggers).

Every write to a conversation or its messages must move that conversation's
change seq forward, so another device's cursor sync sees it - including the
writes the old updated_at + message_count detector missed (archive, trash,
pin, anonymous toggle, message deletes, permanent deletes).
"""

from collections.abc import Callable

import pytest

from src.api.schemas.common import MessageRole
from src.db.models import Conversation, Database, User


def _changes(db: Database, user: User, after: int = 0) -> dict[str, int]:
    return {c.conversation_id: c.seq for c in db.get_conversation_changes(user.id, after, 1000)}


def _bumps(db: Database, user: User, conv: Conversation, write: Callable[[], object]) -> bool:
    before = _changes(db, user)[conv.id]
    write()
    return _changes(db, user)[conv.id] > before


class TestChangeLog:
    def test_creating_a_conversation_records_a_change(
        self, test_database: Database, test_user: User
    ) -> None:
        cursor = test_database.get_sync_cursor()
        conv = test_database.create_conversation(test_user.id, "New")

        changes = test_database.get_conversation_changes(test_user.id, cursor, 100)

        assert [c.conversation_id for c in changes] == [conv.id]
        assert changes[0].seq > cursor
        assert changes[0].conversation is not None
        assert changes[0].conversation.title == "New"

    @pytest.mark.parametrize(
        "write",
        [
            "message",
            "rename",
            "archive",
            "unarchive",
            "pin",
            "trash",
            "restore",
            "anonymous",
            "delete_message",
            "edit_message",
        ],
    )
    def test_every_write_moves_the_conversation_forward(
        self, test_database: Database, test_user: User, write: str
    ) -> None:
        db = test_database
        conv = db.create_conversation(test_user.id, "Chat")
        msg = db.add_message(conv.id, MessageRole.USER, "hi")
        if write == "unarchive":
            db.archive_conversation(conv.id, test_user.id)
        if write == "restore":
            db.trash_conversation(conv.id, test_user.id)

        writes: dict[str, Callable[[], object]] = {
            "message": lambda: db.add_message(conv.id, MessageRole.ASSISTANT, "hello"),
            "rename": lambda: db.update_conversation(conv.id, test_user.id, title="Renamed"),
            "archive": lambda: db.archive_conversation(conv.id, test_user.id),
            "unarchive": lambda: db.unarchive_conversation(conv.id, test_user.id),
            "pin": lambda: db.set_conversation_pinned(conv.id, test_user.id, True),
            "trash": lambda: db.trash_conversation(conv.id, test_user.id),
            "restore": lambda: db.restore_conversation(conv.id, test_user.id),
            "anonymous": lambda: db.set_conversation_anonymous_mode(conv.id, test_user.id, True),
            "delete_message": lambda: db.delete_message(msg.id, test_user.id),
            "edit_message": lambda: db.update_message_content(msg.id, "edited"),
        }

        assert _bumps(db, test_user, conv, writes[write])

    def test_a_permanent_delete_leaves_a_tombstone(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Doomed")
        test_database.add_message(conv.id, MessageRole.USER, "bye")
        cursor = test_database.get_sync_cursor()

        test_database.delete_conversation(conv.id, test_user.id)

        changes = test_database.get_conversation_changes(test_user.id, cursor, 100)
        assert [c.conversation_id for c in changes] == [conv.id]
        assert changes[0].conversation is None

    def test_changes_are_per_user(self, test_database: Database, test_user: User) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        cursor = test_database.get_sync_cursor()
        test_database.create_conversation(other.id, "Theirs")

        assert test_database.get_conversation_changes(test_user.id, cursor, 100) == []

    def test_changes_come_oldest_first_and_page_by_limit(
        self, test_database: Database, test_user: User
    ) -> None:
        cursor = test_database.get_sync_cursor()
        convs = [test_database.create_conversation(test_user.id, f"C{i}") for i in range(3)]

        first = test_database.get_conversation_changes(test_user.id, cursor, 2)
        rest = test_database.get_conversation_changes(test_user.id, first[-1].seq, 2)

        assert [c.conversation_id for c in first + rest] == [c.id for c in convs]

    def test_change_carries_count_and_last_message(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Chat")
        test_database.add_message(conv.id, MessageRole.USER, "question")
        last = test_database.add_message(conv.id, MessageRole.ASSISTANT, "answer")

        change = test_database.get_conversation_changes(test_user.id, 0, 100)[-1]

        assert change.message_count == 2
        assert change.last_message_id == last.id
        assert change.last_message_preview == "answer"
