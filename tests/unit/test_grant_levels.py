"""Grant levels (standing chats phase 2, D3): a tool in a job's grants means
read; "<tool>:write" lets an unattended run change things there. A write
without the write level is a draft: the gate files that exact call's card
and the run pauses - never a silent change; approving lets that one call run.
Destructive operations still need a card per call even with the write level."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from src.agent.run_context import JobContext, clear_job_context, set_job_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import use_database


@pytest.fixture
def run_as(test_database: Any, test_user: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    def start(grants: list[str] | None) -> Any:
        agent = test_database.create_standing_chat(
            test_user.id, f"Job {len(grants or [])}", grants=grants
        )
        set_job_context(
            JobContext(item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id])
        )
        return agent

    with use_database(test_database):
        yield start
    clear_job_context()


def _blocked(tool: str, args: dict[str, Any]) -> Any:
    """The call pauses the run; the card it filed."""
    from src.agent.run_context import get_job_context
    from src.db.models import db

    with pytest.raises(ApprovalRequestedException) as raised:
        check_autonomous_permission(tool, args)
    run = get_job_context()
    assert run is not None
    return db.get_proposal(raised.value.approval_id, run.user.id)


def test_read_grant_allows_reads_only(run_as: Any) -> None:
    run_as(["todoist"])

    check_autonomous_permission("todoist", {"operation": "list_tasks"})
    _blocked("todoist", {"operation": "add_task"})


def test_write_grant_allows_writes_but_not_silent_deletes(run_as: Any) -> None:
    run_as(["todoist", "todoist:write"])

    check_autonomous_permission("todoist", {"operation": "add_task"})
    _blocked("todoist", {"operation": "delete_task"})


def test_all_tools_grant_writes(run_as: Any) -> None:
    run_as(None)

    check_autonomous_permission("google_calendar", {"operation": "create_event"})


def test_write_without_write_grant_files_the_calls_card(run_as: Any, test_database: Any) -> None:
    run_as(["garmin_workout"])
    card = _blocked("garmin_workout", {"action": "add_block", "workout_id": "w1"})
    # A held writable tool can be always allowed from the card
    assert [o["label"] for o in card.options] == ["Approve", "Always allow Garmin workouts changes"]
    test_database.claim_proposal(card.id, "approved", 0, "button")

    check_autonomous_permission("garmin_workout", {"action": "add_block", "workout_id": "w1"})
    _blocked("garmin_workout", {"action": "add_block", "workout_id": "w1"})  # once only


def test_write_level_alone_permits_the_tool(run_as: Any) -> None:
    run_as(["rouvy_workout:write"])

    check_autonomous_permission("rouvy_workout", {"action": "create"})


def test_update_stores_the_grants_exactly(test_database: Any, test_user: Any) -> None:
    """The editor shows write levels (its "can change things" toggle) and
    sends the complete list: a save stores it as sent."""
    agent = test_database.create_standing_chat(
        test_user.id, "Coach", grants=["todoist", "todoist:write", "garmin_workout"]
    )

    test_database.update_standing_chat(agent.id, test_user.id, grants=["todoist", "web_search"])

    job = test_database.get_item(agent.id, test_user.id)
    assert sorted(job.grants) == ["todoist", "web_search"]


def test_job_detail_shows_write_levels(test_database: Any, test_user: Any) -> None:
    from src.api.helpers.standing_responses import standing_to_response

    agent = test_database.create_standing_chat(
        test_user.id, "Coach", grants=["todoist", "todoist:write"]
    )

    assert standing_to_response(agent)["grants"] == ["todoist", "todoist:write"]


# Part D review: the gate must hold through the real tools, per operation


def test_garmin_workout_write_needs_approval_through_the_tool(run_as: Any) -> None:
    from unittest.mock import patch

    from src.agent.tools.garmin_workout import garmin_workout

    run_as(["garmin_workout"])
    with (
        patch("src.agent.tools.garmin_workout.get_garmin_client") as client,
        pytest.raises(ApprovalRequestedException),
    ):
        garmin_workout.invoke({"action": "update", "workout_id": "1", "edits": "[]"})
    client.assert_not_called()


def test_rouvy_write_needs_approval_through_the_tool(run_as: Any) -> None:
    from unittest.mock import patch

    from src.agent.tools.rouvy import rouvy_workout

    run_as(["rouvy_workout"])
    with (
        patch("src.agent.tools.rouvy._write_workout") as write,
        pytest.raises(ApprovalRequestedException),
    ):
        rouvy_workout.invoke({"action": "create", "content": "x", "name": "Tempo"})
    write.assert_not_called()


def test_rouvy_delete_is_destructive_even_with_write(run_as: Any) -> None:
    run_as(["rouvy_workout", "rouvy_workout:write"])

    _blocked("rouvy_workout", {"action": "delete", "workout_id": 7})


def test_an_approved_write_authorizes_only_that_call(run_as: Any, test_database: Any) -> None:
    run_as(["todoist"])
    card = _blocked("todoist", {"operation": "add_task", "content": "Buy milk"})
    test_database.claim_proposal(card.id, "approved", 0, "button")

    _blocked("todoist", {"operation": "add_task", "content": "Buy bread"})  # other text: asks again
    _blocked("todoist", {"operation": "delete_project", "project_id": "w"})  # never a delete
    check_autonomous_permission("todoist", {"operation": "add_task", "content": "Buy milk"})


def test_request_approval_files_an_unbound_card(run_as: Any, test_database: Any) -> None:
    from src.agent.tools.request_approval import request_approval

    agent = run_as(["whatsapp"])

    with pytest.raises(ApprovalRequestedException) as raised:
        request_approval.func(  # type: ignore[attr-defined]
            action_description="Send Jana the weekly summary", tool_name="whatsapp"
        )

    assert raised.value.tool_name == "whatsapp"
    card = test_database.get_proposal(raised.value.approval_id, agent.user_id)
    assert card is not None and card.summary == "Send Jana the weekly summary"
    assert card.options[0]["payload"]["signature"] is None  # nothing consumes it


def test_request_approval_cannot_pose_as_a_settings_change(
    run_as: Any, test_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agent.tools.request_approval import request_approval

    run_as(["todoist"])

    result = request_approval.func(  # type: ignore[attr-defined]
        action_description="Harmless", tool_name="edit_standing_chat"
    )

    assert "edit_standing_chat" in result and "error" in result
