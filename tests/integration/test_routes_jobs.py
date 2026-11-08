"""GET /api/jobs: every job in one overview - light items set from chats and
standing jobs (agents), with each job's recent runs and next run, needs
attention first (standing chats phase 3, E1)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import ScheduledItem

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database, User


def _item(db: Database, user: User, conv: Conversation, **overrides: object) -> ScheduledItem:
    item = ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        conversation_id=conv.id,
        kind="watcher",
        text="the school's job board",
        end_condition="a teacher job is posted",
        schedule=None,
        interval_hours=24,
        next_run_at=datetime.now(UTC) + timedelta(hours=5),
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=datetime.now(UTC),
    )
    return db.add_item(replace(item, **overrides))  # type: ignore[arg-type]


def _overview(client: FlaskClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/jobs", headers=headers)
    assert response.status_code == 200
    return response.get_json()


def test_overview_lists_light_items_and_jobs(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(test_database, test_user, test_conversation)
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")

    jobs = {j["id"]: j for j in _overview(client, auth_headers)["jobs"]}

    assert set(jobs) == {item.id, agent.id}
    assert (jobs[item.id]["standing"], jobs[item.id]["area"]) == (False, "chat")
    assert (jobs[agent.id]["standing"], jobs[agent.id]["area"]) == (True, "agents")
    assert jobs[agent.id]["editable"] is True
    assert jobs[item.id]["conversation_id"] == test_conversation.id


def test_overview_lists_live_chats_only(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    _item(test_database, test_user, test_conversation)
    test_database.trash_conversation(test_conversation.id, test_user.id)

    assert _overview(client, auth_headers)["jobs"] == []

    test_database.restore_conversation(test_conversation.id, test_user.id)
    assert len(_overview(client, auth_headers)["jobs"]) == 1


def test_agent_job_titled_with_its_chat(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "VWCE Watcher", schedule="0 18 * * 5")

    [job] = _overview(client, auth_headers)["jobs"]

    assert (job["id"], job["title"]) == (agent.id, "VWCE Watcher")
    assert "Friday" in job["when"]


def test_recent_runs_newest_three(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    for status in ("completed", "completed", "failed", "completed"):
        run = test_database.create_execution(agent.id, "scheduled")
        test_database.update_execution(run.id, status=status, error_message="Garmin down")

    [job] = _overview(client, auth_headers)["jobs"]

    assert len(job["recent_runs"]) == 3
    assert job["recent_runs"][0]["status"] == "completed"
    assert job["recent_runs"][1]["status"] == "failed"


def test_needs_attention_first(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    soon = _item(
        test_database,
        test_user,
        test_conversation,
        next_run_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    test_database.create_approval_request(agent.id, test_user.id, "todoist", None, "Add milk")

    jobs = _overview(client, auth_headers)["jobs"]

    assert [j["id"] for j in jobs] == [agent.id, soon.id]
    assert jobs[0]["has_pending_approval"] is True


def test_counts_for_the_sidebar(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    waiting = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    test_database.create_approval_request(waiting.id, test_user.id, "todoist", None, "Add milk")
    failing = test_database.create_standing_chat(test_user.id, "Watcher", schedule="0 18 * * 5")
    run = test_database.create_execution(failing.id, "scheduled")
    test_database.update_execution(run.id, status="failed", error_message="boom")
    test_database.add_message(failing.conversation_id or "", "assistant", "A report")

    overview = _overview(client, auth_headers)

    assert (overview["jobs_waiting"], overview["jobs_with_errors"]) == (1, 1)
    assert overview["total_unread"] == 1
    assert len(overview["pending_approvals"]) == 1


def test_never_run_jobs_have_no_next_run(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    test_database.create_standing_chat(test_user.id, "On demand")  # no schedule

    [job] = _overview(client, auth_headers)["jobs"]

    assert job["next_run_at"] is None
