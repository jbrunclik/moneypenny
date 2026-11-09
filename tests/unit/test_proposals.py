"""Proposals: filed by a tool, answered on the card or by a typed yes, and
applied by the server exactly as shown (docs/features/proposals.md)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.proposals import (
    MAX_OPTIONS,
    ProposalFailedError,
    ProposalNotPendingError,
    answer_typed,
    file_proposal,
    register_kind,
    resolve,
    turn_note,
    typed_answer,
)
from src.agent.tool_results import set_current_request_id
from src.agent.tools.context import set_conversation_context
from src.db.models import use_database
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, Proposal, ProposalOption, User

_APPLIED: list[dict[str, object]] = []


def _apply(proposal: Proposal, option: ProposalOption) -> str:
    if option["payload"].get("fail"):
        raise ProposalFailedError("That time has passed")
    _APPLIED.append(option["payload"])
    return f"Done: {option['label']}"


@pytest.fixture
def db(test_database: Database) -> Iterator[Database]:
    with use_database(test_database):
        yield test_database


@pytest.fixture
def conv(db: Database, test_user: User) -> Iterator[str]:
    register_kind("test_kind", _apply)
    _APPLIED.clear()
    conv_id = db.create_conversation(test_user.id).id
    set_conversation_context(conv_id, test_user.id)
    set_current_request_id("req-1")
    yield conv_id
    set_conversation_context(None, None)
    set_current_request_id(None)


def _option(label: str = "Set it up", **payload: Any) -> ProposalOption:
    return {"label": label, "description": "", "payload": payload or {"n": 1}}


def _file(*options: ProposalOption, kind: str = "test_kind") -> Proposal:
    return file_proposal(
        kind, "Reminder Thu 8:00", {"When": "Thu 8:00"}, list(options or [_option()])
    )


def _on_reply(db: Database, conv_id: str, request_id: str = "req-1") -> str:
    reply = db.add_message(conv_id, "assistant", "Shall I?")
    db.link_proposals(request_id, reply.id)
    return reply.id


@pytest.mark.parametrize("text", ["yes", "Yes!", "ok", "do it", "ano", "Ano.", "jo", "jasně", "👍"])
def test_typed_yes_words_cs_and_en(text: str) -> None:
    assert typed_answer(text, [_option()]) == 0


@pytest.mark.parametrize("text", ["no", "Ne", "not now", "zrušit", "👎"])
def test_typed_no_words(text: str) -> None:
    assert typed_answer(text, [_option()]) is None


def test_a_qualified_yes_is_not_an_answer() -> None:
    assert typed_answer("yes but at 9", [_option()]) == "no-answer"
    assert typed_answer("ano, ale v 9", [_option()]) == "no-answer"


def test_number_or_label_picks_among_options() -> None:
    options = [_option("Weekly check"), _option("Watch the page")]
    assert typed_answer("2", options) == 1
    assert typed_answer("watch the page", options) == 1
    assert typed_answer("5", options) == "no-answer"


def test_yes_resolves_nothing_with_several_options() -> None:
    assert typed_answer("yes", [_option("A"), _option("B")]) == "no-answer"


def test_resolve_applies_the_chosen_payload(db: Database, conv: str, test_user: User) -> None:
    proposal = _file(_option(when="Thu"))

    done = resolve(proposal, 0, "button")

    assert (done.state, done.result, done.chosen, done.resolved_by) == (
        "approved",
        "Done: Set it up",
        0,
        "button",
    )
    assert _APPLIED == [{"when": "Thu"}]


def test_resolve_declines(db: Database, conv: str) -> None:
    done = resolve(_file(), None, "button")
    assert done.state == "declined"
    assert _APPLIED == []


def test_resolve_applies_once_under_a_race(db: Database, conv: str) -> None:
    proposal = _file()
    errors: list[Exception] = []

    def tap() -> None:
        try:
            resolve(proposal, 0, "button")
        except ProposalNotPendingError as e:
            errors.append(e)

    threads = [threading.Thread(target=tap) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(_APPLIED) == 1
    assert len(errors) == 1


def test_apply_failure_marks_failed_with_reason(db: Database, conv: str) -> None:
    done = resolve(_file(_option(fail=True)), 0, "button")
    assert (done.state, done.result) == ("failed", "That time has passed")


def test_a_second_proposal_of_a_request_supersedes(
    db: Database, conv: str, test_user: User
) -> None:
    first = _file()
    second = _file()

    assert [p.id for p in db.pending_proposals(conv)] == [second.id]
    older = db.get_proposal(first.id, test_user.id)
    assert older is not None and older.state == "superseded"


def test_answer_typed_resolves_all_on_the_latest_reply(db: Database, conv: str) -> None:
    register_kind("other_kind", _apply)
    _file()
    _file(kind="other_kind")
    _on_reply(db, conv)

    answered = answer_typed(conv, "ano")

    assert sorted(p.state for p in answered) == ["approved", "approved"]
    assert len(_APPLIED) == 2


def test_a_non_answer_expires_pending(db: Database, conv: str, test_user: User) -> None:
    proposal = _file()
    _on_reply(db, conv)

    assert answer_typed(conv, "actually make it 9") == []

    after = db.get_proposal(proposal.id, test_user.id)
    assert after is not None and after.state == "expired"


def test_turn_note_reports_once(db: Database, conv: str) -> None:
    resolve(_file(), 0, "button")

    note = turn_note(conv)

    assert note is not None and "approved" in note and "Done: Set it up" in note
    assert turn_note(conv) is None


def test_unknown_kind_is_refused(db: Database, conv: str) -> None:
    with pytest.raises(KeyError):
        file_proposal("nope", "x", {}, [_option()])


@pytest.mark.parametrize("count", [0, MAX_OPTIONS + 1])
def test_one_to_four_options(db: Database, conv: str, count: int) -> None:
    with pytest.raises(ValueError, match="options"):
        file_proposal("test_kind", "x", {}, [_option(str(n)) for n in range(count)])


def test_a_tap_racing_a_typed_answer_is_skipped(
    db: Database, conv: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tap claims the card between the typed answer's read and its claim:
    the typed answer skips it instead of failing the turn."""
    filed = _file()
    _on_reply(db, conv)
    stale = db.get_proposal(filed.id, filed.user_id)  # the typed answer's read
    assert stale is not None and stale.message_id is not None
    resolve(stale, 0, "button")  # the phone's tap wins
    monkeypatch.setattr(db, "pending_proposals", lambda _conv_id: [stale])  # read before the tap

    assert answer_typed(conv, "ok") == []
    assert len(_APPLIED) == 1


