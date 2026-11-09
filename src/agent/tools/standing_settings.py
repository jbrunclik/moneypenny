"""edit_standing_chat: an agent changes its own settings - never silently.

Standing chats phase 2, Part D (D1). Editable: standing instructions,
schedule (cron), model, daily budget, fresh context, grants (tools).

- In conversation (the user is here): the call files a proposal card
  (src/agent/proposals.py); the server applies exactly that change when the
  user approves.
- In an unattended run: it files an approval request and the run pauses;
  the change applies only when the user approves it.
Grants therefore never widen without the user's explicit yes or approval.
The Daily Briefing runs on a stock prompt from code: its first instructions
edit stores the user's own copy (the preview says so).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, TypedDict, cast

from croniter import croniter
from langchain_core.tools import tool

from src.agent.permissions import WRITE_LEVEL_TOOLS, WRITE_SUFFIX, base_tool
from src.agent.proposals import ProposalFailedError, card_shown, file_proposal, register_kind
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.request_approval import ApprovalRequestedException
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Proposal, ProposalOption, StandingChat

logger = get_logger(__name__)

TOOL_NAME = "edit_standing_chat"
PROPOSAL_KIND = "edit_agent"
_APPROVE_LABEL = "Apply"
ALL_GRANTS = "*"


class Change(TypedDict, total=False):
    """The settings a change sets (absent = unchanged)."""

    instructions: str
    schedule: str
    model: str
    budget_usd: float
    fresh_context: bool
    grants: list[str]


def _changes(**fields: object) -> Change:
    return cast("Change", {name: value for name, value in fields.items() if value is not None})


def _invalid(changes: Change) -> str | None:
    """Why the change cannot be made, if it cannot."""
    from src.agent.tools import grantable_tool_names  # noqa: PLC0415 - cycle: tools imports this module

    if not changes:
        return "Say what to change: instructions, schedule, model, budget_usd, fresh_context or grants."
    schedule = changes.get("schedule")
    if schedule is not None and not croniter.is_valid(schedule):
        return f"'{schedule}' is not a valid cron expression (e.g. '15 7 * * *')."
    model = changes.get("model")
    if model is not None and model not in Config.MODELS:
        return f"Unknown model '{model}'. Available: {', '.join(Config.MODELS)}."
    budget = changes.get("budget_usd")
    if budget is not None and budget < 0:
        return "The daily budget cannot be negative."
    unknown = {
        grant
        for grant in changes.get("grants") or []
        if not _grantable(grant, grantable_tool_names())
    }
    if unknown:
        return f"Unknown tools: {', '.join(sorted(unknown))}."
    return None


def unknown_grants(grants: list[str]) -> set[str]:
    """The grants no job can hold (shared with create_standing_chat)."""
    from src.agent.tools import grantable_tool_names  # noqa: PLC0415 - cycle: tools imports this module

    tools = grantable_tool_names()
    return {grant for grant in grants if not _grantable(grant, tools)}


def _grantable(grant: str, tools: set[str]) -> bool:
    """A tool a job can hold, or a write level of a writable integration."""
    if grant == ALL_GRANTS:
        return True
    if grant.endswith(WRITE_SUFFIX):
        return base_tool(grant) in WRITE_LEVEL_TOOLS
    return grant in tools


def _tools_text(grants: set[str]) -> str:
    return ", ".join("all tools" if g == ALL_GRANTS else g for g in sorted(grants)) or "none"


def _describe(chat: StandingChat, changes: Change) -> str:
    """The change in words: what the user is agreeing to."""
    lines: list[str] = []
    if "instructions" in changes:
        lines.append(f"- Instructions become:\n  {changes['instructions']}")
        if chat.standing_type and not chat.instructions:
            lines.append("  (this replaces the built-in prompt with your own copy)")
    if "schedule" in changes:
        lines.append(
            f"- Schedule: `{chat.job.schedule}` -> `{changes['schedule']}` ({chat.job.timezone})"
        )
    if "model" in changes:
        lines.append(f"- Model: {chat.job.model} -> {changes['model']}")
    if "budget_usd" in changes:
        lines.append(f"- Daily budget: ${changes['budget_usd']:.2f}")
    if "fresh_context" in changes:
        state = (
            "each run starts fresh" if changes["fresh_context"] else "runs see this chat's history"
        )
        lines.append(f"- History: {state}")
    if "grants" in changes:
        before = set(chat.grants)
        after = set(changes["grants"])
        added, removed = after - before, before - after
        lines.append(
            f"- Tools: {_tools_text(after)}"
            + (f" (new access: {_tools_text(added)})" if added else "")
            + (f" (removed: {_tools_text(removed)})" if removed else "")
        )
    return "\n".join(lines)


def validated_change(raw: Mapping[str, object]) -> Change | str:
    """An approved change re-checked before it applies: only known fields,
    valid values (a stale or forged approval changes nothing); or why not."""
    change = cast("Change", {k: v for k, v in raw.items() if k in Change.__annotations__})
    if problem := _invalid(change):
        return problem
    return change


def apply_standing_changes(job_id: str, user_id: str, changes: Change) -> StandingChat | None:
    """Apply an approved change to a standing chat (its chat and its job)."""
    chat = db.update_standing_chat(
        job_id,
        user_id,
        instructions=changes.get("instructions", ...),
        schedule=changes.get("schedule", ...),
        model=changes.get("model", ...),
        budget_usd=changes.get("budget_usd", ...),
        fresh_context=changes.get("fresh_context", ...),
        grants=changes.get("grants", ...),
    )
    logger.info(
        "Standing chat settings changed",
        extra={"user_id": user_id, "job_id": job_id, "fields": sorted(changes)},
    )
    return chat


def _request_approval(chat: StandingChat, changes: Change) -> str:
    """Unattended: file the change for the user's approval and pause the run."""
    description = f"Change {chat.name}'s settings:\n{_describe(chat, changes)}"
    approval = db.create_approval_request(
        chat.id, chat.user_id, TOOL_NAME, dict(changes), description
    )
    raise ApprovalRequestedException(approval.id, description, TOOL_NAME)


