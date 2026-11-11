"""propose_instruction_change: the assistant proposes a change to the user's
custom instructions.

In an ordinary chat, when the user corrects how the assistant behaves in a way
meant to last ("stop using bullet points", "from now on answer in Czech"), it
files the change as a `custom_instructions` card: the passage before/after,
that it applies to every chat, and the turns it rests on. Only the user's yes
applies it (src/services/instructions_tuning.py); Decline remembers it, so it
is not offered again without newer evidence. An ignored card may come back
once, at least SETUP_REOFFER_AFTER_DAYS later - counted per user, since the
instructions are (docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import cast

from langchain_core.tools import tool

from src.agent.proposals import ProposalFailedError, card_shown, file_proposal, register_kind
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.config import Config
from src.db.models import Conversation, Proposal, ProposalOption, db
from src.services import instructions_tuning as it
from src.services import program_setup as setup
from src.utils.clock import utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

KIND = "custom_instructions"
TOOL_NAME = "propose_instruction_change"
_APPROVE_LABEL = "Apply"
APPLIES_TO = "Every chat - the coaches and agents included"


def _refused(reason: str, retriable: bool = True) -> str:
    """The tool error, logged with its reason (the regular review counts refusals)."""
    logger.info("Instructions change refused", extra={"reason": reason[:160]})
    return tool_error(f"Not proposed: {reason}", retriable=retriable)


def is_ordinary(conv: Conversation | None) -> bool:
    """A chat the instructions are learned from: not a program, agent, planner,
    What's new, standing or anonymous chat."""
    return conv is not None and not (
        conv.is_planning
        or conv.is_agent
        or conv.is_sports
        or conv.is_language
        or conv.is_whats_new
        or conv.standing_type
        or conv.anonymous_mode
    )


def _ignored(p: Proposal, conversation_id: str) -> bool:
    """An offer the user left unanswered: expired, or still pending in another
    chat (a card expires only when its own chat goes on - final review I1)."""
    return p.state == "expired" or (p.state == "pending" and p.conversation_id != conversation_id)


def _offered_again_too_soon(user_id: str, conversation_id: str, mark: str) -> str | None:
    """Why an ignored card may not come back yet (once, after a few days), or None."""
    past = [
        p
        for p in db.user_kind_proposals(user_id, KIND)
        if p.options and p.options[0]["payload"].get("fingerprint") == mark
    ]
    if any(p.state == "pending" and p.conversation_id == conversation_id for p in past):
        return "This exact change is already on a card in this chat."
    expired = [p for p in past if _ignored(p, conversation_id)]
    if len(expired) >= 2:
        return "This change was offered twice already and left unanswered - don't offer it again."
    if expired:
        last = expired[0].resolved_at or expired[0].created_at
        if utc_now() - last < timedelta(days=Config.SETUP_REOFFER_AFTER_DAYS):
            return (
                f"This change was offered on {last.date().isoformat()} and left unanswered - "
                f"offer it again at most once, after {Config.SETUP_REOFFER_AFTER_DAYS} days."
            )
    return None


def _summary(change: it.InstructionChange) -> str:
    op = change.get("instructions", {}).get("op")
    verb = {"append": "Add to", "replace": "Change", "remove": "Remove from"}.get(str(op), "Change")
    return f"{verb} your instructions"


def _checked(
    change: str, user_id: str, conversation_id: str, evidence: list[str]
) -> it.InstructionChange | str:
    """The validated change, or why it is not proposed."""
    try:
        parsed = json.loads(change)
    except json.JSONDecodeError:
        return "change must be a JSON object."
    checked = it.validate_change(parsed)
    if isinstance(checked, str):
        return f"{checked}."
    if "instructions" not in checked:
        return "a card changes the instructions; a fact about the user goes to manage_memory."
    state = it.load_state(user_id)
    if duplicate := it.already_there(state, checked):
        return duplicate
    if problem := it.evidence_problem(evidence, setup.chat_dates(conversation_id), state, checked):
        return problem
    return checked


