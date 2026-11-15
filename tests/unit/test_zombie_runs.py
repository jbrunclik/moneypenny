"""Zombie cleanup closes crashed runs, not runs paused on their card.

A run waiting on its card was marked failed after AGENT_EXECUTION_TIMEOUT_
MINUTES (10) while the card lives AGENT_APPROVAL_TTL_HOURS (24): the
Command Center showed it failed until the card was answered (Nov 15 2026
audit). The card's own expiry closes it (run_approvals.expire_stale_run_cards);
the cleanup only catches one whose card was lost.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.config import Config
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, User


def _run(db: Database, user: User, status: str, age: timedelta) -> str:
    agent = db.create_standing_chat(user_id=user.id, name=f"Zombie {status} {age}")
    run = db.create_execution(agent.job.id, "scheduled")
    db.update_execution(run.id, status=status)
    with db._pool.get_connection() as conn:
        conn.execute(
            "UPDATE job_runs SET started_at = ? WHERE id = ?", (to_db(utc_now() - age), run.id)
        )
        conn.commit()
    return run.id


def _status(db: Database, run_id: str) -> str:
    with db._pool.get_connection() as conn:
        return str(
            conn.execute("SELECT status FROM job_runs WHERE id = ?", (run_id,)).fetchone()[0]
        )


def test_a_stuck_running_run_is_closed(test_database: Database, test_user: User) -> None:
    run = _run(test_database, test_user, "running", timedelta(minutes=30))
    assert test_database.cleanup_zombie_executions() == 1
    assert _status(test_database, run) == "failed"


def test_a_run_waiting_on_its_card_stays_waiting(test_database: Database, test_user: User) -> None:
    run = _run(test_database, test_user, "waiting_approval", timedelta(minutes=30))
    assert test_database.cleanup_zombie_executions() == 0
    assert _status(test_database, run) == "waiting_approval"


def test_a_wait_past_the_cards_lifetime_is_closed(test_database: Database, test_user: User) -> None:
    age = timedelta(hours=Config.AGENT_APPROVAL_TTL_HOURS + 2)
    run = _run(test_database, test_user, "waiting_approval", age)
    assert test_database.cleanup_zombie_executions() == 1
    assert _status(test_database, run) == "failed"
