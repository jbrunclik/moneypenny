"""Approving or rejecting an agent's request (POST /api/approvals/<id>/...).

Agents run unattended; the approval is the one moment a person steps in, so
the paused run must be closed, the decision recorded in the agent's
conversation and, on approval, the agent resumed - even when it then fails.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask.testing import FlaskClient

from src.api.routes import agent_approvals
from src.db.models import Database, User
from src.db.models.dataclasses import Agent, ApprovalRequest


@pytest.fixture
def resume(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """The faked execute_agent the approve route resumes the agent with."""
    fake = MagicMock(return_value=(True, None))
    monkeypatch.setattr(agent_approvals, "execute_agent", fake)
    yield fake


@pytest.fixture
def paused(test_database: Database, test_user: User) -> tuple[Agent, ApprovalRequest, str]:
    """An agent whose run paused for approval: (agent, approval, paused execution id)."""
    agent = test_database.create_agent(test_user.id, "Mailer")
    execution = test_database.create_execution(agent.id, "scheduled")
    test_database.update_execution(execution.id, status="waiting_approval")
    approval = test_database.create_approval_request(
        agent.id, test_user.id, "send_email", {"to": "x"}, "Send the weekly summary"
    )
    return agent, approval, execution.id


def _executions(db: Database, agent: Agent) -> dict[str, Any]:
    return {e.id: e for e in db.get_agent_executions(agent.id, limit=10)}


def _last_message(db: Database, agent: Agent) -> str:
    assert agent.conversation_id
    return db.get_messages(agent.conversation_id)[-1].content


class TestApprove:
    def test_resumes_the_agent_and_closes_the_paused_run(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        agent, approval, paused_id = paused
        response = client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"status": "approved"}

        assert resume.call_args.args[0].id == agent.id
        assert _last_message(test_database, agent) == "[Action approved: Send the weekly summary]"
        executions = _executions(test_database, agent)
        assert executions[paused_id].status == "completed"  # superseded by the resumed run
        resumed = [e for i, e in executions.items() if i != paused_id]
        assert [e.status for e in resumed] == ["completed"]
        assert test_database.get_pending_approvals(agent.user_id) == []

    def test_a_failing_resumed_run_is_recorded(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        agent, approval, paused_id = paused
        resume.return_value = (False, "Mail server refused")
        assert (
            client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers).status_code
            == 200
        )
        resumed = [e for i, e in _executions(test_database, agent).items() if i != paused_id]
        assert [(e.status, e.error_message) for e in resumed] == [("failed", "Mail server refused")]

    def test_a_crashing_resumed_run_is_recorded_not_left_running(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        agent, approval, paused_id = paused
        resume.side_effect = RuntimeError("model unavailable")
        response = client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers)
        assert response.status_code == 200  # the approval itself went through
        resumed = [e for i, e in _executions(test_database, agent).items() if i != paused_id]
        assert [e.status for e in resumed] == ["failed"]

    def test_approving_twice_finds_nothing_the_second_time(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        _, approval, _ = paused
        client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers)
        second = client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers)
        assert second.status_code == 404
        assert resume.call_count == 1

    def test_another_users_approval_is_not_found(
        self,
        client: FlaskClient,
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        from src.auth.jwt_auth import create_token

        _, approval, _ = paused
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        headers = {"Authorization": f"Bearer {create_token(other)}"}
        assert (
            client.post(f"/api/approvals/{approval.id}/approve", headers=headers).status_code == 404
        )
        resume.assert_not_called()


class TestReject:
    def test_records_the_rejection_and_closes_the_paused_run(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
        resume: MagicMock,
    ) -> None:
        agent, approval, paused_id = paused
        response = client.post(f"/api/approvals/{approval.id}/reject", headers=auth_headers)
        assert response.get_json() == {"status": "rejected"}
        assert _last_message(test_database, agent) == "[Action rejected: Send the weekly summary]"
        execution = _executions(test_database, agent)[paused_id]
        assert (execution.status, execution.error_message) == ("failed", "Action rejected by user")
        resume.assert_not_called()

    def test_another_users_approval_is_not_found(
        self,
        client: FlaskClient,
        test_database: Database,
        paused: tuple[Agent, ApprovalRequest, str],
    ) -> None:
        from src.auth.jwt_auth import create_token

        _, approval, _ = paused
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        headers = {"Authorization": f"Bearer {create_token(other)}"}
        assert (
            client.post(f"/api/approvals/{approval.id}/reject", headers=headers).status_code == 404
        )


class TestStandingJobApprovals:
    """A standing job's run that paused for approval (phase 2 plan, A4): its
    approval names the job, and approving resumes the job's run."""

    @pytest.fixture
    def job_paused(self, test_database: Database, test_user: User) -> tuple[Any, ApprovalRequest]:
        import uuid
        from datetime import UTC, datetime

        from src.db.models.dataclasses import ScheduledItem

        conv = test_database.create_conversation(test_user.id, "Coach")
        now = datetime.now(UTC)
        job = test_database.add_item(
            ScheduledItem(
                id=str(uuid.uuid4()),
                user_id=test_user.id,
                conversation_id=conv.id,
                kind="recurring",
                text="Plan tomorrow's ride.",
                end_condition=None,
                schedule="0 20 * * *",
                interval_hours=None,
                next_run_at=now,
                expires_at=None,
                status="active",
                last_result=None,
                quiet_runs=0,
                failures=0,
                created_at=now,
                grants=["todoist"],
            )
        )
        execution = test_database.create_execution(job.id, "scheduled")
        test_database.update_execution(execution.id, status="waiting_approval")
        approval = test_database.create_approval_request(
            job.id, test_user.id, "todoist", None, "Delete the old ride task"
        )
        return job, approval

    def test_approving_a_job_request_resumes_the_job(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        job_paused: tuple[Any, ApprovalRequest],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        job, approval = job_paused
        resumed: list[tuple[str, str | None]] = []

        def run_job_now(item: Any, user: User, *, message: str | None = None) -> Any:
            resumed.append((item.id, message))

        monkeypatch.setattr(agent_approvals, "run_job_now", run_job_now)

        response = client.post(f"/api/approvals/{approval.id}/approve", headers=auth_headers)

        assert response.status_code == 200
        assert resumed == [(job.id, "[Action approved: Delete the old ride task]")]
        [paused_run] = test_database.get_agent_executions(job.id)
        assert paused_run.status == "completed"
        last = test_database.get_messages(job.conversation_id)[-1]
        assert last.content == "[Action approved: Delete the old ride task]"

    def test_rejecting_a_job_request_is_recorded_in_its_chat(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        job_paused: tuple[Any, ApprovalRequest],
    ) -> None:
        job, approval = job_paused

        response = client.post(f"/api/approvals/{approval.id}/reject", headers=auth_headers)

        assert response.status_code == 200
        last = test_database.get_messages(job.conversation_id)[-1]
        assert last.content == "[Action rejected: Delete the old ride task]"
        [paused_run] = test_database.get_agent_executions(job.id)
        assert paused_run.status == "failed"
