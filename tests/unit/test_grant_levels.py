"""Grant levels (standing chats phase 2, D3): a tool in a job's grants means
read; "<tool>:write" lets an unattended run change things there. A write
without the write level is a draft: it needs the user's approval, one call
per approval - never a silent change. Destructive operations still need an
approval per call even with the write level."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from src.agent.executor import AgentContext, clear_agent_context, set_agent_context
from src.agent.tools.permission_check import ApprovalRequiredError, check_autonomous_permission


@pytest.fixture
def run_as(test_database: Any, test_user: Any, monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    monkeypatch.setattr("src.agent.tools.permission_check.db", test_database)

    def start(grants: list[str] | None) -> Any:
        agent = test_database.create_agent(
            test_user.id, f"Job {len(grants or [])}", tool_permissions=grants
        )
        set_agent_context(AgentContext(agent=agent, user=test_user, trigger_chain=[agent.id]))
        return agent

    yield start
    clear_agent_context()


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
        agent.id, test_user.id, "garmin_workout", None, "Add a tempo block"
    )
    test_database.resolve_approval(approval.id, test_user.id, approved=True)

    check_autonomous_permission("garmin_workout", {"action": "add_block"})  # the approved draft
    with pytest.raises(ApprovalRequiredError):
        check_autonomous_permission("garmin_workout", {"action": "add_block"})


def test_write_level_alone_permits_the_tool(run_as: Any) -> None:
    run_as(["rouvy_workout:write"])

    check_autonomous_permission("rouvy_workout", {"action": "create"})


def test_editor_save_keeps_write_levels(test_database: Any, test_user: Any) -> None:
    """The agent editor knows tool names, not levels: saving must not drop them."""
    agent = test_database.create_agent(
        test_user.id, "Coach", tool_permissions=["todoist", "todoist:write", "garmin_workout"]
    )

    test_database.update_agent(agent.id, test_user.id, tool_permissions=["todoist", "web_search"])

    job = test_database.get_item(agent.id, test_user.id)
    assert sorted(job.grants) == ["todoist", "todoist:write", "web_search"]


def test_agent_response_lists_tool_names(test_database: Any, test_user: Any) -> None:
    from src.api.helpers.agent_responses import agent_to_response

    agent = test_database.create_agent(
        test_user.id, "Coach", tool_permissions=["todoist", "todoist:write"]
    )

    response = agent_to_response(agent)

    assert response["tool_permissions"] == ["todoist"]
