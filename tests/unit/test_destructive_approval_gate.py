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
