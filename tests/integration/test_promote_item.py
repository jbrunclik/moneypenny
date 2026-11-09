"""A chat's watcher or recurring check becomes a full agent: the draft the
editor opens with, and the create that replaces the item (docs/features/agents.md)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import ScheduledItem

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Conversation, Database, User


def _item(db: Database, user: User, conv: Conversation, **fields: Any) -> ScheduledItem:
    item = ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        conversation_id=conv.id,
        kind="watcher",
        text="Check whether the school posted a teacher job",
        end_condition="a teacher job is posted",
        schedule=None,
        interval_hours=24,
        next_run_at=datetime(2026, 11, 10, 8, 30, tzinfo=UTC),
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=datetime.now(UTC),
    )
    return db.add_item(replace(item, **fields))


def test_a_watcher_drafts_an_agent_that_checks_daily_and_stops_itself(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(test_database, test_user, test_conversation)

    response = client.get(f"/api/schedules/{item.id}/agent-draft", headers=auth_headers)

    assert response.status_code == 200
    draft = response.get_json()
    assert draft["name"] == "Check whether the school posted a teacher job"
    assert draft["instructions"].startswith("Check whether the school posted a teacher job")
    assert "a teacher job is posted" in draft["instructions"]
    assert draft["schedule"] == "30 9 * * *"  # its next check, 08:30 UTC, is 09:30 in Prague
    assert draft["grants"] == ["web_search", "fetch_url", "research"]
    assert draft["fresh_context"] is False
    assert draft["replaces_item_id"] == item.id


def test_a_recurring_check_keeps_its_cron(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(
        test_database,
        test_user,
        test_conversation,
        kind="recurring",
        text="What's for lunch at school",
        end_condition=None,
        schedule="0 9 * * 1",
        interval_hours=None,
    )

    draft = client.get(f"/api/schedules/{item.id}/agent-draft", headers=auth_headers).get_json()

    assert (draft["name"], draft["schedule"]) == ("What's for lunch at school", "0 9 * * 1")


def test_a_reminder_has_no_agent_to_become(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(test_database, test_user, test_conversation, kind="reminder", interval_hours=None)

    response = client.get(f"/api/schedules/{item.id}/agent-draft", headers=auth_headers)

    assert response.status_code == 409


def test_creating_the_agent_replaces_the_item(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(test_database, test_user, test_conversation)
    draft = client.get(f"/api/schedules/{item.id}/agent-draft", headers=auth_headers).get_json()
    body = {k: draft[k] for k in ("name", "instructions", "schedule", "timezone", "grants")}

    response = client.post(
        "/api/jobs", headers=auth_headers, json={**body, "replaces_item_id": item.id}
    )

    assert response.status_code == 201
    assert test_database.get_item(item.id, test_user.id) is None
    agent = test_database.get_standing_chat(response.get_json()["id"], test_user.id)
    assert agent is not None and agent.schedule == "30 9 * * *"


def test_a_failed_create_keeps_the_item(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    item = _item(test_database, test_user, test_conversation)
    test_database.create_standing_chat(test_user.id, "Taken")

    response = client.post(
        "/api/jobs",
        headers=auth_headers,
        json={"name": "Taken", "replaces_item_id": item.id},
    )

    assert response.status_code == 400
    assert test_database.get_item(item.id, test_user.id) is not None


def test_another_users_item_cannot_be_replaced(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_conversation: Conversation,
) -> None:
    other = test_database.get_or_create_user(email="other@example.com", name="O")
    conv = test_database.create_conversation(other.id, "Theirs")
    item = _item(test_database, other, conv)

    response = client.post(
        "/api/jobs", headers=auth_headers, json={"name": "Mine", "replaces_item_id": item.id}
    )

    assert response.status_code == 404
    assert test_database.get_item(item.id, other.id) is not None


def test_the_sidebar_shows_how_many_jobs_a_chat_has(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_database: Database,
    test_user: User,
    test_conversation: Conversation,
) -> None:
    """Light items only: an agent's own job is shown as the agent."""
    _item(test_database, test_user, test_conversation)
    _item(test_database, test_user, test_conversation, kind="reminder", interval_hours=None)
    quiet = test_database.create_conversation(test_user.id, "Quiet")

    listed = client.get("/api/conversations", headers=auth_headers).get_json()["conversations"]
    synced = client.get("/api/conversations/sync", headers=auth_headers).get_json()["conversations"]

    for found in (listed, synced):
        counts = {c["id"]: c.get("scheduled_count") for c in found}
        assert counts[test_conversation.id] == 2
        assert not counts[quiet.id]
