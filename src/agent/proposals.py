"""Proposals: the one way Moneypenny asks for a yes (docs/features/proposals.md).

A tool files a proposal during a turn instead of acting: 1-4 options, each
with the exact payload choosing it applies. The saved reply shows it as a
card. The user answers on the card (resolve) or with a typed answer as their
next message (answer_typed): a yes word approves a one-option proposal, a
number or an option's label picks among several, a no word declines. Any
other message leaves the conversation's pending proposals expired - the
user moved on. Applying is the server's job, through the kind's registered
apply function, so what runs is exactly what the card showed; the agent
hears the outcome on its next turn (turn_note).
"""

from __future__ import annotations

import importlib
import re
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from src.agent.tool_results import get_current_request_id
from src.db.models import Proposal, ProposalOption, db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.db.models.dataclasses import ProposalState

logger = get_logger(__name__)

MAX_OPTIONS = 4
# A claim older than this that never recorded its outcome: the worker died
APPLY_STALE_AFTER = timedelta(minutes=2)
NoAnswer = Literal["no-answer"]
NO_ANSWER: NoAnswer = "no-answer"

# Whole-message typed answers (casefolded, trailing punctuation dropped)
_YES = frozenset(
    {
        "yes", "y", "yeah", "yep", "sure", "ok", "okay", "do it", "go ahead",
        "yes please", "please do",
        "ano", "jo", "jj", "jasně", "dobře", "souhlasím", "potvrzuji", "ano prosím",
        "jo prosím", "👍",
    }
)  # fmt: skip
_NO = frozenset({"no", "nope", "not now", "cancel", "ne", "nechci", "zrušit", "👎"})
_TRAILING = re.compile(r"[\s.!,]+$")
_INNER = re.compile(r"[\s,]+")

Apply = Callable[[Proposal, ProposalOption], str]
Decline = Callable[[Proposal], None]
_KINDS: dict[str, Apply] = {}
_DECLINES: dict[str, Decline] = {}
# Kinds whose first option is the plain yes (the others are extras)
_YES_FIRST: set[str] = set()
# More whole-message yes words a kind takes (its action's own verb: "smaž to")
_EXTRA_YES: dict[str, frozenset[str]] = {}
# Kinds a typed number does not pick from ("2" may be the user's own answer)
_LABELS_ONLY: set[str] = set()
# Kinds whose pick takes the whole message: a question's "Smazat" answers the
# question, never a delete card beside it on the same reply
_EXCLUSIVE: set[str] = set()
# What the agent hears about a kind's card, by state, where the default
# ("The user approved: ...") would be wrong (a question is answered, not approved)
_KIND_OUTCOMES: dict[str, dict[str, str]] = {}
# Kinds a typed answer reaches only on the stream, and only a turn starts
# (deep research runs as that turn) - never the approve endpoint
_STREAM_ONLY: set[str] = set()
STREAM_STARTED = _STREAM_ONLY


class ProposalFailedError(Exception):
    """Applying an option could not be done; the message says why (shown on the card)."""


class ProposalNotPendingError(Exception):
    """The proposal was answered, expired or superseded already."""


def register_kind(
    kind: str,
    apply: Apply,
    decline: Decline | None = None,
    *,
    yes_is_first: bool = False,
    stream_only: bool = False,
    extra_yes: frozenset[str] = frozenset(),
    outcomes: Mapping[str, str] | None = None,
    exclusive: bool = False,
    by_number: bool = True,
) -> None:
    """Register how a kind's chosen option is applied (returns the result
    line), what a decline does besides recording it (a paused run ends),
    whether a typed yes picks its first option when it offers several, and
    whether only a streamed turn can act on a typed yes (a batch turn leaves
    the card open for its button)."""
    _KINDS[kind] = apply
    if yes_is_first:
        _YES_FIRST.add(kind)
    if stream_only:
        _STREAM_ONLY.add(kind)
    if extra_yes:
        _EXTRA_YES[kind] = frozenset(_normalized(word) for word in extra_yes)
    if outcomes:
        _KIND_OUTCOMES[kind] = dict(outcomes)
    if exclusive:
        _EXCLUSIVE.add(kind)
    if not by_number:
        _LABELS_ONLY.add(kind)
    if decline is not None:
        _DECLINES[kind] = decline


def card_shown(proposal: Proposal) -> str:
    """The tool result after filing: the card is the question, the model only
    says what it proposed (and never claims it is done)."""
    labels = " / ".join(o["label"] for o in proposal.options)
    shown = "; ".join(f"{k}: {v}" for k, v in proposal.details.items())
    return (
        f"PROPOSAL shown to the user as a card ({labels} / Not now): {proposal.summary}"
        f"{f' - {shown}' if shown else ''}. Nothing is done yet: say in one sentence what "
        "you proposed; they answer on the card or by replying."
    )


# Where the kinds register: the tools package (the chat setups, deep
# research) and the chat-change hold
_KIND_MODULES = ("src.agent.tools", "src.agent.chat_changes")