@tool
def propose_instruction_change(change: str, evidence: list[str], reason: str) -> str:
    """Propose a change to the user's custom instructions (the rules in every
    chat's system prompt) when the user corrects the form of your replies in a
    way meant to last: format, length, tone, language ("stop using bullet
    points", "from now on answer in Czech"). The user sees a card with the
    passage before/after and your evidence; only their yes applies it. Not for
    a one-off request ("shorter this time") and not for facts about the user -
    those stay with manage_memory, also when phrased as a rule ("I'm
    vegetarian, never suggest meat": save the fact).

    Args:
        change: JSON object, one of:
            {"instructions": {"op": "append", "new": "<the rule>"}};
            {"instructions": {"op": "replace", "old": "<exact passage now there>", "new": "<rule>"}};
            {"instructions": {"op": "remove", "old": "<exact passage>"}}.
            Moving a memory that is really a rule: add "memory": {"op": "delete", "id": "<memory id>"}.
            Write the rule in the user's language, as a short instruction.
        evidence: 1-5 items, each "YYYY-MM-DD: what the user said" from this chat.
        reason: One sentence, for the user, on why this helps.
    """
    conversation_id, user_id = get_conversation_context()
    if (
        not conversation_id
        or not user_id
        or not is_ordinary(db.get_conversation(conversation_id, user_id))
    ):
        return tool_error(
            "Not proposed: this tool works only in an ordinary chat (not a coach, agent or "
            "anonymous chat).",
            retriable=False,
        )
    items = [e.strip() for e in evidence if e.strip()]
    checked = _checked(change, user_id, conversation_id, items)
    if isinstance(checked, str):
        return _refused(checked)
    if it.blocked_by_decline(it.declined(user_id), checked, items):
        return _refused(
            "The user declined this change before. Propose it again only with a turn dated "
            "after that decline.",
            retriable=False,
        )
    mark = it.fingerprint(checked)
    if refusal := _offered_again_too_soon(user_id, conversation_id, mark):
        return _refused(refusal, retriable=False)
    _retire_elsewhere(user_id, conversation_id, mark)
    return _file(user_id, checked, items, reason.strip())


def _retire_elsewhere(user_id: str, conversation_id: str, mark: str) -> None:
    """Offered again here: the same card left pending in another chat expires
    (two live cards for one change would apply it twice)."""
    for p in db.user_kind_proposals(user_id, KIND):
        if (
            p.state == "pending"
            and p.conversation_id != conversation_id
            and p.options
            and p.options[0]["payload"].get("fingerprint") == mark
        ):
            db.finish_proposal(p.id, "expired", "Offered again in another chat.")


def _file(user_id: str, change: it.InstructionChange, evidence: list[str], reason: str) -> str:
    state = it.load_state(user_id)
    try:
        rows = it.field_changes(state, change)
    except it.InstructionsChangeError as e:
        return _refused(str(e), retriable=False)
    # Approving later applies only if its memory still holds what the card showed
    change = it.with_snapshot(state, change)
    payload: dict[str, object] = {
        "change": dict(change),
        "fingerprint": it.fingerprint(change),
        # The card shows these as field rows (proposal_to_response)
        "changes": list(rows),
    }
    option: ProposalOption = {"label": _APPROVE_LABEL, "description": "", "payload": payload}
    changed = "\n".join(f"{r['field']}: {r['before'] or '—'} → {r['after'] or '—'}" for r in rows)
    details = {
        "Change": changed or "—",
        "Applies to": APPLIES_TO,
        "Why": reason,
        "Based on": "\n".join(evidence),
    }
    proposal = file_proposal(KIND, _summary(change), details, [option])
    logger.info("Instructions change proposed", extra={"target": it.target_name(change)})
    # Steering rides on the result: the rule is on its card, not in memory too
    return f"{card_shown(proposal)} Don't also save this rule as a memory."


def _change(option: ProposalOption) -> it.InstructionChange:
    return cast("it.InstructionChange", option["payload"].get("change") or {})


def apply_instructions_card(proposal: Proposal, option: ProposalOption) -> str:
    """Apply exactly the approved change (re-checked; a stale one fails with its reason)."""
    change = _change(option)
    try:
        it.apply_change(proposal.user_id, change)
    except it.InstructionsChangeError as e:
        it.log_resolved("card", "failed", change)
        raise ProposalFailedError(str(e)) from e
    it.log_resolved("card", "approved", change)
    return "Your instructions are updated."


def decline_instructions_card(proposal: Proposal) -> None:
    """Declined: remembered, so it is not offered again without newer evidence."""
    if not proposal.options:
        return
    change = _change(proposal.options[0])
    it.record_decline(proposal.user_id, change, proposal.summary)
    it.log_resolved("card", "declined", change)


register_kind(KIND, apply_instructions_card, decline=decline_instructions_card)