def test_a_rerun_hears_outcomes_since_its_message_again(db: Database, conv: str) -> None:
    since = utc_now()
    resolve(_file(), 0, "button")
    assert turn_note(conv) is not None  # the failed turn heard it...

    note = turn_note(conv, since=since)  # ...its regenerate hears it again

    assert note is not None and "Done: Set it up" in note


def test_approving_passes_through_applying(db: Database, conv: str, test_user: User) -> None:
    seen: list[str] = []

    def watching(proposal: Proposal, option: ProposalOption) -> str:
        current = db.get_proposal(proposal.id, proposal.user_id)
        seen.append(current.state if current else "?")
        return "ok"

    register_kind("watched", watching)
    done = resolve(_file(kind="watched"), 0, "button")

    assert seen == ["applying"]
    assert done.state == "approved"


def test_a_running_turns_new_card_survives_a_message(db: Database, conv: str) -> None:
    """An attachment send while a turn runs is not steering: it must not
    expire the card that turn just filed (not linked to its reply yet)."""
    running = _file()

    assert answer_typed(conv, "here is the photo", turn_running=True) == []

    assert [p.id for p in db.pending_proposals(conv)] == [running.id]


def test_a_yes_with_more_after_it_still_answers_nothing() -> None:
    """Only whole-message answers: "yes but at 9" is a new instruction."""
    from src.agent.proposals import typed_answer

    assert typed_answer("yes please", [_option()]) == 0
    assert typed_answer("yes but at 9", [_option()]) == "no-answer"