def _ensure_kinds() -> None:
    """The kinds register when their modules import (a route may come first;
    imported by name - they import this module)."""
    for module in _KIND_MODULES:
        importlib.import_module(module)


def file_proposal(
    kind: str, summary: str, details: Mapping[str, object], options: list[ProposalOption]
) -> Proposal:
    """File a proposal for this turn's reply; a newer one of the same kind
    from the same turn replaces the older (one preview per kind, as before)."""
    if kind not in _KINDS:
        raise KeyError(f"unknown proposal kind {kind!r}")
    if not 1 <= len(options) <= MAX_OPTIONS:
        raise ValueError(f"a proposal has 1-{MAX_OPTIONS} options, not {len(options)}")
    from src.agent.tools.context import get_conversation_context  # noqa: PLC0415 - cycle: the tools package imports this module

    conversation_id, user_id = get_conversation_context()
    if not (conversation_id and user_id):
        raise ValueError("a proposal needs a conversation")
    proposal = db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=None,
            request_id=get_current_request_id() or "",
            kind=kind,
            summary=summary,
            details=dict(details),
            options=options,
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
        )
    )
    if proposal.request_id:
        db.supersede_proposals(proposal.request_id, kind, proposal.id)
    logger.info("Proposal filed", extra={"kind": kind, "options": len(options)})
    return proposal


def normalize_answer(text: str) -> str:
    """A typed answer (or an option's label) as it is matched."""
    return _normalized(text)


def is_answer_word(label: str) -> bool:
    """Whether a label would read as a plain yes or no (it could not be picked).
    A kind's own yes words ("smazat") stay allowed: a question's pick is the
    message's only answer (exclusive), so it never approves a card beside it."""
    return _normalized(label) in _YES | _NO


def _normalized(text: str) -> str:
    """Casefolded, trailing punctuation dropped, inner commas and runs of
    space as one space ("Ano, smazat!" -> "ano smazat")."""
    return _INNER.sub(" ", _TRAILING.sub("", text.strip().casefold()))


def typed_answer(
    text: str,
    options: list[ProposalOption],
    *,
    yes_is_first: bool = False,
    extra_yes: frozenset[str] = frozenset(),
    by_number: bool = True,
) -> int | NoAnswer | None:
    """The option a typed message picks, None for a no, or NO_ANSWER."""
    said = _normalized(text)
    if said in _NO:
        return None
    if len(options) == 1 or yes_is_first:
        if said in _YES or said in extra_yes:
            return 0
        if len(options) == 1:
            return NO_ANSWER
    if by_number and said.isdigit() and 1 <= int(said) <= len(options):
        return int(said) - 1
    labels = [_normalized(o["label"]) for o in options]
    return labels.index(said) if said in labels else NO_ANSWER


def resolve(proposal: Proposal, choice: int | None, by: Literal["button", "typed"]) -> Proposal:
    """Answer a pending proposal: decline (None) or apply the chosen option."""
    _ensure_kinds()
    if choice is not None and not 0 <= choice < len(proposal.options):
        raise ValueError(f"choice {choice} is not one of the {len(proposal.options)} options")
    # An approval is claimed as "applying" until its outcome is recorded
    state: ProposalState = "declined" if choice is None else "applying"
    if not db.claim_proposal(proposal.id, state, choice, by):
        raise ProposalNotPendingError(proposal.id)
    if choice is not None:
        state, result = _apply(proposal, proposal.options[choice])
        db.finish_proposal(proposal.id, state, result)
    elif on_decline := _DECLINES.get(proposal.kind):
        on_decline(proposal)
    resolved = db.get_proposal(proposal.id, proposal.user_id) or proposal
    log_resolved(proposal, resolved.state, by)
    return resolved


def log_resolved(proposal: Proposal, state: ProposalState, by: str) -> None:
    """One line per answer (A8): what was asked, how it ended, how fast.
    A deep-research Start claims its card itself and logs here too."""
    logger.info(
        "Proposal resolved",
        extra={
            "kind": proposal.kind,
            "state": state,
            "resolved_by": by,
            "seconds_open": round((utc_now() - proposal.created_at).total_seconds()),
        },
    )


def _apply(proposal: Proposal, option: ProposalOption) -> tuple[ProposalState, str]:
    started = time.monotonic()
    try:
        result = _KINDS[proposal.kind](proposal, option)
    except ProposalFailedError as e:
        return "failed", str(e)
    except Exception:  # never leave a claimed proposal without an outcome
        logger.warning("Proposal apply crashed", extra={"kind": proposal.kind}, exc_info=True)
        return "failed", "Something went wrong - nothing was changed. Try again later."
    logger.debug("Proposal applied", extra={"ms": round((time.monotonic() - started) * 1000)})
    return "approved", result


