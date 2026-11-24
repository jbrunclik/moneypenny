"""A write to a shared project's memory is labelled under the reply, so the
author sees at once what the family will read (privacy gate, projects design)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.agent.memory_review import format_note
from src.api.helpers.project_notes import note_shared_project_writes
from src.db.models.memory import MemoryWrite
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Database, User


def _turn(db: Database, user: User, conv_id: str, project_id: str | None, text: str) -> str:
    """A user message, a project memory written by the turn, the reply's id."""
    db.add_message(conv_id, MessageRole.USER, "Note this")
    if project_id:
        db.apply_memory_batch(
            user.id,
            conv_id,
            [MemoryWrite(action="add", content=text, category="fact", project_id=project_id)],
            project_id=project_id,
        )
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
        _turn(test_database, test_user, conv.id, project.id, "Garage has 3-phase power")
        reply = _turn(test_database, test_user, conv.id, None, "")

        note_shared_project_writes(conv.id, test_user.id, reply)

        assert _note(test_database, reply) is None


def test_format_note_names_the_project() -> None:
    note = format_note(["Garage has 3-phase power"], project_name="Home")
    assert note.startswith("Garage has 3-phase power")
    assert "Home" in note
    assert format_note(["x"]) == "x"
