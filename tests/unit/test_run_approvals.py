"""A run's card: parked under the waiting message, answered once, and the
answer resumes or ends exactly that run (docs/features/proposals.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from src.agent.proposals import resolve
from src.agent.run_context import (
    JobContext,
    clear_job_context,
    record_approval_request,
    set_job_context,
)
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import use_database

if TYPE_CHECKING:
    from src.db.models import Database, Proposal, User


@pytest.fixture
def run(test_database: Database, test_user: User) -> Iterator[tuple[Any, JobContext]]:
    with (
        use_database(test_database),
        patch("src.agent.run_context.send_push_to_user"),
    ):
        agent = test_database.create_standing_chat(test_user.id, "Coach", grants=["todoist"])
        context = JobContext(
            item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id]
        )
        set_job_context(context)
        yield agent, context
        clear_job_context()


def _park(db: Database, context: JobContext, args: dict[str, Any]) -> Proposal:
    """The run makes a gated call and is parked on its card."""
    execution = db.create_execution(context.item.id, "scheduled")
    with pytest.raises(ApprovalRequestedException) as raised:
        check_autonomous_permission("todoist", args)
    record_approval_request(raised.value, context, context.item.conversation_id or "", execution.id)
    card = db.get_proposal(raised.value.approval_id, context.user.id)
    assert card is not None
    return card


def test_a_parked_run_shows_its_card_under_the_waiting_message(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run

    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    [message] = test_database.get_messages(agent.conversation_id)
    assert card.message_id == message.id and card.execution_id is not None
    assert message.content.startswith("**Waiting for your approval**")
    assert "[approval-request:" not in message.content


def test_approving_resumes_that_run_with_the_call_to_reissue(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume") as resume:
        done = resolve(card, 0, "button")

    assert done.state == "approved"
    [_, note] = test_database.get_messages(agent.conversation_id)
    assert note.content == "[Action approved: Todoist: add task]"
    resume.assert_called_once()
    assert '"content": "Buy milk"' in resume.call_args.args[1]
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "completed"


def test_the_resume_is_an_approval_run(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """It runs (and reports, with a push) as a resume, not a hand-started run."""
    _agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with (
        patch("src.agent.item_scheduler.run_job_now") as run_now,
        patch("src.agent.run_approvals.threading.Thread") as thread,
    ):
        resolve(card, 0, "button")
        thread.call_args.kwargs["target"]()

    assert run_now.call_args.kwargs["trigger"] == "approval"


def test_always_allow_grants_the_write_level(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume"):
        resolve(card, 1, "button")

    job = test_database.get_item(agent.id, agent.user_id)
    assert job is not None and "todoist:write" in (job.grants or [])


def test_always_allow_never_covers_a_destructive_call(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """After Always allow, writes pass without a card; a delete still asks."""
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})
    with patch("src.agent.run_approvals._resume"):
        resolve(card, 1, "button")
    job = test_database.get_item(agent.id, agent.user_id)
    assert job is not None
    set_job_context(JobContext(item=job, user=context.user, name=agent.name, trigger_chain=[]))

    check_autonomous_permission("todoist", {"operation": "add_task", "content": "Eggs"})
    with pytest.raises(ApprovalRequestedException):
        check_autonomous_permission("todoist", {"operation": "delete_task", "task_id": "t1"})


def test_a_typed_yes_approves_a_card_that_also_offers_always_allow(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """Yes means Approve (the extra option is picked by its number or label)."""
    from src.agent.proposals import answer_typed

    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})
    assert len(card.options) == 2

    with patch("src.agent.run_approvals._resume"):
        [answered] = answer_typed(agent.conversation_id, "yes")

    assert (answered.id, answered.state, answered.chosen) == (card.id, "approved", 0)


def test_declining_ends_the_run(run: tuple[Any, JobContext], test_database: Database) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume") as resume:
        resolve(card, None, "button")

    resume.assert_not_called()
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "rejected"
    assert test_database.get_messages(agent.conversation_id)[-1].content.startswith(
        "[Action rejected:"
    )


def test_two_paused_runs_each_resume_their_own(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    _agent, context = run
    first = _park(test_database, context, {"operation": "add_task", "content": "A"})
    second = _park(test_database, context, {"operation": "add_task", "content": "B"})

    with patch("src.agent.run_approvals._resume"):
        resolve(second, 0, "button")

    runs = {r.id: r.status for r in test_database.get_job_runs(context.item.id)}
    assert runs[second.execution_id or ""] == "completed"
    assert runs[first.execution_id or ""] == "waiting_approval"


def test_an_unanswered_card_expires_and_closes_its_run(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    from datetime import timedelta

    from src.agent.run_approvals import expire_stale_run_cards
    from src.utils.clock import utc_now

    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    assert expire_stale_run_cards(utc_now() + timedelta(hours=25)) == 1

    expired = test_database.get_proposal(card.id, card.user_id)
    assert expired is not None and expired.state == "expired"
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "failed" and "approval" in (execution.error_message or "")


def test_the_real_tool_signs_its_full_arguments(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """The card shows - and the approval binds - what the call would really
    do, through the tool itself (not a hand-made dict)."""
    from src.agent.tools.todoist import todoist

    _agent, context = run
    connected = patch("src.agent.tools.todoist.todoist_client.get_todoist_token", return_value="t")
    with connected, pytest.raises(ApprovalRequestedException) as raised:
        todoist.invoke({"action": "add_task", "content": "Buy milk", "due_string": "tomorrow"})
    card = test_database.get_proposal(raised.value.approval_id, context.user.id)
    assert card is not None
    assert card.details == {"Content": "Buy milk", "Due string": "tomorrow"}
    test_database.claim_proposal(card.id, "approved", 0, "button")

    # Other text is another call: it asks again instead of spending the yes
    with connected, pytest.raises(ApprovalRequestedException):
        todoist.invoke({"action": "add_task", "content": "Buy beer", "due_string": "tomorrow"})


def _round_with_two_gated_calls(test_database: Database, test_user: User) -> tuple[Any, Any]:
    """An agent's round makes two gated Todoist calls and one free call;
    the run is parked on what the round filed."""
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, StateGraph

    from src.agent.graph_state import AgentState
    from src.agent.tool_node import create_tool_node
    from src.agent.tools.permission_check import call_arguments

    @tool
    def todoist(action: str, content: str) -> str:
        """Change Todoist."""
        check_autonomous_permission("todoist", call_arguments(todoist, locals()))
        return "done"

    @tool
    def echo(text: str) -> str:
        """Echo."""
        return f"echo: {text}"

    agent = test_database.create_standing_chat(test_user.id, "Pair", grants=["todoist", "echo"])
    context = JobContext(item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id])
    set_job_context(context)
    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("tools", create_tool_node([todoist, echo], is_autonomous=True))
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    calls = [
        {"name": "todoist", "args": {"action": "add_task", "content": "A"}, "id": "c1"},
        {"name": "todoist", "args": {"action": "add_task", "content": "B"}, "id": "c2"},
        {"name": "echo", "args": {"text": "hi"}, "id": "c3"},
    ]
    execution = test_database.create_execution(agent.id, "scheduled")
    with pytest.raises(ApprovalRequestedException) as raised:
        graph.compile().invoke({"messages": [AIMessage(content="", tool_calls=calls)]})
    record_approval_request(raised.value, context, agent.conversation_id or "", execution.id)
    return agent, raised.value


def test_two_gated_calls_in_one_round_park_the_run_on_both_cards(
    run: tuple[Any, JobContext], test_database: Database, test_user: User
) -> None:
    agent, paused = _round_with_two_gated_calls(test_database, test_user)

    cards = test_database.pending_run_proposals(test_user.id)
    mine = [c for c in cards if c.job_id == agent.id]
    [waiting] = test_database.get_messages(agent.conversation_id)
    assert sorted(c.details["Content"] for c in mine) == ["A", "B"]
    assert {c.message_id for c in mine} == {waiting.id}
    assert len({c.execution_id for c in mine}) == 1
    assert ("echo", "echo: hi") in paused.sibling_results


def test_the_run_resumes_once_every_card_is_answered_with_all_approved_calls(
    run: tuple[Any, JobContext], test_database: Database, test_user: User
) -> None:
    agent, _ = _round_with_two_gated_calls(test_database, test_user)
    first, second = [
        c for c in test_database.pending_run_proposals(test_user.id) if c.job_id == agent.id
    ]

    with patch("src.agent.run_approvals._resume") as resume:
        resolve(first, 0, "button")
        resume.assert_not_called()
        resolve(second, 0, "button")

    resume.assert_called_once()
    message = resume.call_args.args[1]
    assert '"content": "A"' in message and '"content": "B"' in message


def test_the_stored_note_is_neutral(run: tuple[Any, JobContext], test_database: Database) -> None:
    """The chat keeps a plain note; the call to re-issue goes only to the resumed run."""
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume"):
        resolve(card, 0, "button")

    note = test_database.get_messages(agent.conversation_id)[-1]
    assert note.content == "[Action approved: Todoist: add task]"


def test_a_resumed_run_may_make_the_call_while_the_card_still_applies(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """The resume can start before the card is marked approved."""
    _agent, context = run
    call = {"operation": "add_task", "content": "Buy milk"}
    card = _park(test_database, context, call)
    test_database.claim_proposal(card.id, "applying", 0, "button")

    check_autonomous_permission("todoist", call)


def test_a_typed_answer_answers_only_the_latest_reply(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    """A run card under an older message waits for its button."""
    from src.agent.proposals import answer_typed

    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})
    test_database.add_message(agent.conversation_id, "user", "How was the run?")
    test_database.add_message(agent.conversation_id, "assistant", "Fine, waiting on you.")

    with patch("src.agent.run_approvals._resume"):
        assert answer_typed(agent.conversation_id, "1") == []

    still = test_database.get_proposal(card.id, card.user_id)
    assert still is not None and still.state == "pending"


def test_an_expired_card_cannot_be_answered_by_typing(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    from datetime import timedelta

    from src.agent.proposals import answer_typed
    from src.db.models.timestamps import to_db
    from src.utils.clock import utc_now

    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})
    test_database._write(
        "UPDATE proposals SET expires_at = ? WHERE id = ?",
        (to_db(utc_now() - timedelta(minutes=1)), card.id),
    )

    with patch("src.agent.run_approvals._resume") as resume:
        assert answer_typed(agent.conversation_id, "1") == []
    resume.assert_not_called()
