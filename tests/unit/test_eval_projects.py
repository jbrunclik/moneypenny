"""The eval harness's project seeding (projects evals, Nov 2026)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from evals.run import EvalCase, seed_project

if TYPE_CHECKING:
    from src.db.models import Database, User


def _case(**project: object) -> EvalCase:
    return EvalCase(id="project_case", description="", user="hi", rubric="", project=dict(project))


def test_seed_project_shared_creates_member(test_database: Database, test_user: User) -> None:
    project_id = seed_project(
        _case(
            name="Hanák",
            instructions="No emoji.",
            shared=True,
            memories=[{"content": "Client builds garden ponds", "category": "fact"}],
        ),
        test_user,
        test_database,
    )

    assert project_id is not None
    project = test_database.get_project(project_id, test_user.id)
    assert project is not None
    assert project.shared is True
    assert project.instructions == "No emoji."
    assert [m.content for m in test_database.list_project_memories(project_id)] == [
        "Client builds garden ponds"
    ]


def test_no_project_seeds_nothing(test_database: Database, test_user: User) -> None:
    assert seed_project(_case(), test_user, test_database) is None
    assert test_database.list_projects(test_user.id) == []
