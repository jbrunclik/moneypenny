"""Tests for the destructive-action approval gate (S9 hardening).

Delete operations on todoist/google_calendar are enforced at the tool
layer for agent contexts: each requires consuming one approved,
unexpired approval request. Prompt-level confirmation alone is exactly
what prompt injection bypasses.
"""

from __future__ import annotations

import pytest

from src.agent.executor import AgentContext, clear_agent_context, set_agent_context
from src.agent.tools.permission_check import (
    ApprovalRequiredError,
    check_autonomous_permission,
)


@pytest.fixture
def agent_ctx(test_database, test_user, monkeypatch):
    """A real agent set as the current agent context, with db patched."""
    monkeypatch.setattr("src.db.models.db", test_database)
    agent = test_database.create_agent(user_id=test_user.id, name="Gate Test")
    set_agent_context(AgentContext(agent=agent, user=test_user, trigger_chain=[agent.id]))
    yield agent
    clear_agent_context()


class TestDestructiveApprovalGate:
    def test_no_agent_context_allows(self) -> None:
        clear_agent_context()
        # Interactive/plain chat: the user is driving - no gate
        check_autonomous_permission("todoist", {"operation": "delete_task"})

    def test_non_destructive_action_allows(self, agent_ctx) -> None:
        check_autonomous_permission("todoist", {"operation": "add_task"})

    def test_destructive_without_approval_blocked(self, agent_ctx) -> None:
        with pytest.raises(ApprovalRequiredError, match="request_approval"):
            check_autonomous_permission("todoist", {"operation": "delete_task"})

    def test_approved_request_authorizes_exactly_one_call(
        self, agent_ctx, test_database, test_user
    ) -> None:
        approval = test_database.create_approval_request(
            agent_id=agent_ctx.id,
            user_id=test_user.id,
            tool_name="todoist",
            tool_args={"description": "delete task X"},
            description="delete task X",
        )
        test_database.resolve_approval(approval.id, test_user.id, approved=True)

        # First call consumes the approval and passes
        check_autonomous_permission("todoist", {"operation": "delete_task"})
        assert test_database.get_approval_request(approval.id, test_user.id).status == "consumed"

        # Second call has no approval left
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission("todoist", {"operation": "delete_task"})

    def test_rejected_approval_does_not_authorize(
        self, agent_ctx, test_database, test_user
    ) -> None:
        approval = test_database.create_approval_request(
            agent_id=agent_ctx.id,
            user_id=test_user.id,
            tool_name="todoist",
            tool_args=None,
            description="delete everything",
        )
        test_database.resolve_approval(approval.id, test_user.id, approved=False)

        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission("todoist", {"operation": "delete_project"})

    def test_calendar_delete_gated_separately(self, agent_ctx, test_database, test_user) -> None:
        # A todoist approval does not authorize a calendar delete
        approval = test_database.create_approval_request(
            agent_id=agent_ctx.id,
            user_id=test_user.id,
            tool_name="todoist",
            tool_args=None,
            description="delete task",
        )
        test_database.resolve_approval(approval.id, test_user.id, approved=True)

        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission("google_calendar", {"operation": "delete_event"})


def _approve(test_database, agent, user, tool_name="todoist", target_id=None):
    tool_args = {"description": "x"}
    if target_id:
        tool_args["target_id"] = target_id
    approval = test_database.create_approval_request(
        agent_id=agent.id,
        user_id=user.id,
        tool_name=tool_name,
        tool_args=tool_args,
        description="x",
    )
    test_database.resolve_approval(approval.id, user.id, approved=True)
    return approval


class TestArchiveAndRescheduleGates:
    def test_archive_project_gated(self, agent_ctx) -> None:
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission(
                "todoist", {"operation": "archive_project", "project_id": "p1"}
            )

    def test_update_event_reschedule_gated(self, agent_ctx) -> None:
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission(
                "google_calendar",
                {"operation": "update_event", "event_id": "e1", "start_time": "2026-06-13T09:00"},
            )

    def test_update_event_attendee_change_gated(self, agent_ctx) -> None:
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission(
                "google_calendar",
                {"operation": "update_event", "event_id": "e1", "attendees": ["a@b.c"]},
            )

    def test_update_event_cosmetic_edit_allowed(self, agent_ctx) -> None:
        # Renames/description tweaks are reversible and stay ungated
        check_autonomous_permission(
            "google_calendar", {"operation": "update_event", "event_id": "e1"}
        )


class TestTargetMatching:
    def test_targeted_approval_authorizes_only_that_entity(
        self, agent_ctx, test_database, test_user
    ) -> None:
        _approve(test_database, agent_ctx, test_user, target_id="task-X")

        # Wrong entity: the approval for task-X must not be spent on task-Y
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission(
                "todoist", {"operation": "delete_task", "task_id": "task-Y"}
            )

        # Right entity passes and consumes
        check_autonomous_permission("todoist", {"operation": "delete_task", "task_id": "task-X"})
        with pytest.raises(ApprovalRequiredError):
            check_autonomous_permission(
                "todoist", {"operation": "delete_task", "task_id": "task-X"}
            )

    def test_generic_approval_authorizes_any_single_call(
        self, agent_ctx, test_database, test_user
    ) -> None:
        _approve(test_database, agent_ctx, test_user, target_id=None)
        check_autonomous_permission("todoist", {"operation": "delete_task", "task_id": "task-Y"})

    def test_targeted_approval_preferred_over_generic(
        self, agent_ctx, test_database, test_user
    ) -> None:
        generic = _approve(test_database, agent_ctx, test_user, target_id=None)
        targeted = _approve(test_database, agent_ctx, test_user, target_id="task-X")

        check_autonomous_permission("todoist", {"operation": "delete_task", "task_id": "task-X"})

        # The targeted approval was spent; the generic one remains usable
        assert test_database.get_approval_request(targeted.id, test_user.id).status == "consumed"
        assert test_database.get_approval_request(generic.id, test_user.id).status == "approved"