def apply_edit_agent(proposal: Proposal, option: ProposalOption) -> str:
    """Apply exactly the approved change (re-checked: stale values change nothing)."""
    payload = option["payload"]
    changes = validated_change(cast("Mapping[str, object]", payload.get("changes") or {}))
    if isinstance(changes, str):
        raise ProposalFailedError(changes)
    chat = apply_standing_changes(str(payload.get("job_id")), proposal.user_id, changes)
    if chat is None:
        raise ProposalFailedError("That agent no longer exists.")
    return f"Updated {chat.name}."


register_kind(PROPOSAL_KIND, apply_edit_agent)


def _in_chat(conversation_id: str, user_id: str, changes: Change) -> str:
    conv = db.get_conversation(conversation_id, user_id)
    chat = (
        db.get_standing_chat(conv.job_id, user_id)
        if conv and conv.is_agent and conv.job_id
        else None
    )
    if chat is None:
        return tool_error("This chat has no agent whose settings could change.", retriable=False)
    if problem := _invalid(changes):
        return tool_error(problem)
    proposal = file_proposal(
        PROPOSAL_KIND,
        f"Change {chat.name}'s settings",
        {"Changes": _describe(chat, changes)},
        [
            {
                "label": _APPROVE_LABEL,
                "description": "",
                "payload": {"job_id": chat.id, "changes": dict(changes)},
            }
        ],
    )
    return card_shown(proposal)


@tool
def edit_standing_chat(
    instructions: str | None = None,
    schedule: str | None = None,
    model: str | None = None,
    budget_usd: float | None = None,
    fresh_context: bool | None = None,
    grants: list[str] | None = None,
) -> str:
    """Change this agent's own settings - its standing instructions, schedule,
    model, daily budget, history or tools - always with the user's agreement.

    Talking with the user: it shows them a card with the change and changes
    nothing itself - the server applies exactly that change when they approve
    (on the card, or by replying yes). Never say it changed before you hear
    it was approved. During a scheduled run (the user is away) it asks the
    user for approval instead and the run pauses until they answer.

    Args:
        instructions: The full new standing instructions (not a diff).
        schedule: Cron in the agent's timezone, e.g. "30 6 * * *" (daily 06:30),
            "0 18 * * 5" (Fridays 18:00).
        model: A model id.
        budget_usd: Daily budget for the agent's own runs, in USD.
        fresh_context: true = each run starts fresh; false = runs see this chat.
        grants: The complete list of tools the agent may use (e.g. ["garmin_connect"]).
    """
    from src.agent.run_context import get_job_context  # noqa: PLC0415 - cycle: run_context imports the tools

    changes = _changes(
        instructions=instructions,
        schedule=schedule,
        model=model,
        budget_usd=budget_usd,
        fresh_context=fresh_context,
        grants=grants,
    )
    run = get_job_context()
    if run is not None:  # unattended: only ever a request for approval
        if problem := _invalid(changes):
            return tool_error(problem)
        chat = db.get_standing_chat(run.item.id, run.user.id)
        if chat is None:
            return tool_error(
                "Only a standing chat's run can change its settings.", retriable=False
            )
        return _request_approval(chat, changes)
    conversation_id, user_id = get_conversation_context()
    if not conversation_id or not user_id:
        return tool_error("No conversation context available.", retriable=False)
    return _in_chat(conversation_id, user_id, changes)
