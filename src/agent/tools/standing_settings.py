"""edit_standing_chat: an agent changes its own settings - never silently.

Standing chats phase 2, Part D (D1). Editable: standing instructions,
schedule (cron), model, daily budget, fresh context, grants (tools).

- In conversation (the user is here): the first call previews the change;
  it applies on the user's yes in a later turn (the schedule tool's gate,
  src/agent/tools/pending_gate.py).
- In an unattended run: it files an approval request and the run pauses;
  the change applies only when the user approves it.
Grants therefore never widen without the user's explicit yes or approval.
The Daily Briefing runs on a stock prompt from code: its first instructions
edit stores the user's own copy (the preview says so).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict, cast

from croniter import croniter
from langchain_core.tools import tool

from src.agent.permissions import base_tool
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.pending_gate import keep_pending, unanswered
from src.agent.tools.request_approval import ApprovalRequestedException
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Agent

logger = get_logger(__name__)

TOOL_NAME = "edit_standing_chat"
PENDING_NAMESPACE = "standing_pending"
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
    from src.agent.tools import get_all_tool_names  # noqa: PLC0415 - cycle: tools imports this module

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
        if base_tool(grant) not in get_all_tool_names() and grant != ALL_GRANTS
    }
    if unknown:
        return f"Unknown tools: {', '.join(sorted(unknown))}."
    return None


def _describe(agent: Agent, changes: Change) -> str:
    """The change in words: what the user is agreeing to."""
    lines: list[str] = []
    if "instructions" in changes:
        lines.append(f"- Instructions become:\n  {changes['instructions']}")
        if agent.system_type and not agent.system_prompt:
            lines.append("  (this replaces the built-in prompt with your own copy)")
    if "schedule" in changes:
        lines.append(
            f"- Schedule: `{agent.schedule}` -> `{changes['schedule']}` ({agent.timezone})"
        )
    if "model" in changes:
        lines.append(f"- Model: {agent.model} -> {changes['model']}")
    if "budget_usd" in changes:
        lines.append(f"- Daily budget: ${changes['budget_usd']:.2f}")
    if "fresh_context" in changes:
        state = (
            "each run starts fresh" if changes["fresh_context"] else "runs see this chat's history"
        )
        lines.append(f"- History: {state}")
    if "grants" in changes:
        before = set(agent.tool_permissions or [ALL_GRANTS])
        after = set(changes["grants"])
        added, removed = sorted(after - before), sorted(before - after)
        lines.append(
            f"- Tools: {', '.join(sorted(after)) or 'none'}"
            + (f" (new access: {', '.join(added)})" if added else "")
            + (f" (removed: {', '.join(removed)})" if removed else "")
        )
    return "\n".join(lines)


def apply_standing_changes(job_id: str, user_id: str, changes: Change) -> Agent | None:
    """Apply an approved change to an agent (its chat and its job)."""
    grants = changes.get("grants", ...)
    agent = db.update_agent(
        job_id,
        user_id,
        system_prompt=changes.get("instructions", ...),
        schedule=changes.get("schedule", ...),
        model=changes.get("model", ...),
        budget_limit=changes.get("budget_usd", ...),
        fresh_context=changes.get("fresh_context", ...),
        tool_permissions=None if isinstance(grants, list) and ALL_GRANTS in grants else grants,
    )
    logger.info(
        "Standing chat settings changed",
        extra={"user_id": user_id, "job_id": job_id, "fields": sorted(changes)},
    )
    return agent


def _request_approval(agent: Agent, changes: Change) -> str:
    """Unattended: file the change for the user's approval and pause the run."""
    description = f"Change {agent.name}'s settings:\n{_describe(agent, changes)}"
    approval = db.create_approval_request(
        agent.id, agent.user_id, TOOL_NAME, dict(changes), description
    )
    raise ApprovalRequestedException(approval.id, description, TOOL_NAME)


def _in_chat(conversation_id: str, user_id: str, changes: Change, confirm: bool) -> str:
    conv = db.get_conversation(conversation_id, user_id)
    agent = (
        db.get_agent(conv.agent_id, user_id) if conv and conv.is_agent and conv.agent_id else None
    )
    if agent is None:
        return tool_error("This chat has no agent whose settings could change.", retriable=False)
    if not confirm:
        if problem := _invalid(changes):
            return tool_error(problem)
        keep_pending(user_id, PENDING_NAMESPACE, conversation_id, {"changes": changes})
        return (
            f"PREVIEW (nothing changed yet):\n{_describe(agent, changes)}\n\n"
            "Show this to the user and ask; call edit_standing_chat(confirm=true) only after "
            "they agree in their reply."
        )
    raw = db.kv_get(user_id, PENDING_NAMESPACE, conversation_id)
    if not raw:
        return tool_error("Nothing was previewed in this chat: preview the change first.")
    pending: dict[str, Change] = json.loads(raw)
    if unanswered(conversation_id, pending):
        return tool_error(
            "The user has not answered the preview yet - show it and ask them; confirm only "
            "after they agree in their reply."
        )
    db.kv_delete(user_id, PENDING_NAMESPACE, conversation_id)
    apply_standing_changes(agent.id, user_id, pending["changes"])
    return f"Updated {agent.name}:\n{_describe(agent, pending['changes'])}"


@tool
def edit_standing_chat(
    instructions: str | None = None,
    schedule: str | None = None,
    model: str | None = None,
    budget_usd: float | None = None,
    fresh_context: bool | None = None,
    grants: list[str] | None = None,
    confirm: bool = False,
) -> str:
    """Change this agent's own settings - its standing instructions, schedule,
    model, daily budget, history or tools - always with the user's agreement.

    Talking with the user: call it WITHOUT confirm - it returns a preview and
    changes nothing. Show the preview and ask; only after they agree in their
    reply, call it with confirm=true (no other fields): it applies exactly the
    previewed change. During a scheduled run (the user is away) it asks the
    user for approval instead and the run pauses until they answer.

    Args:
        instructions: The full new standing instructions (not a diff).
        schedule: Cron in the agent's timezone, e.g. "30 6 * * *" (daily 06:30),
            "0 18 * * 5" (Fridays 18:00).
        model: A model id.
        budget_usd: Daily budget for the agent's own runs, in USD.
        fresh_context: true = each run starts fresh; false = runs see this chat.
        grants: The complete list of tools the agent may use (e.g. ["garmin_connect"]).
        confirm: true only after the user agreed to the preview in their reply.
    """
    from src.agent.executor import get_agent_context  # noqa: PLC0415 - cycle: executor imports the tools

    changes = _changes(
        instructions=instructions,
        schedule=schedule,
        model=model,
        budget_usd=budget_usd,
        fresh_context=fresh_context,
        grants=grants,
    )
    run = get_agent_context()
    if run is not None:  # unattended: only ever a request for approval
        if problem := _invalid(changes):
            return tool_error(problem)
        return _request_approval(run.agent, changes)
    conversation_id, user_id = get_conversation_context()
    if not conversation_id or not user_id:
        return tool_error("No conversation context available.", retriable=False)
    return _in_chat(conversation_id, user_id, changes, confirm)
