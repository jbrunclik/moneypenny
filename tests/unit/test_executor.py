"""The unattended run's shared pieces (src/agent/executor.py): the run context
permission checks read, the trigger message, the run's history and the
approval recorder. Agents run as standing jobs (src/agent/item_runner.py,
tested in test_item_runner.py)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from src.agent.executor import (
    AgentContext,
    build_trigger_message,
    clear_agent_context,
    get_agent_context,
    get_trigger_chain,
    record_approval_request,
    run_history,
    set_agent_context,
)
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import Agent, Database, User, use_database
from src.enums import MessageRole


@pytest.fixture
def db(test_database: Database) -> Generator[Database]:
    with use_database(test_database):
        yield test_database


@pytest.fixture
def user(db: Database) -> User:
    return db.get_or_create_user(email="agent-owner@example.com", name="Owner", picture=None)


def _agent(db: Database, user: User, **overrides: object) -> Agent:
    fields: dict[str, object] = {
        "name": "Reporter",
        "system_prompt": "Summarize the news.",
        "schedule": "0 9 * * *",
        "tool_permissions": [],
    }
    fields.update(overrides)
    return db.create_agent(user.id, **fields)  # type: ignore[arg-type]


class TestAgentContextHelpers:
    def test_trigger_chain_is_empty_outside_a_run(self) -> None:
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


class TestTriggerMessage:
    def test_scheduled_has_timestamp_prefix(self) -> None:
        msg = build_trigger_message("scheduled")
        assert msg.startswith("[Scheduled run at ")
        assert msg.endswith("UTC]")

    def test_unknown_trigger_type_falls_back(self) -> None:
        assert build_trigger_message("webhook") == "[Triggered: webhook]"

    def test_includes_the_triggering_agents_message(self) -> None:
        msg = build_trigger_message("agent_trigger", "Focus on AAPL earnings")
        assert msg.startswith("[Triggered by another agent at ")
        assert "Message from triggering agent: Focus on AAPL earnings" in msg

    @pytest.mark.parametrize("extra", ["Continue", None, "   "])
    def test_ignores_an_empty_or_default_message(self, extra: str | None) -> None:
        # "Continue" is the legacy default of trigger_agent's message arg and
        # means "no message" - it must not be echoed into the trigger message.
        assert "Message from" not in build_trigger_message("agent_trigger", extra)


class TestRunHistory:
    def test_uses_chat_compaction_and_keeps_messages(self, db: Database, user: User) -> None:
        """One non-destructive compaction for runs and chats: a long agent
        conversation is compacted for the model, never deleted."""
        agent = _agent(db, user, fresh_context=False)
        conv_id = agent.conversation_id or ""
        for i in range(30):
            db.add_message(conv_id, MessageRole.USER, f"[Scheduled run {i}]")
            db.add_message(conv_id, MessageRole.ASSISTANT, f"Report {i}")

        with patch(
            "src.agent.executor.build_compacted_history", side_effect=lambda u, c, h: h[-4:]
        ) as compact:
            history = run_history(agent, conv_id, keep_last=True)

        assert compact.call_args.args[:2] == (user.id, conv_id)
        assert len(history) == 4
        assert history[-1]["content"] == "Report 29"
        assert len(db.get_messages(conv_id)) == 60

    def test_drops_the_just_saved_trigger_unless_kept(self, db: Database, user: User) -> None:
        agent = _agent(db, user, fresh_context=False)
        conv_id = agent.conversation_id or ""
        db.add_message(conv_id, MessageRole.ASSISTANT, "Old report")
        db.add_message(conv_id, MessageRole.USER, "[Action approved: X]")

        contents = [h["content"] for h in run_history(agent, conv_id)]

        assert contents == ["Old report"]

    def test_fresh_context_run_has_no_history(self, db: Database, user: User) -> None:
        agent = _agent(db, user, fresh_context=True)
        db.add_message(agent.conversation_id or "", MessageRole.ASSISTANT, "Old report")

        assert run_history(agent, agent.conversation_id or "") == []


def test_an_approval_request_parks_the_run_and_pushes(db: Database, user: User) -> None:
    agent = _agent(db, user)
    execution = db.create_execution(agent.id, "scheduled")
    request = ApprovalRequestedException("ap-1", "Send the summary", "whatsapp")

    with patch("src.agent.executor.send_push_to_user") as push:
        record_approval_request(request, agent, user, agent.conversation_id or "", execution.id)

    [saved] = db.get_agent_executions(agent.id)
    assert saved.status == "waiting_approval"
    assert "[approval-request:ap-1]" in db.get_messages(agent.conversation_id or "")[-1].content
    assert isinstance(push, MagicMock) and push.call_args.kwargs["tag"] == "approval-ap-1"
