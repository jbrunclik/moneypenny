"""Grant levels (standing chats phase 2, D3): a tool in a job's grants means
read; "<tool>:write" lets an unattended run change things there. A write
without the write level is a draft: it needs the user's approval, one call
per approval - never a silent change. Destructive operations still need an
approval per call even with the write level."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from src.agent.run_context import JobContext, clear_job_context, set_job_context
from src.agent.tools.permission_check import ApprovalRequiredError, check_autonomous_permission


@pytest.fixture
def run_as(test_database: Any, test_user: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    monkeypatch.setattr("src.agent.tools.permission_check.db", test_database)

    def start(grants: list[str] | None) -> Any:
        agent = test_database.create_standing_chat(
            test_user.id, f"Job {len(grants or [])}", grants=grants
        )
        set_job_context(
            JobContext(item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id])
        )
        return agent

    yield start
    clear_job_context()


def test_read_grant_allows_reads_only(run_as: Any) -> None:
    run_as(["todoist"])

    check_autonomous_permission("todoist", {"operation": "list_tasks"})
    with pytest.raises(ApprovalRequiredError, match="request_approval"):
        check_autonomous_permission("todoist", {"operation": "add_task"})


def test_write_grant_allows_writes_but_not_silent_deletes(run_as: Any) -> None:
    run_as(["todoist", "todoist:write"])

    check_autonomous_permission("todoist", {"operation": "add_task"})
    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("todoist", {"operation": "delete_task"})


def test_all_tools_grant_writes(run_as: Any) -> None:
    run_as(None)

    check_autonomous_permission("google_calendar", {"operation": "create_event"})


def test_write_without_write_grant_files_approval(
    run_as: Any, test_database: Any, test_user: Any
) -> None:
    agent = run_as(["garmin_workout"])
    approval = test_database.create_approval_request(
        agent.id, test_user.id, "garmin_workout", {"operation": "add_block"}, "Add a tempo block"
    )
    test_database.resolve_approval(approval.id, test_user.id, approved=True)

    check_autonomous_permission("garmin_workout", {"action": "add_block"})  # the approved draft
    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("garmin_workout", {"action": "add_block"})


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
        pytest.raises(ApprovalRequiredError),
    ):
        garmin_workout.invoke({"action": "update", "workout_id": "1", "edits": "[]"})
    client.assert_not_called()


def test_rouvy_write_needs_approval_through_the_tool(run_as: Any) -> None:
    from unittest.mock import patch

    from src.agent.tools.rouvy import rouvy_workout

    run_as(["rouvy_workout"])
    with (
        patch("src.agent.tools.rouvy._write_workout") as write,
        pytest.raises(ApprovalRequiredError),
    ):
        rouvy_workout.invoke({"action": "create", "content": "x", "name": "Tempo"})
    write.assert_not_called()


def test_rouvy_delete_is_destructive_even_with_write(run_as: Any) -> None:
    run_as(["rouvy_workout", "rouvy_workout:write"])

    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("rouvy_workout", {"action": "delete", "workout_id": 7})


def test_a_write_approval_authorizes_only_its_operation(
    run_as: Any, test_database: Any, test_user: Any
) -> None:
    agent = run_as(["todoist"])
    approval = test_database.create_approval_request(
        agent.id, test_user.id, "todoist", {"operation": "add_task"}, "Add 'Buy milk'"
    )
    test_database.resolve_approval(approval.id, test_user.id, approved=True)

    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("todoist", {"operation": "update_project", "project_id": "p"})
    check_autonomous_permission("todoist", {"operation": "add_task"})


def test_a_write_approval_cannot_authorize_a_delete(
    run_as: Any, test_database: Any, test_user: Any
) -> None:
    agent = run_as(None)
    approval = test_database.create_approval_request(
        agent.id, test_user.id, "todoist", {"operation": "add_task"}, "Add 'Buy milk'"
    )
    test_database.resolve_approval(approval.id, test_user.id, approved=True)

    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("todoist", {"operation": "delete_project", "project_id": "w"})


def test_request_approval_names_its_tool_and_records_the_operation(
    run_as: Any, test_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from src.agent.tools.request_approval import ApprovalRequestedException, request_approval

    monkeypatch.setattr(
        importlib.import_module("src.agent.tools.request_approval"), "db", test_database
    )
    agent = run_as(["todoist"])

    with pytest.raises(ApprovalRequestedException) as raised:
        request_approval.func(  # type: ignore[attr-defined]
            action_description="Add 'Buy milk'", tool_name="todoist", operation="add_task"
        )

    assert raised.value.tool_name == "todoist"  # the chat's card shows it (Always allow)
    approval = test_database.get_approval_request(raised.value.approval_id, agent.user_id)
    assert approval is not None and approval.tool_args["operation"] == "add_task"


def test_request_approval_cannot_pose_as_a_settings_change(
    run_as: Any, test_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from src.agent.tools.request_approval import request_approval

    monkeypatch.setattr(
        importlib.import_module("src.agent.tools.request_approval"), "db", test_database
    )
    run_as(["todoist"])

    result = request_approval.func(  # type: ignore[attr-defined]
        action_description="Harmless", tool_name="edit_standing_chat"
    )

    assert "edit_standing_chat" in result and "error" in result
