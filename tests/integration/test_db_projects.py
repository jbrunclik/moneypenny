"""Integration tests for the project store (projects, members, chat moves)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from src.config import Config
from src.db.models.projects import ProjectWriteError
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def other_user(test_database: Database) -> User:
    return test_database.get_or_create_user(email="jana@example.com", name="Jana Nováková")


def _set(db: Database, table: str, row_id: str, column: str, value: object) -> None:
    with db._pool.get_connection() as conn:
        conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (value, row_id))
        conn.commit()


def _project_id_of(db: Database, table: str, row_id: str) -> str | None:
    with db._pool.get_connection() as conn:
        row = conn.execute(f"SELECT project_id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return row[0]


class TestProjects:
    def test_create_makes_owner_a_member(self, test_database: Database, test_user: User) -> None:
        project = test_database.create_project(test_user.id, "Bikes", "Metric units")

        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.owner_id == test_user.id
        assert got.instructions == "Metric units"
        assert got.member_ids == [test_user.id]

    def test_create_past_cap_raises(
        self, test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "PROJECTS_MAX_PER_USER", 2)
        test_database.create_project(test_user.id, "A")
        test_database.create_project(test_user.id, "B")
        with pytest.raises(ProjectWriteError, match="2"):
            test_database.create_project(test_user.id, "C")

    def test_get_project_needs_membership(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Bikes")
        assert test_database.get_project(project.id, other_user.id) is None
        assert test_database.add_project_member(project.id, test_user.id, other_user.id)
        got = test_database.get_project(project.id, other_user.id)
        assert got is not None
        assert sorted(got.member_ids) == sorted([test_user.id, other_user.id])

    def test_only_owner_adds_members(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Bikes")
        assert not test_database.add_project_member(project.id, other_user.id, other_user.id)

    def test_only_owner_renames(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Bikes")
        test_database.add_project_member(project.id, test_user.id, other_user.id)

        assert not test_database.update_project(project.id, other_user.id, name="Kola")
        assert test_database.update_project(project.id, test_user.id, name="Kola")
        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.name == "Kola"

    def test_member_edits_instructions_with_expected_text(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Bikes", "Old")
        test_database.add_project_member(project.id, test_user.id, other_user.id)

        assert not test_database.update_project(
            project.id, other_user.id, instructions="New", expected_instructions="Stale"
        )
        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.instructions == "Old"
        assert test_database.update_project(
            project.id, other_user.id, instructions="New", expected_instructions="Old"
        )
        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.instructions == "New"

    def test_remove_member_returns_their_chats_to_main_list(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        theirs = test_database.create_conversation(other_user.id, "Wallbox")
        mine = test_database.create_conversation(test_user.id, "Lights")
        assert test_database.set_conversation_project(theirs.id, other_user.id, project.id)
        assert test_database.set_conversation_project(mine.id, test_user.id, project.id)

        assert test_database.remove_project_member(project.id, test_user.id, other_user.id)

        assert _project_id_of(test_database, "conversations", theirs.id) is None
        assert _project_id_of(test_database, "conversations", mine.id) == project.id
        assert test_database.get_project(project.id, other_user.id) is None

    def test_member_can_leave(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        assert test_database.remove_project_member(project.id, other_user.id, other_user.id)
        assert test_database.get_project(project.id, other_user.id) is None

    def test_owner_cannot_be_removed(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        assert not test_database.remove_project_member(project.id, test_user.id, test_user.id)
        assert not test_database.remove_project_member(project.id, other_user.id, test_user.id)

    def test_delete_soft_deletes_memories_documents_and_frees_chats(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        conv = test_database.create_conversation(test_user.id, "Wallbox")
        test_database.set_conversation_project(conv.id, test_user.id, project.id)
        memory = test_database.add_memory(test_user.id, "Garage has 3-phase power")
        personal = test_database.add_memory(test_user.id, "Likes tea")
        _set(test_database, "user_memories", memory.id, "project_id", project.id)

        assert test_database.delete_project(project.id, test_user.id)

        assert test_database.get_project(project.id, test_user.id) is None
        assert _project_id_of(test_database, "conversations", conv.id) is None
        with test_database._pool.get_connection() as conn:
            deleted = {
                r[0]: r[1]
                for r in conn.execute("SELECT id, deleted_at FROM user_memories").fetchall()
            }
        assert deleted[memory.id] is not None
        assert deleted[personal.id] is None
        assert [p.id for p in test_database.list_deleted_projects(test_user.id)] == [project.id]

    def test_restore_brings_back_memories_not_chats(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        conv = test_database.create_conversation(test_user.id, "Wallbox")
        test_database.set_conversation_project(conv.id, test_user.id, project.id)
        memory = test_database.add_memory(test_user.id, "Garage has 3-phase power")
        _set(test_database, "user_memories", memory.id, "project_id", project.id)
        test_database.delete_project(project.id, test_user.id)

        assert test_database.restore_project(project.id, test_user.id)

        assert test_database.get_project(project.id, test_user.id) is not None
        assert [m.id for m in test_database.list_project_memories(project.id)] == [memory.id]
        assert _project_id_of(test_database, "conversations", conv.id) is None

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("is_agent", 1),
            ("is_sports", 1),
            ("is_language", 1),
            ("is_whats_new", 1),
            ("is_planning", 1),
            ("anonymous_mode", 1),
            ("standing_type", "daily_briefing"),
        ],
    )
    def test_move_refuses_special_chats(
        self, test_database: Database, test_user: User, column: str, value: object
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        conv = test_database.create_conversation(test_user.id, "Special")
        _set(test_database, "conversations", conv.id, column, value)
        assert not test_database.set_conversation_project(conv.id, test_user.id, project.id)
        assert _project_id_of(test_database, "conversations", conv.id) is None

    def test_move_refuses_non_member_project(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(other_user.id, "Theirs")
        conv = test_database.create_conversation(test_user.id, "Mine")
        assert not test_database.set_conversation_project(conv.id, test_user.id, project.id)

    def test_move_refuses_other_users_chat(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        conv = test_database.create_conversation(other_user.id, "Theirs")
        assert not test_database.set_conversation_project(conv.id, test_user.id, project.id)

    def test_move_out_with_none(self, test_database: Database, test_user: User) -> None:
        project = test_database.create_project(test_user.id, "Home")
        conv = test_database.create_conversation(test_user.id, "Wallbox")
        test_database.set_conversation_project(conv.id, test_user.id, project.id)
        assert test_database.set_conversation_project(conv.id, test_user.id, None)
        assert _project_id_of(test_database, "conversations", conv.id) is None

    def test_project_for_conversation_none_after_leaving(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        conv = test_database.create_conversation(other_user.id, "Wallbox")
        test_database.set_conversation_project(conv.id, other_user.id, project.id)
        got = test_database.project_for_conversation(conv.id, other_user.id)
        assert got is not None
        assert got.id == project.id

        test_database.remove_project_member(project.id, other_user.id, other_user.id)

        assert test_database.project_for_conversation(conv.id, other_user.id) is None

    def test_list_projects_counts_only_own_chats(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        for user in (test_user, other_user, other_user):
            conv = test_database.create_conversation(user.id, "Chat")
            test_database.set_conversation_project(conv.id, user.id, project.id)

        [mine] = test_database.list_projects(test_user.id)
        [theirs] = test_database.list_projects(other_user.id)

        assert mine.chat_count == 1
        assert theirs.chat_count == 2
        assert mine.project.id == theirs.project.id
        assert sorted(mine.member_names) == ["Jana Nováková", test_user.name]

    def test_czech_and_emoji_name_round_trips(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "🐟 Hanák / Zeleko")
        got = test_database.get_project(project.id, test_user.id)
        assert got is not None
        assert got.name == "🐟 Hanák / Zeleko"

    def test_list_people_excludes_caller(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        people = test_database.list_people(test_user.id)
        assert (other_user.id, "Jana Nováková") in people
        assert all(user_id != test_user.id for user_id, _ in people)


class TestProjectPurge:
    def test_deleted_project_memories_outlive_memory_purge_until_project_purge(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        memory = test_database.add_memory(test_user.id, "Garage has 3-phase power")
        _set(test_database, "user_memories", memory.id, "project_id", project.id)
        test_database.delete_project(project.id, test_user.id)
        long_ago = to_db(utc_now() - timedelta(days=60))
        for table in ("projects", "user_memories"):
            with test_database._pool.get_connection() as conn:
                conn.execute(f"UPDATE {table} SET deleted_at = ?", (long_ago,))
                conn.commit()

        test_database.purge_deleted_memories(7)
        with test_database._pool.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_memories").fetchone()[0] == 1

        assert test_database.purge_deleted_projects(30) == 1
        with test_database._pool.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM user_memories").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


class TestProjectsVersion:
    def test_member_change_bumps_projects_version_for_both_users(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        owner_before = test_database.projects_version(test_user.id)
        member_before = test_database.projects_version(other_user.id)

        test_database.add_project_member(project.id, test_user.id, other_user.id)

        assert test_database.projects_version(test_user.id) != owner_before
        assert test_database.projects_version(other_user.id) != member_before

        shared = test_database.projects_version(other_user.id)
        test_database.remove_project_member(project.id, test_user.id, other_user.id)
        assert test_database.projects_version(other_user.id) != shared

    def test_rename_and_instructions_bump_version(
        self, test_database: Database, test_user: User
    ) -> None:
        project = test_database.create_project(test_user.id, "Home")
        before = test_database.projects_version(test_user.id)
        test_database.update_project(project.id, test_user.id, instructions="Metric")
        assert test_database.projects_version(test_user.id) != before

    def test_unrelated_user_version_unchanged(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        before = test_database.projects_version(other_user.id)
        test_database.create_project(test_user.id, "Home")
        assert test_database.projects_version(other_user.id) == before
