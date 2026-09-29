"""Tests for autonomous agent execution (src/agent/executor.py).

The LLM seam (ChatAgent) and the push sender are faked; everything else -
the database, trigger message, history, cost recording, execution records
and the agent context - runs for real against an isolated test database.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.executor import (
    AgentBlockedError,
    AgentContext,
    AgentExecutor,
    clear_agent_context,
    execute_agent,
    get_agent_context,
    get_trigger_chain,
    set_agent_context,
)
from src.agent.tools.request_approval import ApprovalRequestedException
from src.api.schemas.common import MessageRole
from src.db.models import Agent, Database, User, use_database

USAGE = {"input_tokens": 1200, "output_tokens": 300}


class FakeChatAgent:
    """Stands in for ChatAgent: records how it was built and called."""

    instances: list[FakeChatAgent] = []
    response: str = "Report ready\nSecond line with details"
    error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.chat_kwargs: dict[str, Any] = {}
        self.context_during_call: AgentContext | None = None
        FakeChatAgent.instances.append(self)

    def chat_batch(self, **kwargs: Any) -> tuple[str, list[Any], dict[str, int], list[Any]]:
        self.chat_kwargs = kwargs
        self.context_during_call = get_agent_context()
        if FakeChatAgent.error is not None:
            raise FakeChatAgent.error
        return FakeChatAgent.response, [], dict(USAGE), []


@pytest.fixture
def db(test_database: Database) -> Generator[Database]:
    with use_database(test_database):
        yield test_database


@pytest.fixture
def fake_llm() -> Generator[type[FakeChatAgent]]:
    FakeChatAgent.instances = []
    FakeChatAgent.response = "Report ready\nSecond line with details"
    FakeChatAgent.error = None
    with patch("src.agent.executor.ChatAgent", FakeChatAgent):
        yield FakeChatAgent


@pytest.fixture
def push() -> Generator[MagicMock]:
    with patch("src.agent.executor.send_push_to_user") as mock:
        yield mock


@pytest.fixture
def user(db: Database) -> User:
    return db.get_or_create_user(email="agent-owner@example.com", name="Owner", picture=None)


def _agent(db: Database, user: User, **overrides: Any) -> Agent:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "name": "Reporter",
        "system_prompt": "Summarize the news.",
        "schedule": "0 9 * * *",
        "tool_permissions": [],
    }
    fields.update(overrides)
    return db.create_agent(**fields)


def _run(db: Database, agent: Agent, user: User, trigger: str = "scheduled") -> tuple[Any, Any]:
    execution = db.create_execution(agent_id=agent.id, trigger_type=trigger)
    return execute_agent(agent, user, trigger, execution.id)


class TestExecuteAgentSuccess:
    def test_saves_trigger_and_response_and_records_cost(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        result = _run(db, agent, user)

        assert result == (True, None)
        messages = db.get_messages(agent.conversation_id or "")
        assert [m.role for m in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
        assert messages[0].content.startswith("[Scheduled run at ")
        assert messages[1].content == "Report ready\nSecond line with details"
        cost = db.get_message_cost(messages[1].id)
        assert cost is not None
        assert cost["input_tokens"] == USAGE["input_tokens"]
        assert cost["output_tokens"] == USAGE["output_tokens"]
        refreshed = db.get_agent(agent.id, user.id)
        assert refreshed is not None and refreshed.last_run_at is not None

    def test_runs_autonomously_with_agent_model_and_context(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        _run(db, agent, user)

        (llm,) = fake_llm.instances
        assert llm.init_kwargs["is_autonomous"] is True
        assert llm.init_kwargs["model_name"] == agent.model
        assert llm.init_kwargs["agent_context"]["name"] == "Reporter"
        assert llm.init_kwargs["agent_context"]["goals"] == "Summarize the news."
        assert llm.init_kwargs["agent_context"]["trigger_type"] == "scheduled"
        # Permission checks see the autonomous context while the model runs...
        assert llm.context_during_call is not None
        assert llm.context_during_call.trigger_chain == [agent.id]
        # ...and it is cleared afterwards
        assert get_agent_context() is None

    def test_scheduled_run_pushes_first_line_tagged_per_agent(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        _run(db, agent, user)

        push.assert_called_once()
        args, kwargs = push.call_args
        assert args == (user.id, "Reporter finished", "Report ready")
        assert kwargs["tag"] == f"agent-{agent.id}"
        assert kwargs["url"] == f"/#/conversations/{agent.conversation_id}"

    def test_push_body_is_truncated(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        fake_llm.response = "x" * 500
        agent = _agent(db, user)

        _run(db, agent, user)

        assert push.call_args.args[2] == "x" * 160

    def test_manual_run_does_not_push(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        assert _run(db, agent, user, trigger="manual") == (True, None)

        push.assert_not_called()

    def test_fresh_context_sends_no_history(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user, fresh_context=True)
        db.add_message(agent.conversation_id or "", MessageRole.ASSISTANT, "Yesterday's report")

        _run(db, agent, user)

        assert fake_llm.instances[0].chat_kwargs["history"] == []

    def test_continuing_context_sends_prior_messages_without_trigger(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user, fresh_context=False)
        conv_id = agent.conversation_id or ""
        db.add_message(conv_id, MessageRole.USER, "[Scheduled run at earlier]")
        db.add_message(conv_id, MessageRole.ASSISTANT, "Yesterday's report")

        _run(db, agent, user)

        history = fake_llm.instances[0].chat_kwargs["history"]
        assert history == [
            {"role": "user", "content": "[Scheduled run at earlier]"},
            {"role": "assistant", "content": "Yesterday's report"},
        ]

    def test_compaction_failure_does_not_block_the_run(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        with patch(
            "src.agent.compaction.compact_conversation", side_effect=RuntimeError("llm down")
        ):
            assert _run(db, agent, user) == (True, None)


class TestExecuteAgentPreflightFailures:
    def test_agent_without_conversation_fails_before_llm(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = replace(_agent(db, user), conversation_id=None)

        ok, error = _run(db, agent, user)

        assert ok is False
        assert error == f"Agent has no conversation: {agent.id}"
        assert fake_llm.instances == []

    def test_missing_conversation_fails(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = replace(_agent(db, user), conversation_id="does-not-exist")

        ok, error = _run(db, agent, user)

        assert ok is False
        assert error == "Agent conversation not found: does-not-exist"
        assert fake_llm.instances == []

    def test_over_budget_agent_is_refused(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user, budget_limit=1.0)
        conv_id = agent.conversation_id or ""
        msg = db.add_message(conv_id, MessageRole.ASSISTANT, "Expensive earlier run")
        db.save_message_cost(msg.id, conv_id, user.id, agent.model, 10, 10, cost_usd=2.5)

        ok, error = _run(db, agent, user)

        assert ok is False
        assert error == "Agent exceeded daily budget limit ($1.00, spent: $2.50)"
        assert fake_llm.instances == []
        # No trigger message was written for a refused run
        assert len(db.get_messages(conv_id)) == 1


class TestExecuteAgentRunFailures:
    def test_approval_request_pauses_the_run(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        fake_llm.error = ApprovalRequestedException("appr-1", "Delete project Old", "todoist")
        agent = _agent(db, user)
        execution = db.create_execution(agent_id=agent.id, trigger_type="scheduled")

        result = execute_agent(agent, user, "scheduled", execution.id)

        assert result == ("waiting_approval", "Delete project Old")
        (latest,) = db.get_agent_executions(agent.id)
        assert latest.status == "waiting_approval"
        last_message = db.get_messages(agent.conversation_id or "")[-1]
        assert last_message.role == MessageRole.ASSISTANT
        assert "appr-1" in last_message.content
        assert "Delete project Old" in last_message.content
        push.assert_called_once()
        assert push.call_args.args[1] == "Reporter needs your approval"
        assert push.call_args.kwargs["tag"] == "approval-appr-1"
        assert get_agent_context() is None

    def test_llm_error_returns_failure_and_clears_context(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        fake_llm.error = RuntimeError("quota exhausted")
        agent = _agent(db, user)

        assert _run(db, agent, user) == (False, "quota exhausted")

        assert get_agent_context() is None
        push.assert_not_called()
        # Only the trigger message was saved
        messages = db.get_messages(agent.conversation_id or "")
        assert [m.role for m in messages] == [MessageRole.USER]


class TestAgentExecutor:
    def test_completed_run_marks_execution_completed(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        agent = _agent(db, user)

        result = AgentExecutor(agent, user, "agent_trigger", "parent-id").run("Focus on AAPL")

        assert result.status == "completed"
        (execution,) = db.get_agent_executions(agent.id)
        assert execution.id == result.execution_id
        assert execution.status == "completed"
        assert execution.triggered_by_agent_id == "parent-id"
        trigger = db.get_messages(agent.conversation_id or "")[0].content
        assert "Message from triggering agent: Focus on AAPL" in trigger

    def test_child_inherits_the_parent_trigger_chain(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        parent = _agent(db, user, name="Parent")
        child = _agent(db, user, name="Child")
        set_agent_context(AgentContext(agent=parent, user=user, trigger_chain=[parent.id]))
        try:
            AgentExecutor(child, user, "agent_trigger", parent.id).run()
        finally:
            clear_agent_context()

        context = fake_llm.instances[0].context_during_call
        assert context is not None
        assert context.trigger_chain == [parent.id, child.id]

    def test_failed_run_raises_and_marks_execution_failed(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        fake_llm.error = RuntimeError("boom")
        agent = _agent(db, user)

        with pytest.raises(AgentBlockedError, match="boom"):
            AgentExecutor(agent, user, "agent_trigger").run()

        (execution,) = db.get_agent_executions(agent.id)
        assert execution.status == "failed"
        assert execution.error_message == "boom"

    def test_approval_raises_but_keeps_waiting_status(
        self, db: Database, user: User, fake_llm: type[FakeChatAgent], push: MagicMock
    ) -> None:
        fake_llm.error = ApprovalRequestedException("appr-2", "Send WhatsApp", "whatsapp")
        agent = _agent(db, user)

        with pytest.raises(AgentBlockedError, match="waiting for approval: Send WhatsApp"):
            AgentExecutor(agent, user, "agent_trigger").run()

        (execution,) = db.get_agent_executions(agent.id)
        assert execution.status == "waiting_approval"


class TestAgentContextHelpers:
    def test_trigger_chain_is_empty_outside_an_execution(self) -> None:
        clear_agent_context()
        assert get_trigger_chain() == []

    def test_trigger_chain_reflects_current_context(self, db: Database, user: User) -> None:
        agent = _agent(db, user)
        set_agent_context(AgentContext(agent=agent, user=user, trigger_chain=["a", agent.id]))
        try:
            assert get_trigger_chain() == ["a", agent.id]
        finally:
            clear_agent_context()
        assert get_agent_context() is None
