"""propose_setup_change: the coach proposes a change to its own setup on a card
(docs/superpowers/specs/2026-11-11-program-self-tuning-design.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.proposals import resolve
from src.agent.tool_results import set_current_request_id
from src.agent.tools import program_setup_tool as tool_module
from src.agent.tools.context import set_conversation_context
from src.agent.tools.program_setup_tool import propose_setup_change
from src.db.models import use_database
from src.enums import MessageRole
from src.services import program_setup as ps
from src.services.program_setup import ProgramRef
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal, User

REF = ProgramRef("sports", "cycling")
_NEXT = {
    "id": "next",
    "emoji": "⏭️",
    "label": "Next workout",
    "body": "What is my next workout?",
    "fields": [],
}
_ADD = {
    "target": "quick_action",
    "op": "add",
    "action": {**_NEXT, "id": "plan-week", "label": "Plan week", "body": "Plan my week."},
}


def _today(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


@pytest.fixture
def program_chat(test_database: Database, test_user: User) -> Iterator[Conversation]:
    with use_database(test_database):
        program = {
            "id": "cycling",
            "name": "Cycling",
            "emoji": "🚴",
            "created_at": "2026-11-01",
            "quick_actions": [_NEXT],
        }
        test_database.kv_set(test_user.id, "sports", "programs", json.dumps([program]))
        conv = test_database.get_or_create_program_conversation("sports", test_user.id, "cycling")
        # The day the evidence cites: the user wrote in this chat today
        test_database.add_message(conv.id, MessageRole.USER, "plan my week please")
        set_conversation_context(conv.id, test_user.id)
        set_current_request_id("turn-1")
        yield conv
        set_conversation_context(None, None)
        set_current_request_id(None)


def _propose(change: dict[str, Any] | None = None, evidence: list[str] | None = None) -> str:
    return str(
        propose_setup_change.invoke(
            {
                "change": json.dumps(change if change is not None else _ADD),
                "evidence": evidence
                if evidence is not None
                else [f"{_today()}: 'plan my week please'"],
                "reason": "You ask for a weekly plan every Monday.",
            }
        )
    )


def _card(db: Database, conv: Conversation, request_id: str = "turn-1") -> Proposal:
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "I have a suggestion.")
    db.link_proposals(request_id, reply.id)
    [card] = db.pending_proposals(conv.id)
    return card


class TestToolSchema:
    def test_every_param_has_a_concrete_type(self) -> None:
        for name, schema in propose_setup_change.args.items():
            assert "type" in schema or "anyOf" in schema, name
        assert propose_setup_change.args["evidence"]["items"]["type"] == "string"


def test_files_a_card_with_before_after_and_evidence(
    program_chat: Conversation, test_database: Database
) -> None:
    result = _propose()

    assert result.startswith("PROPOSAL shown to the user")
    card = _card(test_database, program_chat)
    assert card.kind == "program_setup"
    # One line per changed field, not the whole action twice
    assert "Label: — → Plan week" in card.details["Change"].splitlines()
    assert "plan my week please" in card.details["Based on"]
    assert card.details["Why"] == "You ask for a weekly plan every Monday."
    assert card.options[0]["payload"]["fingerprint"] == ps.fingerprint(_ADD)


def test_outside_a_program_chat_it_refuses(
    test_database: Database, test_conversation: Conversation
) -> None:
    with use_database(test_database):
        set_conversation_context(test_conversation.id, test_conversation.user_id)
        set_current_request_id("turn-1")
        try:
            result = _propose()
        finally:
            set_conversation_context(None, None)
            set_current_request_id(None)
        assert "program chat" in result
        assert test_database.pending_proposals(test_conversation.id) == []


def test_without_dated_evidence_it_refuses(
    program_chat: Conversation, test_database: Database
) -> None:
    for evidence in ([], ["you often ask for a plan"]):
        result = _propose(evidence=evidence)
        assert "YYYY-MM-DD" in result
    assert test_database.pending_proposals(program_chat.id) == []


def test_an_invalid_change_is_refused_with_its_reason(
    program_chat: Conversation, test_database: Database
) -> None:
    result = _propose({"target": "instruction", "key": "progress", "patch": {"a": 1}})
    assert "goals" in result
    assert test_database.pending_proposals(program_chat.id) == []


def test_a_declined_change_needs_newer_evidence(
    program_chat: Conversation, test_database: Database, test_user: User
) -> None:
    # Declined today: today's turn is not newer evidence
    ps.record_decline(test_user.id, REF, ps.validate_change("sports", _ADD), "Add Plan week")  # type: ignore[arg-type]
    assert "declined" in _propose(evidence=[f"{_today()}: 'plan my week'"])

    # Declined two days ago: today's turn is newer
    entries = [{**e, "declined_at": _today(-2)} for e in ps.declined(test_user.id, REF)]
    test_database.kv_set(test_user.id, "sports", "setup_declined:cycling", json.dumps(entries))
    assert _propose(evidence=[f"{_today()}: 'plan my week again'"]).startswith("PROPOSAL")


def test_evidence_must_cite_a_day_the_user_wrote(
    program_chat: Conversation, test_database: Database
) -> None:
    """Final review #4: a made-up date is refused (it used to re-open declined changes)."""
    result = _propose(evidence=[f"{_today(-5)}: 'plan my week'"])
    assert "Cite only days the user wrote" in result
    assert test_database.pending_proposals(program_chat.id) == []


