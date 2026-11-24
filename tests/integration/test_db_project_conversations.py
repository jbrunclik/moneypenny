"""Project chats leave the main list and live in their project; creation,
the trash and the archive keep the filing straight."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.db.models.projects import ProjectWriteError

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Project, User


@pytest.fixture
def other_user(test_database: Database) -> User:
    return test_database.get_or_create_user(email="jana@example.com", name="Jana")


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Bikes")


def _filed(db: Database, user: User, project: Project, title: str) -> Conversation:
    conv = db.create_conversation(user.id, title, project_id=project.id)
    assert conv.project_id == project.id
    return conv


class TestProjectConversations:
    def test_main_list_hides_project_chats_but_keeps_pinned(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        plain = test_database.create_conversation(test_user.id, "Plain")
        filed = _filed(test_database, test_user, project, "Filed")
        pinned = _filed(test_database, test_user, project, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)

        rows, _cursor, _more, total = test_database.list_conversations_paginated_with_counts(
            test_user.id
        )
        pinned_rows = test_database.list_pinned_conversations(test_user.id)

        assert [c.id for c, _n, _p in rows] == [plain.id]
        assert [c.id for c, _n, _p in pinned_rows] == [pinned.id]
        assert total == 2  # the plain chat and the pinned one
        assert filed.id not in {c.id for c, _n, _p in rows}

    def test_sync_listing_includes_project_chats(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        filed = _filed(test_database, test_user, project, "Filed")
        ids = {
            c.id for c, _n, _p in test_database.list_conversations_with_message_count(test_user.id)
        }
        assert filed.id in ids

    def test_project_list_shows_only_callers_chats(
        self, test_database: Database, test_user: User, other_user: User, project: Project
    ) -> None:
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        mine = _filed(test_database, test_user, project, "Mine")
        _filed(test_database, other_user, project, "Theirs")

        rows, cursor, more = test_database.list_project_conversations(project.id, test_user.id)

        assert [c.id for c, _n, _p in rows] == [mine.id]
        assert cursor is None
        assert more is False

    def test_project_list_paginates(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        chats = [_filed(test_database, test_user, project, f"Chat {i}") for i in range(3)]

        first, cursor, more = test_database.list_project_conversations(
            project.id, test_user.id, limit=2
        )
        rest, _cursor, more_after = test_database.list_project_conversations(
            project.id, test_user.id, limit=2, cursor=cursor
        )

        assert more is True
        assert more_after is False
        assert [c.id for c, _n, _p in first + rest] == [c.id for c in reversed(chats)]

    def test_project_list_empty_for_non_member(
        self, test_database: Database, other_user: User, project: Project
    ) -> None:
        rows, _cursor, _more = test_database.list_project_conversations(project.id, other_user.id)
        assert rows == []

    def test_create_in_project_requires_membership(
        self, test_database: Database, other_user: User, project: Project
    ) -> None:
        with pytest.raises(ProjectWriteError):
            test_database.create_conversation(other_user.id, "Nope", project_id=project.id)

    def test_restore_from_trash_after_project_deleted_lands_in_main_list(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        conv = _filed(test_database, test_user, project, "Filed")
        test_database.trash_conversations(test_user.id, [conv.id])
        # the trash keeps the filing; the project then goes away
        test_database.delete_project(project.id, test_user.id)

        assert test_database.restore_conversation(conv.id, test_user.id)

        got = test_database.get_conversation(conv.id, test_user.id)
        assert got is not None
        assert got.project_id is None

    def test_restore_after_leaving_lands_in_main_list(
        self, test_database: Database, test_user: User, other_user: User, project: Project
    ) -> None:
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        conv = _filed(test_database, other_user, project, "Theirs")
        test_database.trash_conversations(other_user.id, [conv.id])
        # leaving clears live chats only; the trashed one still names the project
        test_database.remove_project_member(project.id, other_user.id, other_user.id)
        with test_database._pool.get_connection() as connection:
            connection.execute(
                "UPDATE conversations SET project_id = ? WHERE id = ?", (project.id, conv.id)
            )
            connection.commit()

        assert test_database.restore_conversations(other_user.id, [conv.id]) == [conv.id]

        got = test_database.get_conversation(conv.id, other_user.id)
        assert got is not None
        assert got.project_id is None

    def test_restore_keeps_project_when_still_member(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        conv = _filed(test_database, test_user, project, "Filed")
        test_database.trash_conversations(test_user.id, [conv.id])

        assert test_database.restore_conversation(conv.id, test_user.id)

        got = test_database.get_conversation(conv.id, test_user.id)
        assert got is not None
        assert got.project_id == project.id

    def test_archived_list_includes_project_chats_with_project_id(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        conv = _filed(test_database, test_user, project, "Filed")
        test_database.archive_conversation(conv.id, test_user.id)

        rows, *_rest = test_database.list_archived_conversations_paginated(test_user.id)

        [(got, _n, _p)] = [r for r in rows if r[0].id == conv.id]
        assert got.project_id == project.id
