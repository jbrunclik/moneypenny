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
        "ano", "jo", "jj", "jasně", "dobře", "souhlasím", "potvrzuji", "👍",
    }
)  # fmt: skip
_NO = frozenset({"no", "nope", "not now", "cancel", "ne", "nechci", "zrušit", "👎"})
_TRAILING = re.compile(r"[\s.!,]+$")

Apply = Callable[[Proposal, ProposalOption], str]
_KINDS: dict[str, Apply] = {}


class ProposalFailedError(Exception):
    """Applying an option could not be done; the message says why (shown on the card)."""


class ProposalNotPendingError(Exception):
    """The proposal was answered, expired or superseded already."""


def register_kind(kind: str, apply: Apply) -> None:
    """Register how a kind's chosen option is applied (returns the result line)."""
    _KINDS[kind] = apply


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


def _ensure_kinds() -> None:
    """The kinds register when their tools import (a route may come first)."""
    import src.agent.tools  # noqa: F401, PLC0415 - registration side effect; cycle: tools import this


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


def _normalized(text: str) -> str:
    return _TRAILING.sub("", text.strip().casefold())


def typed_answer(text: str, options: list[ProposalOption]) -> int | NoAnswer | None:
    """The option a typed message picks, None for a no, or NO_ANSWER."""
    said = _normalized(text)
    if said in _NO:
        return None
    if len(options) == 1:
        return 0 if said in _YES else NO_ANSWER
    if said.isdigit() and 1 <= int(said) <= len(options):
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
    resolved = db.get_proposal(proposal.id, proposal.user_id) or proposal
    logger.info(
        "Proposal resolved",
        extra={
            "kind": proposal.kind,
            "state": resolved.state,
            "resolved_by": by,
            "seconds_open": round((utc_now() - proposal.created_at).total_seconds()),
        },
    )
    return resolved


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


def answer_typed(conversation_id: str, text: str, turn_running: bool = False) -> list[Proposal]:
    """Resolve the latest reply's pending proposals from the user's typed
    message; a message that answers none of them expires them all - except,
    while another turn runs (turn_running), the cards it filed and has not
    shown yet."""
    pending = db.pending_proposals(conversation_id)
    shown = [p for p in pending if p.message_id]
    if not shown:
        db.expire_proposals(conversation_id, keep_unlinked=turn_running)
        return []
    latest = shown[-1].message_id
    on_reply = [p for p in shown if p.message_id == latest]
    answers = [(p, typed_answer(text, p.options)) for p in on_reply]
    if all(answer == NO_ANSWER for _, answer in answers):
        db.expire_proposals(conversation_id, keep_unlinked=turn_running)
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
    db.expire_proposals(conversation_id, keep_unlinked=turn_running)
    return resolved


def answer_and_note(
    conversation_id: str,
    text: str | None,
    since: datetime | None = None,
    turn_running: bool = False,
) -> str | None:
    """The turn's start: resolve a typed answer (None for a rerun, which
    answers nothing), then what the agent should hear about its proposals.
    A rerun passes `since` (its user message's time): what that message
    answered is told again - the failed attempt heard it, its retry did not."""
    db.fail_stale_applying(before=utc_now() - APPLY_STALE_AFTER)
    if text is not None:
        answer_typed(conversation_id, text, turn_running=turn_running)
    return turn_note(conversation_id, since=since)


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
        _OUTCOME[p.state].format(summary=p.summary, result=p.result or "")
        for p in news
        if p.state in _OUTCOME
    ]
    return "\n".join(lines) or None
