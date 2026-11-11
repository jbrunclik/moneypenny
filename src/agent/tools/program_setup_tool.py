"""propose_setup_change: the coach proposes a change to its own setup.

A program chat (sports, language) works from its quick actions and its
standing instructions. When the coach notices evidence that one should change
- the user typed a request it has seen before, the user corrected it - it
files the change as a `program_setup` card: before/after and the turns it
rests on. Only the user's yes applies it (src/services/program_setup.py);
Decline remembers it, so it is not offered again without newer evidence. An
ignored card (expired because the user carried on) may come back once, at
least SETUP_REOFFER_AFTER_DAYS later
(docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
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
from src.db.models import Proposal, ProposalOption, db
from src.services import program_setup as setup
from src.services.program_setup import ProgramRef, SetupChange, SetupChangeError
from src.utils.clock import utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

KIND = "program_setup"
TOOL_NAME = "propose_setup_change"
MAX_EVIDENCE = 5
_APPROVE_LABEL = "Apply"


def _refused(reason: str, retriable: bool = True) -> str:
    """The tool error, logged with its reason (the regular review counts refusals)."""
    logger.info("Setup change refused", extra={"reason": reason[:160]})
    return tool_error(f"Not proposed: {reason}", retriable=retriable)


def _parse(change: str) -> dict[str, object] | str:
    try:
        data = json.loads(change)
    except json.JSONDecodeError:
        return "change must be a JSON object"
    return data if isinstance(data, dict) else "change must be a JSON object"


def _evidence_problem(evidence: list[str]) -> str | None:
    items = [e.strip() for e in evidence if e.strip()]
    if not 1 <= len(items) <= MAX_EVIDENCE or len(setup.evidence_dates(items)) != len(items):
        return (
            f"Give 1-{MAX_EVIDENCE} evidence items, each starting with the YYYY-MM-DD date of a "
            "turn in this chat and what was said (e.g. \"2026-11-09: 'what's my next workout?'\")."
        )
    return None


def _offered_again_too_soon(conversation_id: str, mark: str) -> str | None:
    """Why an ignored card may not come back yet (once, after a few days), or None."""
    past = [
        p
        for p in db.kind_proposals(conversation_id, KIND)
        if p.options and p.options[0]["payload"].get("fingerprint") == mark
    ]
    if any(p.state == "pending" for p in past):
        return "This exact change is already on a card in this chat."
    expired = [p for p in past if p.state == "expired"]
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


def _refusal(
    ref: ProgramRef, user_id: str, conversation_id: str, change: SetupChange, evidence: list[str]
) -> str | None:
    if setup.blocked_by_decline(setup.declined(user_id, ref), change, evidence):
        return (
            "The user declined this change before. Propose it again only with a turn dated "
            "after that decline."
        )
    return _offered_again_too_soon(conversation_id, setup.fingerprint(change))


def _summary(change: SetupChange) -> str:
    if change.get("target") == "instruction":
        return f"Update the coach's {change.get('key')}"
    action = change.get("action") or {}
    verb = {"add": "Add", "edit": "Change", "remove": "Remove"}.get(str(change.get("op")), "Change")
    label = action.get("label") or change.get("action_id") or "a quick action"
    return f"{verb} the quick action {label}"


@tool
def propose_setup_change(change: str, evidence: list[str], reason: str) -> str:
    """Propose a change to this program's own setup - a quick action or a
    standing instruction - when this chat shows it is needed: the user typed a
    request you have seen before (a quick action would save the typing), or
    corrected you (an instruction is out of date). The user sees a card with
    the change as before/after and your evidence, and only their yes applies
    it. Not for things the user asked you to change - do those directly.

    Args:
        change: JSON object, one of:
            {"target": "quick_action", "op": "add", "action": {"id", "emoji", "label", "body", "fields": [..]}};
            {"target": "quick_action", "op": "edit", "action_id": "<id>", "action": {...the whole new action}};
            {"target": "quick_action", "op": "remove", "action_id": "<id>"};
            {"target": "instruction", "key": "<goals|preferences|routine (sports); profile|grammar (language)>",
             "patch": {"field": "new value", "old_field": null}} or "text": "<whole new value>" for a prose value.
            Labels and bodies in the user's language.
        evidence: 1-5 items, each "YYYY-MM-DD: what the user said or did" from this chat.
        reason: One sentence, for the user, on why this helps.
    """
    conversation_id, user_id = get_conversation_context()
    ref = (
        setup.program_for_conversation(conversation_id, user_id)
        if conversation_id and user_id
        else None
    )
    if ref is None or not user_id or not conversation_id:
        return tool_error(
            "Not proposed: this tool works only in a program chat (sports, language).",
            retriable=False,
        )
    parsed = _parse(change)
    checked = parsed if isinstance(parsed, str) else setup.validate_change(ref.namespace, parsed)
    if isinstance(checked, str):
        return _refused(f"{checked}.")
    if problem := _evidence_problem(evidence):
        return _refused(problem)
    if refusal := _refusal(ref, user_id, conversation_id, checked, evidence):
        return _refused(refusal, retriable=False)
    return _file(ref, user_id, checked, [e.strip() for e in evidence if e.strip()], reason.strip())


def _file(
    ref: ProgramRef, user_id: str, change: SetupChange, evidence: list[str], reason: str
) -> str:
    try:
        before, after = setup.describe_change(setup.load_setup(user_id, ref), change)
    except SetupChangeError as e:
        return _refused(str(e), retriable=False)
    payload: dict[str, object] = {
        "namespace": ref.namespace,
        "program_id": ref.program_id,
        "change": dict(change),
        "fingerprint": setup.fingerprint(change),
    }
    option: ProposalOption = {"label": _APPROVE_LABEL, "description": "", "payload": payload}
    details = {"Change": f"{before} → {after}", "Why": reason, "Based on": "; ".join(evidence)}
    proposal = file_proposal(KIND, _summary(change), details, [option])
    logger.info(
        "Setup change proposed", extra={"target": change.get("target"), "namespace": ref.namespace}
    )
    return card_shown(proposal)


def _payload(option: ProposalOption) -> tuple[ProgramRef, SetupChange]:
    payload = option["payload"]
    ref = ProgramRef(str(payload.get("namespace")), str(payload.get("program_id")))
    return ref, cast("SetupChange", payload.get("change") or {})


def apply_setup_change(proposal: Proposal, option: ProposalOption) -> str:
    """Apply exactly the approved change (re-checked; a stale target fails with its reason)."""
    ref, change = _payload(option)
    try:
        line = setup.apply_change(proposal.user_id, ref, change)
    except SetupChangeError as e:
        setup.log_resolved("card", "failed", change)
        raise ProposalFailedError(str(e)) from e
    setup.log_resolved("card", "approved", change)
    return line


def decline_setup_change(proposal: Proposal) -> None:
    """Declined: remembered, so it is not offered again without newer evidence."""
    if not proposal.options:
        return
    ref, change = _payload(proposal.options[0])
    setup.record_decline(proposal.user_id, ref, change, proposal.summary)
    setup.log_resolved("card", "declined", change)


register_kind(KIND, apply_setup_change, decline=decline_setup_change)
