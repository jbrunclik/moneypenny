"""propose_instruction_change: the assistant proposes a change to the user's
custom instructions on a card (docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.proposals import resolve
from src.agent.tool_results import set_current_request_id
from src.agent.tools import instructions_tool as tool_module
from src.agent.tools.context import set_conversation_context
from src.agent.tools.instructions_tool import propose_instruction_change
from src.db.models import use_database
from src.enums import MessageRole
from src.services import instructions_tuning as it
from src.utils.clock import local_today, utc_now

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal, User

RULE = "Never use bullet points."
_APPEND = {"instructions": {"op": "append", "new": RULE}}


def _today(offset: int = 0) -> str:
    return (local_today() + timedelta(days=offset)).isoformat()


def _stored(db: Database, user: User) -> str:
    found = db.get_user_by_id(user.id)
    return (found.custom_instructions or "") if found else ""


@pytest.fixture
def chat(test_database: Database, test_user: User) -> Iterator[Conversation]:
    with use_database(test_database):
        test_database.update_user_custom_instructions(test_user.id, "Answer in Czech.")
        conv = test_database.create_conversation(test_user.id, "Chat")
        test_database.add_message(conv.id, MessageRole.USER, "stop using bullet points please")
        set_conversation_context(conv.id, test_user.id)
        set_current_request_id("turn-1")
        yield conv
        set_conversation_context(None, None)
        set_current_request_id(None)


def _propose(change: dict[str, Any] | None = None, evidence: list[str] | None = None) -> str:
    return str(
        propose_instruction_change.invoke(
            {
                "change": json.dumps(change if change is not None else _APPEND),
                "evidence": evidence
                if evidence is not None
                else [f"{_today()}: 'stop using bullet points please'"],
                "reason": "You asked for no bullet points.",
            }
        )
    )


def _card(db: Database, conv: Conversation, request_id: str = "turn-1") -> Proposal:
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Noted.")
    db.link_proposals(request_id, reply.id)
    [card] = db.pending_proposals(conv.id)
    return card


class TestToolSchema:
    def test_every_param_has_a_concrete_type(self) -> None:
        for name, schema in propose_instruction_change.args.items():
            assert "type" in schema or "anyOf" in schema, name
        assert propose_instruction_change.args["evidence"]["items"]["type"] == "string"


def test_files_a_card_that_says_where_it_applies(
    chat: Conversation, test_database: Database
) -> None:
    result = _propose()

    assert result.startswith("PROPOSAL shown to the user")
    assert "Don't also save this rule as a memory" in result
    card = _card(test_database, chat)
    assert card.kind == "custom_instructions"
    assert card.details["Change"] == f"Instructions: — → {RULE}"
    assert card.details["Applies to"] == tool_module.APPLIES_TO
    assert "stop using bullet points" in card.details["Based on"]
    assert card.options[0]["payload"]["fingerprint"] == it.fingerprint(_APPEND)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["program", "anonymous"])
def test_outside_an_ordinary_chat_it_refuses(
    test_database: Database, test_user: User, kind: str
) -> None:
    with use_database(test_database):
        if kind == "program":
            conv = test_database.get_or_create_program_conversation("sports", test_user.id, "x")
        else:
            conv = test_database.create_conversation(test_user.id, "Secret")
            test_database.set_conversation_anonymous_mode(conv.id, test_user.id, True)
        set_conversation_context(conv.id, test_user.id)
        set_current_request_id("turn-1")
        try:
            result = _propose()
        finally:
            set_conversation_context(None, None)
            set_current_request_id(None)
        assert "ordinary chat" in result
        assert test_database.pending_proposals(conv.id) == []


def test_a_memory_only_change_is_not_a_card(chat: Conversation, test_database: Database) -> None:
    result = _propose({"memory": {"op": "delete", "id": "m1"}}, ["Memory: x"])
    assert "manage_memory" in result
    assert test_database.pending_proposals(chat.id) == []


def test_evidence_must_cite_a_day_the_user_wrote(
    chat: Conversation, test_database: Database
) -> None:
    result = _propose(evidence=[f"{_today(-5)}: 'no bullets'"])
    assert "Cite only days the user wrote" in result
    assert test_database.pending_proposals(chat.id) == []


def test_a_declined_change_needs_newer_evidence(chat: Conversation, test_user: User) -> None:
    it.record_decline(test_user.id, _APPEND, "No bullets")  # type: ignore[arg-type]
    assert "declined" in _propose()


def test_an_ignored_card_comes_back_once_after_three_days_across_chats(
    chat: Conversation,
    test_database: Database,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _propose()
    _card(test_database, chat)
    test_database.expire_proposals(chat.id)

    # Another chat, a day later: still too soon (counted per user)
    other = test_database.create_conversation(test_user.id, "Other")
    test_database.add_message(other.id, MessageRole.USER, "no bullet points")
    set_conversation_context(other.id, test_user.id)
    set_current_request_id("turn-2")
    monkeypatch.setattr(tool_module, "utc_now", lambda: utc_now() + timedelta(days=1))
    assert "again" in _propose()

    monkeypatch.setattr(tool_module, "utc_now", lambda: utc_now() + timedelta(days=4))
    assert _propose().startswith("PROPOSAL")


def test_approve_applies_exactly_the_card(
    chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose()
    card = resolve(_card(test_database, chat), 0, "button")

    assert card.state == "approved"
    assert _stored(test_database, test_user) == f"Answer in Czech.\n\n{RULE}"


def test_decline_records_the_decline(
    chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose()
    resolve(_card(test_database, chat), None, "button")

    assert [e["fingerprint"] for e in it.declined(test_user.id)] == [it.fingerprint(_APPEND)]  # type: ignore[arg-type]


def test_a_stale_card_fails_with_its_reason(
    chat: Conversation, test_database: Database, test_user: User
) -> None:
    _propose(
        {"instructions": {"op": "replace", "old": "Answer in Czech.", "new": "Answer in English."}}
    )
    card = _card(test_database, chat)
    test_database.update_user_custom_instructions(test_user.id, "Be brief.")

    answered = resolve(card, 0, "button")

    assert answered.state == "failed"
    assert "no longer" in (answered.result or "")
    assert _stored(test_database, test_user) == "Be brief."


def test_the_card_shows_its_change_as_field_rows(
    chat: Conversation, test_database: Database
) -> None:
    """The client renders the same field rows as the Review (not a text line)."""
    from src.api.utils import proposal_to_response

    _propose()
    shown = proposal_to_response(_card(test_database, chat))

    assert shown["changes"] == [{"field": "Instructions", "before": "", "after": RULE}]
