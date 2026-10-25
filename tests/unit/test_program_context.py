"""The program-conversation context loaders (src/api/helpers/program_context.py).

Runs against a real test database (the global ``db`` swapped via
``use_database``); nothing is faked. Covers the happy-path shape, the
program's own KV keys only, and every way the lookup comes back empty:
no programs, unknown program, another user's program, corrupt JSON.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any

import pytest

from src.api.helpers.program_context import load_language_context, load_sports_context
from src.db.models import Database, User, use_database

Loader = Callable[[str, str], dict[str, Any] | None]

# (namespace, loader, default program name)
LOADERS = [
    pytest.param("sports", load_sports_context, "Training", id="sports"),
    pytest.param("language", load_language_context, "Language", id="language"),
]


@pytest.fixture
def db(test_database: Database) -> Generator[Database]:
    with use_database(test_database):
        yield test_database


def _save_programs(db: Database, user: User, namespace: str, programs: list[Any]) -> None:
    db.kv_set(user.id, namespace, "programs", json.dumps(programs))


@pytest.mark.parametrize(("namespace", "load", "default_name"), LOADERS)
class TestProgramContext:
    def test_returns_the_program_name_id_and_its_stored_data(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(db, test_user, namespace, [{"id": "marathon", "name": "Marathon"}])
        db.kv_set(test_user.id, namespace, "marathon:goals", "Sub-4 hours")
        db.kv_set(test_user.id, namespace, "marathon:progress", '{"week": 3}')

        assert load(test_user.id, "marathon") == {
            "program_name": "Marathon",
            "program_id": "marathon",
            "kv_data": {"goals": "Sub-4 hours", "progress": '{"week": 3}'},
        }

    def test_a_program_with_no_stored_data_has_empty_kv_data(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(db, test_user, namespace, [{"id": "marathon", "name": "Marathon"}])

        context = load(test_user.id, "marathon")

        assert context is not None
        assert context["kv_data"] == {}

    def test_an_unnamed_program_gets_the_default_name(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(db, test_user, namespace, [{"id": "marathon"}])

        context = load(test_user.id, "marathon")

        assert context is not None
        assert context["program_name"] == default_name

    def test_only_the_requested_programs_keys_are_loaded(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(
            db,
            test_user,
            namespace,
            [{"id": "run", "name": "Run"}, {"id": "running", "name": "Running"}],
        )
        db.kv_set(test_user.id, namespace, "run:goals", "5k")
        db.kv_set(test_user.id, namespace, "running:goals", "marathon")
        db.kv_set(test_user.id, namespace, "run-2:goals", "10k")

        context = load(test_user.id, "run")

        assert context is not None
        assert context["kv_data"] == {"goals": "5k"}

    def test_keys_keep_everything_after_the_first_colon(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(db, test_user, namespace, [{"id": "run", "name": "Run"}])
        db.kv_set(test_user.id, namespace, "run:session:2026-10-25", "done")

        context = load(test_user.id, "run")

        assert context is not None
        assert context["kv_data"] == {"session:2026-10-25": "done"}

    def test_no_programs_saved_returns_none(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        assert load(test_user.id, "marathon") is None

    def test_an_unknown_program_returns_none(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        _save_programs(db, test_user, namespace, [{"id": "marathon", "name": "Marathon"}])
        db.kv_set(test_user.id, namespace, "other:goals", "orphaned data")

        assert load(test_user.id, "other") is None

    def test_another_users_program_is_not_visible(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        other = db.get_or_create_user(email="other@example.com", name="Other")
        _save_programs(db, other, namespace, [{"id": "marathon", "name": "Marathon"}])
        db.kv_set(other.id, namespace, "marathon:goals", "private")

        assert load(test_user.id, "marathon") is None

    def test_another_users_data_does_not_leak_into_a_same_named_program(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        other = db.get_or_create_user(email="other@example.com", name="Other")
        _save_programs(db, test_user, namespace, [{"id": "marathon", "name": "Mine"}])
        _save_programs(db, other, namespace, [{"id": "marathon", "name": "Theirs"}])
        db.kv_set(other.id, namespace, "marathon:goals", "private")

        context = load(test_user.id, "marathon")

        assert context is not None
        assert (context["program_name"], context["kv_data"]) == ("Mine", {})

    def test_corrupt_programs_json_returns_none(
        self, db: Database, test_user: User, namespace: str, load: Loader, default_name: str
    ) -> None:
        db.kv_set(test_user.id, namespace, "programs", "{not json")

        assert load(test_user.id, "marathon") is None


def test_sports_and_language_programs_live_in_separate_namespaces(
    db: Database, test_user: User
) -> None:
    _save_programs(db, test_user, "sports", [{"id": "marathon", "name": "Marathon"}])

    assert load_sports_context(test_user.id, "marathon") is not None
    assert load_language_context(test_user.id, "marathon") is None
