"""kv_store writes stay in the turn's own namespace; reads are open.

An instruction planted in a page could make a run or a chat overwrite
`sports`, `places` or another agent's data (Nov 15 2026 audit;
docs/superpowers/specs/2026-11-16-agent-safety-design.md).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.agent_kv import kv_store

if TYPE_CHECKING:
    from src.db.models import Database, User


@contextmanager
def _turn(
    database: Database, user: User, job_id: str | None = None, standing: str | None = None
) -> Iterator[None]:
    job = None
    if job_id:
        job = MagicMock()
        job.item.id = job_id
    with (
        patch("src.agent.tools.agent_kv.get_conversation_context", return_value=("c1", user.id)),
        patch("src.agent.run_context.get_job_context", return_value=job),
        patch("src.agent.tools.agent_kv.get_standing_namespace", return_value=standing),
        patch("src.agent.tools.agent_kv.db", database),
    ):
        yield


def _call(**kwargs: str) -> str:
    return str(kv_store.invoke(kwargs))


@pytest.fixture
def seeded(test_database: Database, test_user: User) -> tuple[Database, User]:
    test_database.kv_set(test_user.id, "places", "home", '{"address": "Praha"}')
    test_database.kv_set(test_user.id, "sports", "p1:routine", '{"day": "Mon"}')
    test_database.kv_set(test_user.id, "agent:other", "state", '{"n": 1}')
    return test_database, test_user


@pytest.mark.parametrize("namespace", ["places", "sports", "agent:other"])
@pytest.mark.parametrize(
    ("action", "value"), [("set", '{"x": 1}'), ("merge", '{"x": 1}'), ("delete", "")]
)
def test_a_run_cannot_write_another_namespace(
    seeded: tuple[Database, User], namespace: str, action: str, value: str
) -> None:
    database, user = seeded
    key = {"places": "home", "sports": "p1:routine", "agent:other": "state"}[namespace]
    before = database.kv_get(user.id, namespace, key)
    with _turn(database, user, job_id="mine"):
        result = _call(action=action, key=key, value=value, namespace=namespace)
    payload = json.loads(result)
    assert "agent:mine" in payload["error"]
    assert payload["retriable"] is False
    assert database.kv_get(user.id, namespace, key) == before


def test_a_run_reads_shared_namespaces(seeded: tuple[Database, User]) -> None:
    database, user = seeded
    with _turn(database, user, job_id="mine"):
        assert "Praha" in _call(action="get", key="home", namespace="places")
        assert "p1:routine" in _call(action="list", namespace="sports")


def test_a_run_writes_its_own_namespace(seeded: tuple[Database, User]) -> None:
    database, user = seeded
    with _turn(database, user, job_id="mine"):
        _call(action="set", key="a", value='{"v": 1}')
        _call(action="merge", key="a", value='{"w": 2}', namespace="agent:mine")
    assert json.loads(database.kv_get(user.id, "agent:mine", "a") or "") == {"v": 1, "w": 2}


def test_a_standing_chat_writes_its_own_and_reads_others(
    seeded: tuple[Database, User],
) -> None:
    database, user = seeded
    with _turn(database, user, standing="sports"):
        _call(action="merge", key="p1:routine", value='{"day": "Tue"}')
        refused = json.loads(_call(action="set", key="home", value="{}", namespace="places"))
        assert "Praha" in _call(action="get", key="home", namespace="places")
    assert json.loads(database.kv_get(user.id, "sports", "p1:routine") or "") == {"day": "Tue"}
    assert "sports" in refused["error"]


def test_a_refused_write_is_logged(seeded: tuple[Database, User]) -> None:
    import src.agent.tools.agent_kv as module

    database, user = seeded
    with _turn(database, user, job_id="mine"), patch.object(module.logger, "warning") as warning:
        _call(action="delete", key="home", namespace="places")
    (message,) = warning.call_args.args
    assert message == "kv write refused"
    assert warning.call_args.kwargs["extra"] == {
        "user_id": user.id,
        "namespace": "places",
        "own": "agent:mine",
        "action": "delete",
    }