def test_the_card_carries_a_snapshot_so_a_hand_edit_wins(
    program_chat: Conversation, test_database: Database, test_user: User
) -> None:
    """Final review #1: approving after a hand edit refuses instead of overwriting."""
    edit = {
        "target": "quick_action",
        "op": "edit",
        "action_id": "next",
        "action": {**_NEXT, "body": "Coach's version"},
    }
    _propose(edit)
    card = _card(test_database, program_chat)
    mine = {
        "target": "quick_action",
        "op": "edit",
        "action_id": "next",
        "action": {**_NEXT, "body": "Mine"},
    }
    ps.apply_change(test_user.id, REF, mine)  # type: ignore[arg-type]

    answered = resolve(card, 0, "button")

    assert answered.state == "failed"
    assert "changed since" in (answered.result or "")
    assert ps.load_setup(test_user.id, REF)["quick_actions"][0]["body"] == "Mine"


def test_an_ignored_card_comes_back_once_after_three_days(
    program_chat: Conversation, test_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _propose()
    _card(test_database, program_chat)
    test_database.expire_proposals(program_chat.id)  # the user carried on chatting

    set_current_request_id("turn-2")
    monkeypatch.setattr(tool_module, "utc_now", lambda: utc_now() + timedelta(days=1))
    assert "again" in _propose()

    monkeypatch.setattr(tool_module, "utc_now", lambda: utc_now() + timedelta(days=4))
    assert _propose().startswith("PROPOSAL")
    _card(test_database, program_chat, "turn-2")
    test_database.expire_proposals(program_chat.id)

    set_current_request_id("turn-3")
    monkeypatch.setattr(tool_module, "utc_now", lambda: utc_now() + timedelta(days=30))
    assert "again" in _propose()


def test_approve_applies_exactly_the_card(
    program_chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose()
    card = resolve(_card(test_database, program_chat), 0, "button")

    assert card.state == "approved"
    assert "Plan week" in (card.result or "")
    labels = [a["label"] for a in ps.load_setup(test_user.id, REF)["quick_actions"]]
    assert labels == ["Next workout", "Plan week"]


def test_decline_records_the_decline(
    program_chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose()
    resolve(_card(test_database, program_chat), None, "button")

    assert [e["fingerprint"] for e in ps.declined(test_user.id, REF)] == [ps.fingerprint(_ADD)]


def test_a_stale_card_fails_with_its_reason(
    program_chat: Conversation, test_database: Database, test_user: User
) -> None:
    edit = {
        "target": "quick_action",
        "op": "edit",
        "action_id": "next",
        "action": {**_NEXT, "body": "Next one?"},
    }
    _propose(edit)
    card = _card(test_database, program_chat)
    ps.apply_change(
        test_user.id, REF, {"target": "quick_action", "op": "remove", "action_id": "next"}
    )

    answered = resolve(card, 0, "button")

    assert answered.state == "failed"
    assert "no longer" in (answered.result or "")
