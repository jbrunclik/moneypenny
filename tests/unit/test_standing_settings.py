"""An agent edits its own settings (edit_standing_chat), never silently.

In conversation it previews, and the change applies only on the user's yes in
a later turn - the schedule tool's gate. In an unattended run it files an
approval request; nothing changes until the user approves. Grants never widen
without one of those two. Standing chats phase 2, Part D (D1).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.standing_settings import PENDING_NAMESPACE, edit_standing_chat
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Agent, Database, User


@pytest.fixture
def agent(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[Agent]:
    import src.agent.tools.pending_gate as gate
    import src.agent.tools.standing_settings as module
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(gate, "db", test_database)
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


def _user_says_yes(db: Database, agent: Agent) -> None:
    from src.agent.tool_results import set_current_request_id

    db.add_message(agent.conversation_id or "", MessageRole.USER, "Yes, do it")
    set_current_request_id("request-2")


def test_chat_settings_change_needs_later_yes(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    preview = _call(instructions="Coach my rides and check the weather first.")

    assert "PREVIEW" in preview
    unchanged = test_database.get_standing_chat(agent.id, test_user.id)
    assert unchanged is not None and unchanged.instructions == "Coach my rides"

    _user_says_yes(test_database, agent)
    applied = _call(confirm=True)

    assert "Updated" in applied
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.instructions == "Coach my rides and check the weather first."


def test_same_turn_confirm_refused(agent: Agent, test_database: Database, test_user: User) -> None:
    _call(schedule="0 6 * * *")

    refused = _call(confirm=True)

    assert "not answered" in refused
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.schedule == "0 20 * * *"


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

    approval = test_database.get_approval_request(raised.value.approval_id, test_user.id)
    assert approval is not None and approval.tool_name == "edit_standing_chat"
    assert approval.tool_args == {"schedule": "0 8 * * 1"}
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.schedule == "0 20 * * *"


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
    import src.agent.tools.pending_gate as gate
    import src.agent.tools.standing_settings as module
    from src.agent.daily_briefing import SYSTEM_TYPE_DAILY_BRIEFING
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(gate, "db", test_database)
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
        _user_says_yes(test_database, briefing)
        _call(confirm=True)
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


def test_pending_namespace_is_reserved() -> None:
    from src.agent.tools.agent_kv import RESERVED_NAMESPACES

    assert PENDING_NAMESPACE in RESERVED_NAMESPACES


def test_the_pending_change_is_stored_as_json(
    agent: Agent, test_database: Database, test_user: User
) -> None:
    _call(budget_usd=0.25)

    raw = test_database.kv_get(test_user.id, PENDING_NAMESPACE, agent.conversation_id or "")
    assert raw is not None and json.loads(raw)["changes"] == {"budget_usd": 0.25}


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
    """Only the user's next message answers a preview: a confirm days later
    (e.g. from a page the agent read) must not apply it."""
    from src.agent.tool_results import set_current_request_id

    _call(grants=["*"])
    test_database.add_message(agent.conversation_id or "", MessageRole.USER, "No, never mind.")
    test_database.add_message(
        agent.conversation_id or "", MessageRole.USER, "Read this page for me"
    )
    set_current_request_id("request-3")

    refused = _call(confirm=True)

    assert "expired" in refused
    after = test_database.get_standing_chat(agent.id, test_user.id)
    assert after is not None and after.grants == ["garmin_connect"]
    assert (
        test_database.kv_get(test_user.id, PENDING_NAMESPACE, agent.conversation_id or "") is None
    )


def test_preview_shows_widening_from_no_tools(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.agent.tools.pending_gate as gate
    import src.agent.tools.standing_settings as module
    from src.agent.tool_results import set_current_request_id

    monkeypatch.setattr(module, "db", test_database)
    monkeypatch.setattr(gate, "db", test_database)
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
