"""Which worker process runs a turn, so a dead one is known at once
(src/api/helpers/turn_owner.py). Nov 14 2026: a worker died mid-turn and the
user's next message steered the dead turn for ~100 s - the journal stall rule
needs 180 s to call it dead."""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from src.api.helpers import turn_owner
from src.db.models import Database, use_database
from src.db.models.timestamps import to_db


@pytest.fixture
def db(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


def dead_pid() -> int:
    """The pid of a process that has exited."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_a_turn_with_no_owner_is_not_known_dead(db: Database) -> None:
    assert turn_owner.turn_owner_gone("msg-1") is False


def test_this_process_owns_a_live_turn(db: Database) -> None:
    turn_owner.record_turn_owner("msg-1")
    assert turn_owner.turn_owner_gone("msg-1") is False


def test_a_turn_whose_worker_exited_is_dead(db: Database) -> None:
    db.kv_set(turn_owner.SYSTEM_KV_USER_ID, turn_owner.NAMESPACE, "msg-1", str(dead_pid()))
    assert turn_owner.turn_owner_gone("msg-1") is True


def test_a_live_other_process_keeps_the_turn(db: Database) -> None:
    """Another worker of this host still running the turn."""
    db.kv_set(turn_owner.SYSTEM_KV_USER_ID, turn_owner.NAMESPACE, "msg-1", str(os.getppid()))
    assert turn_owner.turn_owner_gone("msg-1") is False


def test_old_owner_records_are_swept(db: Database) -> None:
    turn_owner.record_turn_owner("old")
    turn_owner.record_turn_owner("new")
    with db._pool.get_connection() as conn:
        conn.execute(
            "UPDATE kv_store SET updated_at = ? WHERE namespace = ? AND key = 'old'",
            (to_db(datetime.now(UTC) - timedelta(hours=2)), turn_owner.NAMESPACE),
        )
        conn.commit()
    turn_owner.sweep_turn_owners(max_age_seconds=3600)
    assert db.kv_get(turn_owner.SYSTEM_KV_USER_ID, turn_owner.NAMESPACE, "old") is None
    assert db.kv_get(turn_owner.SYSTEM_KV_USER_ID, turn_owner.NAMESPACE, "new") is not None