def answer_typed(
    conversation_id: str, text: str, turn_running: bool = False, streaming: bool = True
) -> list[Proposal]:
    """Resolve the latest reply's pending proposals from the user's typed
    message (cards under older replies, and expired ones, wait for a tap);
    a message that answers none of them expires them all - except, while
    another turn runs (turn_running), the cards it filed and has not shown
    yet, and in a batch turn (not streaming) the stream-only kinds."""
    spared: frozenset[str] = frozenset() if streaming else frozenset(_STREAM_ONLY)
    on_reply = [p for p in db.latest_reply_proposals(conversation_id) if p.kind not in spared]
    answers = [
        (
            p,
            typed_answer(
                text,
                p.options,
                yes_is_first=p.kind in _YES_FIRST,
                extra_yes=_EXTRA_YES.get(p.kind, frozenset()),
                by_number=p.kind not in _LABELS_ONLY,
            ),
        )
        for p in on_reply
    ]
    # A pick on an exclusive card (a question) is the message's only answer
    if any(p.kind in _EXCLUSIVE and answer != NO_ANSWER for p, answer in answers):
        answers = [(p, a if p.kind in _EXCLUSIVE else NO_ANSWER) for p, a in answers]
    if all(answer == NO_ANSWER for _, answer in answers):
        db.expire_proposals(conversation_id, keep_unlinked=turn_running, keep_kinds=spared)
        return []
    resolved: list[Proposal] = []
    for proposal, answer in answers:
        if answer == NO_ANSWER:
            continue
        try:
            resolved.append(resolve(proposal, answer, "typed"))
        except ProposalNotPendingError:  # a tap elsewhere answered it meanwhile
            continue
    # Older or unanswered ones are stale now
    db.expire_proposals(conversation_id, keep_unlinked=turn_running, keep_kinds=spared)
    return resolved


def start_turn(
    conversation_id: str,
    text: str | None,
    since: datetime | None = None,
    turn_running: bool = False,
    streaming: bool = True,
) -> tuple[str | None, list[Proposal]]:
    """The turn's start: resolve a typed answer (None for a rerun, which
    answers nothing); returns what the agent should hear about its proposals
    and the cards this message answered. A rerun passes `since` (its user
    message's time): what that message answered is told again - the failed
    attempt heard it, its retry did not."""
    db.fail_stale_applying(before=utc_now() - APPLY_STALE_AFTER)
    waiting = _stream_only_yes(conversation_id, text) if text and not streaming else []
    answered = (
        answer_typed(conversation_id, text, turn_running=turn_running, streaming=streaming)
        if text is not None
        else []
    )
    note = turn_note(conversation_id, since=since)
    hints = [_STREAM_ONLY_HINT.format(summary=p.summary) for p in waiting]
    return "\n".join(line for line in [note, *hints] if line) or None, answered


# A yes a batch turn cannot act on (deep research runs only on the stream)
_STREAM_ONLY_HINT = (
    "The user said yes to “{summary}”, but with streaming off it starts only from its "
    "Start button: ask them to press Start on the card."
)


def _stream_only_yes(conversation_id: str, text: str) -> list[Proposal]:
    """The latest reply's stream-only cards this message would have answered."""
    return [
        p
        for p in db.latest_reply_proposals(conversation_id)
        if p.kind in _STREAM_ONLY
        and typed_answer(text, p.options, extra_yes=_EXTRA_YES.get(p.kind, frozenset()))
        not in (NO_ANSWER, None)
    ]


def answer_and_note(
    conversation_id: str,
    text: str | None,
    since: datetime | None = None,
    turn_running: bool = False,
) -> str | None:
    """start_turn's note alone (the eval harness)."""
    return start_turn(conversation_id, text, since=since, turn_running=turn_running)[0]


def answers_only_runs(answered: list[Proposal]) -> bool:
    """The message only answered run cards: the resumed (or ended) run is the
    reply, so the turn runs no agent of its own."""
    return bool(answered) and all(p.origin == "run" for p in answered)


_OUTCOME = {
    "approved": "The user approved: {summary} - {result}",
    "declined": "The user declined: {summary}",
    "failed": "The user approved, but it could not be done: {summary} - {result}",
    "expired": "Not answered, so nothing was done: {summary}",
}


def turn_note(conversation_id: str, since: datetime | None = None) -> str | None:
    """What happened to this conversation's proposals since the agent last
    heard (one line each), plus - with `since` - everything resolved since
    then again; None when nothing did."""
    news = db.unreported_proposals(conversation_id)
    if since is not None:
        known = {p.id for p in news}
        news += [
            p for p in db.resolved_proposals_since(conversation_id, since) if p.id not in known
        ]
    if not news:
        return None
    db.mark_reported([p.id for p in news])
    lines = [
        {**_OUTCOME, **_KIND_OUTCOMES.get(p.kind, {})}[p.state].format(
            summary=p.summary, result=p.result or ""
        )
        for p in news
        if p.state in _OUTCOME
    ]
    return "\n".join(lines) or None
