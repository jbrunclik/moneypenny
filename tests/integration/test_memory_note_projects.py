"""A write to a shared project's memory is labelled under the reply, so the
author sees at once what the family will read (privacy gate, projects design)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.agent.memory_review import format_note
from src.agent.tools.memory import note_project_writes
from src.api.helpers.project_notes import note_shared_project_writes
from src.db.models.memory import MemoryWrite
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Database, User


def _turn(db: Database, user: User, conv_id: str, project_id: str | None, text: str) -> str:
    """A user message, a project memory written by the turn, the reply's id."""
    db.add_message(conv_id, MessageRole.USER, "Note this")
    if project_id:
        [memory_id] = db.apply_memory_batch(
            user.id,
            conv_id,
            [MemoryWrite(action="add", content=text, category="fact", project_id=project_id)],
            project_id=project_id,
        )
        # What manage_memory records for the reply's note
        note_project_writes(user.id, conv_id, str(memory_id))
    return db.add_message(conv_id, MessageRole.ASSISTANT, "Noted").id


def _note(db: Database, message_id: str) -> str | None:
    with db._pool.get_connection() as conn:
        row = conn.execute(
            "SELECT memory_note FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
    return row[0]


@pytest.mark.usefixtures("app")
class TestSharedProjectNote:
    def test_shared_project_write_sets_note(self, test_database: Database, test_user: User) -> None:
        jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        conv = test_database.create_conversation(test_user.id, "Wallbox", project_id=project.id)
        reply = _turn(test_database, test_user, conv.id, project.id, "Garage has 3-phase power")

        note_shared_project_writes(conv.id, test_user.id, reply)

        assert _note(test_database, reply) == format_note(
            ["Garage has 3-phase power"], project_name="Home"
        )

    def test_solo_project_write_sets_no_note(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        conv = test_database.create_conversation(test_user.id, "Wallbox", project_id=project.id)
        reply = _turn(test_database, test_user, conv.id, project.id, "Garage has 3-phase power")

        note_shared_project_writes(conv.id, test_user.id, reply)

        assert _note(test_database, reply) is None

    def test_earlier_turns_writes_are_not_repeated(
        self, test_database: Database, test_user: User
    ) -> None:
        jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        conv = test_database.create_conversation(test_user.id, "Wallbox", project_id=project.id)
        first = _turn(test_database, test_user, conv.id, project.id, "Garage has 3-phase power")
        note_shared_project_writes(conv.id, test_user.id, first)  # that turn's save
        reply = _turn(test_database, test_user, conv.id, None, "")

        note_shared_project_writes(conv.id, test_user.id, reply)

        assert _note(test_database, reply) is None


def test_format_note_names_the_project() -> None:
    note = format_note(["Garage has 3-phase power"], project_name="Home")
    assert note.startswith("Garage has 3-phase power")
    assert "Home" in note
    assert format_note(["x"]) == "x"


@pytest.mark.usefixtures("app")
class TestNoteCoversPatches:
    def test_patch_of_earlier_chats_memory_is_noted(
        self, test_database: Database, test_user: User
    ) -> None:
        from src.agent.tools.context import set_conversation_context
        from src.agent.tools.memory import manage_memory

        jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
        project = test_database.create_project(test_user.id, "Family")
        test_database.add_project_member(project.id, test_user.id, jana.id)
        earlier = test_database.create_conversation(test_user.id, "Earlier", project_id=project.id)
        [memory_id] = test_database.apply_memory_batch(
            test_user.id,
            earlier.id,
            [
                MemoryWrite(
                    action="add",
                    content="Presentation on Friday",
                    category="fact",
                    project_id=project.id,
                )
            ],
            project_id=project.id,
        )
        assert memory_id is not None
        conv = test_database.create_conversation(test_user.id, "Now", project_id=project.id)
        test_database.add_message(conv.id, MessageRole.USER, "update it")
        set_conversation_context(conv.id, test_user.id)
        try:
            manage_memory.invoke(
                {
                    "operations": [
                        {
                            "action": "patch",
                            "id": memory_id,
                            "old_text": "Friday",
                            "new_text": "Monday",
                        }
                    ]
                }
            )
        finally:
            set_conversation_context(None, None)
        reply = test_database.add_message(conv.id, MessageRole.ASSISTANT, "Done").id

        note_shared_project_writes(conv.id, test_user.id, reply)

        assert _note(test_database, reply) == format_note(
            ["Presentation on Monday"], project_name="Family"
        )
