"""Scheduled items over the API: a chat's items (header chip), cancel, pause,
resume, and the Command Center's "From chats" lane."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

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


def test_a_trashed_chats_items_are_hidden_until_restored(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    _add(test_database, test_user, test_conversation)
    test_database.trash_conversation(test_conversation.id, test_user.id)

    lane = client.get("/api/agents/command-center", headers=auth_headers).get_json()
    assert lane["chat_items"] == []

    test_database.restore_conversation(test_conversation.id, test_user.id)
    lane = client.get("/api/agents/command-center", headers=auth_headers).get_json()
    assert [i["title"] for i in lane["chat_items"]] == ["Call the plumber"]


def test_the_command_center_lists_items_from_chats(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    _add(
        test_database,
        test_user,
        test_conversation,
        next_run_at=datetime.now(UTC) + timedelta(days=2),
    )
    _watcher(test_database, test_user, test_conversation)

    body = client.get("/api/agents/command-center", headers=auth_headers).get_json()

    assert [i["kind"] for i in body["chat_items"]] == ["watcher", "reminder"]


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
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    job = _job(test_database, test_user, test_conversation)
    test_database.create_approval_request(job.id, test_user.id, "todoist", None, "Delete a task")

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


@pytest.mark.parametrize("action", ["delete", "pause", "resume"])
def test_an_agents_job_cannot_be_managed_as_a_chat_item(
    action: str,
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
) -> None:
    agent = test_database.create_agent(test_user.id, "VWCE Watcher", schedule="0 18 * * 5")
    method, path = (
        ("delete", f"/api/schedules/{agent.id}")
        if action == "delete"
        else (
            "post",
            f"/api/schedules/{agent.id}/{action}",
        )
    )

    response = getattr(client, method)(path, headers=auth_headers)

    assert response.status_code == 409
    assert test_database.get_agent(agent.id, test_user.id) is not None
