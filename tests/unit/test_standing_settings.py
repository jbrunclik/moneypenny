"""An agent edits its own settings (edit_standing_chat), never silently.

In conversation it files a proposal card, and the server applies the change
only when the user approves it (docs/features/proposals.md). In an unattended run it files an
approval request; nothing changes until the user approves. Grants never widen
without one of those two. Standing chats phase 2, Part D (D1).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.proposals import answer_typed, resolve
from src.agent.tools.context import set_conversation_context
from src.agent.tools.standing_settings import edit_standing_chat
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Agent, Database, User


@pytest.fixture
def agent(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[Agent]:
    import src.agent.proposals as proposals_module
    import src.agent.tools.standing_settings as module
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(proposals_module, "db", test_database)
    monkeypatch.setattr("src.agent.run_approvals.db", test_database)
    agent = test_database.create_standing_chat(
        test_user.id,
        "Coach",
        instructions="Coach my rides",
        schedule="0 20 * * *",
        grants=["garmin_connect"],
    )
    set_conversation_context(agent.conversation_id, test_user.id)
    set_current_request_id("request-1")
    test_database.add_message(agent.conversation_id or "", MessageRole.USER, "Add the weather")
    yield agent
    set_conversation_context(None, None)
    set_current_request_id(None)


def _call(**args: object) -> str:
    return str(edit_standing_chat.invoke(args))


def _approve(db: Database, agent: Agent) -> str:
    """The user approves the chat's latest card; the result line or failure."""
    pending = db.pending_proposals(agent.conversation_id or "")
    return resolve(pending[-1], 0, "button").result or "" if pending else "nothing to approve"


def test_chat_settings_change_needs_later_yes(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    preview = _call(instructions="Coach my rides and check the weather first.")

    assert preview.startswith("PROPOSAL shown to the user as a card (Apply / Not now)")
    unchanged = test_database.get_standing_chat(agent.id, test_user.id)
    assert unchanged is not None and unchanged.instructions == "Coach my rides"

    applied = _approve(test_database, agent)

    assert applied == "Updated Coach."
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.instructions == "Coach my rides and check the weather first."


def test_unattended_settings_change_files_approval(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    from src.agent.run_context import JobContext, clear_job_context, set_job_context
    from src.agent.tools.request_approval import ApprovalRequestedException

    set_job_context(
        JobContext(item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id])
    )
    try:
        with pytest.raises(ApprovalRequestedException) as raised:
            edit_standing_chat.func(schedule="0 8 * * 1")  # type: ignore[attr-defined]
    finally:
        clear_job_context()

    card = test_database.get_proposal(raised.value.approval_id, test_user.id)
    assert card is not None and (card.origin, card.kind) == ("run", "edit_agent")
    assert card.options[0]["payload"] == {"job_id": agent.id, "changes": {"schedule": "0 8 * * 1"}}
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.schedule == "0 20 * * *"

    resolve(card, 0, "button")  # the approved change applies, no rerun

    applied = test_database.get_standing_chat(agent.id, test_user.id)
    assert applied is not None and applied.schedule == "0 8 * * 1"


def test_grants_never_widen_without_approval(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    preview = _call(grants=["garmin_connect", "todoist"])

    assert "todoist" in preview  # the preview names the new access
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.grants == ["garmin_connect"]


def test_unknown_grants_and_bad_cron_are_refused(agent: Agent) -> None:
    assert "unknown" in _call(grants=["root_shell"]).lower()
    assert "cron" in _call(schedule="every tuesday").lower()


def test_briefing_edit_freezes_a_copy(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.agent.proposals as proposals_module
    import src.agent.tools.standing_settings as module
    from src.agent.daily_briefing import SYSTEM_TYPE_DAILY_BRIEFING
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(proposals_module, "db", test_database)
    monkeypatch.setattr("src.agent.run_approvals.db", test_database)
    briefing = test_database.create_standing_chat(
        test_user.id,
        "Daily Briefing",
        schedule="15 7 * * *",
        standing_type=SYSTEM_TYPE_DAILY_BRIEFING,
    )
    conv_id = briefing.conversation_id or ""
    set_conversation_context(conv_id, test_user.id)
    set_current_request_id("r1")
    test_database.add_message(conv_id, MessageRole.USER, "Add the weather")
    try:
        preview = _call(instructions="Briefing plus the weather.")
        assert "your own copy" in preview
        _approve(test_database, briefing)
    finally:
        set_conversation_context(None, None)
        set_current_request_id(None)

    conv = test_database.get_conversation(conv_id, test_user.id)
    assert conv is not None
    assert (conv.standing_instructions, conv.standing_type) == (
        "Briefing plus the weather.",
        SYSTEM_TYPE_DAILY_BRIEFING,
    )


def test_refused_in_a_chat_without_an_agent(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.agent.tools.standing_settings as module

    monkeypatch.setattr(module, "db", test_database)
    conv = test_database.create_conversation(test_user.id, "Plain")
    set_conversation_context(conv.id, test_user.id)
    try:
        assert "no agent" in _call(instructions="x").lower()
    finally:
        set_conversation_context(None, None)


def test_the_card_carries_exactly_the_change(agent: Agent, test_database: Database) -> None:
    _call(budget_usd=0.25)

    [card] = test_database.pending_proposals(agent.conversation_id or "")
    assert card.options[0]["payload"] == {"job_id": agent.id, "changes": {"budget_usd": 0.25}}
    assert "Daily budget: $0.25" in str(card.details["Changes"])


def test_deleting_the_agent_takes_its_card(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    """The agent's chat goes with it, and the card with the chat: nothing is
    left to approve for an agent that no longer exists."""
    _call(budget_usd=0.25)
    test_database.delete_standing_chat(agent.id, test_user.id)

    assert test_database.pending_proposals(agent.conversation_id or "") == []


def test_bound_in_standing_chats_only() -> None:
    from src.agent.tools import get_tools_for_request

    standing = {t.name for t in get_tools_for_request(False, False, standing=True)}
    ordinary = {t.name for t in get_tools_for_request(False, False, standing=False)}

    assert "edit_standing_chat" in standing
    assert "edit_standing_chat" not in ordinary


# Part D review


def test_a_preview_answered_with_something_else_expires(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    """Only the user's next message answers a card: anything else expires it,
    so nothing later (e.g. a page the agent read) can apply it."""
    conv_id = agent.conversation_id or ""
    _call(grants=["*"])
    reply = test_database.add_message(conv_id, MessageRole.ASSISTANT, "Shall I?")
    test_database.link_proposals("request-1", reply.id)

    assert answer_typed(conv_id, "Read this page for me") == []

    assert test_database.pending_proposals(conv_id) == []
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.grants == ["garmin_connect"]


def test_preview_shows_widening_from_no_tools(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.agent.proposals as proposals_module
    import src.agent.tools.standing_settings as module
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(proposals_module, "db", test_database)
    monkeypatch.setattr("src.agent.run_approvals.db", test_database)
    bare = test_database.create_standing_chat(test_user.id, "Bare", grants=[])
    set_conversation_context(bare.conversation_id, test_user.id)
    set_current_request_id("r1")
    try:
        preview = _call(grants=["*"])
    finally:
        set_conversation_context(None, None)
        set_current_request_id(None)

    assert "new access: all tools" in preview


@pytest.mark.parametrize("grant", ["schedule", "edit_standing_chat", "web_search:write"])
def test_ungrantable_tools_are_refused(agent: Agent, grant: str) -> None:
    assert "unknown" in _call(grants=[grant]).lower()
