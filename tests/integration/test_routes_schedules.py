"""Scheduled items over the API: a chat's items (header chip), cancel, pause,
resume, and the Command Center's "From chats" lane."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.db.models.dataclasses import ScheduledItem
from src.enums import MessageRole

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database, User


def _add(
    db: Database, user: User, conversation: Conversation, **overrides: object
) -> ScheduledItem:
    item = ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        conversation_id=conversation.id,
        kind="reminder",
        text="Call the plumber",
        end_condition=None,
        schedule=None,
        interval_hours=None,
        next_run_at=datetime.now(UTC) + timedelta(days=1),
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=datetime.now(UTC),
    )
    return db.add_item(replace(item, **overrides))  # type: ignore[arg-type]


def _watcher(db: Database, user: User, conversation: Conversation) -> ScheduledItem:
    return _add(
        db,
        user,
        conversation,
        kind="watcher",
        text="the school's job board",
        end_condition="a teacher job is posted",
        interval_hours=24,
    )


def test_a_chats_items(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _watcher(test_database, test_user, test_conversation)
    other = test_database.create_conversation(user_id=test_user.id, title="Other")
    _add(test_database, test_user, other)

    response = client.get(
        f"/api/conversations/{test_conversation.id}/schedules", headers=auth_headers
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["conversation_id"] == test_conversation.id
    [listed] = body["items"]
    assert listed["id"] == item.id
    assert listed["kind"] == "watcher"
    assert listed["title"] == "the school's job board"
    assert listed["when"] == "checks daily"
    assert listed["ends"].startswith("until a teacher job is posted, at most until")
    assert listed["status"] == "active"
    assert listed["conversation_title"] == test_conversation.title


def test_another_users_chat_is_not_found(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database
) -> None:
    stranger = test_database.get_or_create_user(email="stranger@example.com", name="S")
    theirs = test_database.create_conversation(user_id=stranger.id, title="Theirs")

    response = client.get(f"/api/conversations/{theirs.id}/schedules", headers=auth_headers)

    assert response.status_code == 404


def test_delete_an_item(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _add(test_database, test_user, test_conversation)

    assert client.delete(f"/api/schedules/{item.id}", headers=auth_headers).status_code == 204
    assert test_database.list_items(test_user.id) == []
    assert client.delete(f"/api/schedules/{item.id}", headers=auth_headers).status_code == 404


def test_pause_and_resume_a_watcher(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _watcher(test_database, test_user, test_conversation)

    paused = client.post(f"/api/schedules/{item.id}/pause", headers=auth_headers)
    assert paused.status_code == 200
    assert paused.get_json()["status"] == "paused"
    resumed = client.post(f"/api/schedules/{item.id}/resume", headers=auth_headers)
    assert resumed.get_json()["status"] == "active"


def test_a_reminder_cannot_be_paused(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _add(test_database, test_user, test_conversation)

    response = client.post(f"/api/schedules/{item.id}/pause", headers=auth_headers)

    assert response.status_code == 409


def test_a_delivered_turn_carries_its_label(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    test_database.add_message(
        test_conversation.id,
        MessageRole.ASSISTANT,
        "How's the tail?",
        delivery={"kind": "check_in", "label": "Check-in · Fri 18:00"},
    )

    body = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers).get_json()

    [message] = body["messages"]
    assert message["delivery"] == {"kind": "check_in", "label": "Check-in · Fri 18:00"}


def test_pausing_a_running_item_is_a_conflict(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _watcher(test_database, test_user, test_conversation)
    test_database.claim_due_items(item.next_run_at)

    response = client.post(f"/api/schedules/{item.id}/pause", headers=auth_headers)

    assert response.status_code == 409


# Standing jobs (phase 2 plan, A4): run now, paused reason, any cron


def _job(
    db: Database, user: User, conversation: Conversation, **overrides: object
) -> ScheduledItem:
    fields: dict[str, object] = {
        "kind": "recurring",
        "text": "Send the morning briefing.",
        "schedule": "0 * * * *",  # hourly: a cron the schedule tool would not build
        "grants": ["*"],
    }
    return _add(db, user, conversation, **(fields | overrides))


def test_standing_job_is_listed_with_its_reason_and_any_cron(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    job = _job(test_database, test_user, test_conversation)
    test_database.set_item_paused(job.id, test_user.id, True, reason="failures")

    response = client.get(
        f"/api/conversations/{test_conversation.id}/schedules", headers=auth_headers
    )

    [item] = response.get_json()["items"]
    assert (item["standing"], item["paused_reason"], item["status"]) == (True, "failures", "paused")
    assert "0 * * * *" in item["when"]


def test_run_now_standing_job(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agent.item_runner import RunOutcome
    from src.api.routes import schedules

    ran: list[ScheduledItem] = []

    def run_job_now(item: ScheduledItem, user: User, *, message: str | None = None) -> RunOutcome:
        ran.append(item)
        return RunOutcome("report", "Good morning.")

    monkeypatch.setattr(schedules, "run_job_now", run_job_now)
    job = _job(test_database, test_user, test_conversation)

    response = client.post(f"/api/schedules/{job.id}/run", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {"status": "report"}
    assert [i.id for i in ran] == [job.id]


def test_run_now_refused_for_light_items(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _watcher(test_database, test_user, test_conversation)

    response = client.post(f"/api/schedules/{item.id}/run", headers=auth_headers)

    assert response.status_code == 409


def test_run_now_refused_while_awaiting_approval(
    make_run_card: Any,
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    job = _job(test_database, test_user, test_conversation)
    make_run_card(job)

    response = client.post(f"/api/schedules/{job.id}/run", headers=auth_headers)

    assert response.status_code == 409


def test_run_now_refused_while_the_scheduler_runs_it(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    job = _job(test_database, test_user, test_conversation, next_run_at=datetime.now(UTC))
    [_] = test_database.claim_due_items(datetime.now(UTC) + timedelta(seconds=1))

    response = client.post(f"/api/schedules/{job.id}/run", headers=auth_headers)

    assert response.status_code == 409


# Standing chats phase 3 (E2): every job pauses and resumes from the job list


def test_pause_resume_an_agent_job_keeps_settings_in_step(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agent import daily_briefing

    monkeypatch.setattr(daily_briefing, "db", test_database)
    daily_briefing.set_briefing(test_user, enabled=True, time_str="07:15", timezone="Europe/Prague")
    user = test_database.get_user_by_id(test_user.id)
    assert user is not None and user.daily_briefing_job_id
    job_id = user.daily_briefing_job_id

    paused = client.post(f"/api/schedules/{job_id}/pause", headers=auth_headers)

    assert paused.status_code == 200
    agent = test_database.get_standing_chat(job_id, test_user.id)
    assert agent is not None and agent.enabled is False
    assert daily_briefing.get_briefing_status(user)["enabled"] is False

    resumed = client.post(f"/api/schedules/{job_id}/resume", headers=auth_headers)

    assert resumed.status_code == 200
    agent = test_database.get_standing_chat(job_id, test_user.id)
    assert agent is not None and agent.enabled is True
    assert daily_briefing.get_briefing_status(user)["enabled"] is True


def test_run_now_refused_over_budget_or_awaiting_approval(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    job = _job(test_database, test_user, test_conversation, budget_usd=0.1)
    spent = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "run")
    test_database.save_message_cost(
        spent.id, test_conversation.id, test_user.id, "m", 1, 1, 0.2, job_id=job.id
    )

    response = client.post(f"/api/schedules/{job.id}/run", headers=auth_headers)

    assert response.status_code == 409
    assert "budget" in response.get_json()["error"]["message"]


def test_deleting_an_agent_job_still_refused(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")

    response = client.delete(f"/api/schedules/{agent.id}", headers=auth_headers)

    assert response.status_code == 409


def test_resume_after_settings_turned_the_briefing_off_runs_it_again(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part E review C1: Settings off (next run NEVER), then Resume in the job
    list must schedule the next 07:15 again, not leave it never running."""
    from src.agent import daily_briefing
    from src.db.models.scheduled_items import NEVER_RUN_AT

    monkeypatch.setattr(daily_briefing, "db", test_database)
    daily_briefing.set_briefing(test_user, enabled=True, time_str="07:15", timezone="Europe/Prague")
    user = test_database.get_user_by_id(test_user.id)
    assert user is not None and user.daily_briefing_job_id
    job_id = user.daily_briefing_job_id
    daily_briefing.set_briefing(user, enabled=False, time_str="07:15", timezone="Europe/Prague")

    response = client.post(f"/api/schedules/{job_id}/resume", headers=auth_headers)

    assert response.status_code == 200
    job = test_database.get_item(job_id, test_user.id)
    assert job is not None and job.status == "active"
    assert datetime.now(UTC) < job.next_run_at < NEVER_RUN_AT


def test_resume_after_a_long_pause_does_not_catch_up(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    client.post(f"/api/schedules/{agent.id}/pause", headers=auth_headers)
    test_database.finish_item_run(agent.id, datetime.now(UTC) - timedelta(days=2), None, 0, 0)
    test_database.set_item_paused(agent.id, test_user.id, True, reason="disabled")

    client.post(f"/api/schedules/{agent.id}/resume", headers=auth_headers)

    job = test_database.get_item(agent.id, test_user.id)
    assert job is not None and job.next_run_at > datetime.now(UTC)


def test_resume_an_agent_paused_after_failures(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Coach", schedule="0 20 * * *")
    test_database.finish_item_run(agent.id, datetime.now(UTC) - timedelta(days=1), None, 0, 3)
    test_database.set_item_paused(agent.id, test_user.id, True, reason="failures")

    client.post(f"/api/schedules/{agent.id}/resume", headers=auth_headers)

    job = test_database.get_item(agent.id, test_user.id)
    assert job is not None
    assert (job.status, job.paused_reason, job.failures) == ("active", None, 0)
    assert job.next_run_at > datetime.now(UTC)
