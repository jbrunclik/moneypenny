"""create_standing_chat: a new agent by talking (standing chats phase 3, F1).

"Be my cycle coach, check my Garmin every evening and ask how I feel" in an
ordinary chat previews a standing chat with a job: its name, instructions,
schedule and tools - each tool that can change things spelled out. It is
created on the user's yes in a later turn (the pending gate shared with
schedule and edit_standing_chat), with exactly the previewed settings. Never
in a standing chat or an unattended run.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agent.permissions import WRITE_SUFFIX, base_tool
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.pending_gate import expired, keep_pending, unanswered
from src.agent.tools.standing_settings import ALL_GRANTS, unknown_grants
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.schedule_spec import ScheduleError, describe_cron, recurring_cron
from src.utils.threat_patterns import find_injection

logger = get_logger(__name__)

PENDING_NAMESPACE = "standing_create_pending"
_TOOL_LABELS = {
    "todoist": "Todoist",
    "google_calendar": "Calendar",
    "garmin_workout": "Garmin workouts",
    "rouvy_workout": "Rouvy",
}


def _tools_text(grants: list[str]) -> str:
    """Each tool, and whether it can change things there."""
    if ALL_GRANTS in grants:
        return "all tools, including changing things in your Todoist, Calendar and workouts"
    writes = {base_tool(g) for g in grants if g.endswith(WRITE_SUFFIX)}
    parts = []
    for tool_name in dict.fromkeys(base_tool(g) for g in grants):
        if tool_name in writes:
            parts.append(f"{tool_name} (can change your {_TOOL_LABELS.get(tool_name, tool_name)})")
        else:
            parts.append(f"{tool_name} (read only)")
    return ", ".join(parts) or "web search only"


def _schedule(days: list[str] | None, time: str | None) -> str | ScheduleError | None:
    """The cron for days + time; None runs only on demand."""
    if not days and not time:
        return None
    return recurring_cron(days or ["daily"], time or "")


def _refusal(user_id: str, name: str, instructions: str, grants: list[str]) -> str | None:
    if not name.strip() or not instructions.strip():
        return "Give the new chat a name and its standing instructions."
    for value in (name, instructions):
        if reason := find_injection(value):
            return f"Refused: {reason}. Describe it in your own words."
    if db.get_agent_by_name(user_id, name.strip()) is not None:
        return f'An agent named "{name.strip()}" exists already - pick another name.'
    cap = Config.STANDING_CHATS_MAX_PER_USER
    if len(db.list_agents_with_status(user_id)) >= cap:
        return f"You have reached the limit of {cap} standing chats; remove one first."
    if unknown := unknown_grants(grants):
        return f"Unknown tools: {', '.join(sorted(unknown))}."
    return None


def _preview(spec: dict[str, object]) -> str:
    cron = spec["schedule"]
    when = describe_cron(str(cron)) if cron else "only when you ask it"
    return (
        f'PREVIEW (nothing created yet): a new standing chat "{spec["name"]}" under Agents.\n'
        f"- Instructions: {spec['instructions']}\n"
        f"- Runs: {when} ({Config.APP_TIMEZONE})\n"
        f"- Tools: {_tools_text(list(spec['grants']))}\n"  # type: ignore[call-overload]
        f"- Each run {'starts fresh' if spec['fresh_context'] else 'sees the chat so far'}\n\n"
        "Show this to the user and ask; call create_standing_chat(confirm=true) only after "
        "they agree in their reply."
    )


def _confirm(conversation_id: str, user_id: str) -> str:
    raw = db.kv_get(user_id, PENDING_NAMESPACE, conversation_id)
    if not raw:
        return tool_error("Nothing was previewed in this chat: preview it first.")
    spec = json.loads(raw)
    if expired(conversation_id, spec):
        db.kv_delete(user_id, PENDING_NAMESPACE, conversation_id)
        return tool_error("That preview expired - the user moved on. Preview again and ask.")
    if unanswered(conversation_id, spec):
        return tool_error(
            "The user has not answered the preview yet - show it and ask them; confirm only "
            "after they agree in their reply."
        )
    if refusal := _refusal(user_id, spec["name"], spec["instructions"], spec["grants"]):
        return tool_error(refusal)
    db.kv_delete(user_id, PENDING_NAMESPACE, conversation_id)
    grants = spec["grants"]
    agent = db.create_agent(
        user_id,
        spec["name"],
        system_prompt=spec["instructions"],
        schedule=spec["schedule"],
        timezone=Config.APP_TIMEZONE,
        tool_permissions=None if ALL_GRANTS in grants else grants,
        fresh_context=spec["fresh_context"],
    )
    logger.info("Standing chat created by talking", extra={"user_id": user_id, "job_id": agent.id})
    return (
        f'Created "{agent.name}" under Agents: #/conversations/{agent.conversation_id} - its '
        "reports arrive there. Tell the user where to find it."
    )


@tool
def create_standing_chat(
    name: str = "",
    instructions: str = "",
    days: list[str] | None = None,
    time: str | None = None,
    grants: list[str] | None = None,
    fresh_context: bool = True,
    confirm: bool = False,
) -> str:
    """Set up a new standing chat - a lasting role with its own schedule, like
    "be my cycle coach, check my Garmin every evening and ask how I feel" or
    "watch my bills every Monday". It appears under Agents with its own chat.
    For a one-off reminder or a single check, use schedule instead.

    Call it WITHOUT confirm first: it returns a preview and creates nothing.
    Show the preview and ask; only after the user agrees in their reply, call
    it with confirm=true (no other fields): it creates exactly what was
    previewed.

    Args:
        name: A short name, e.g. "Cycling coach".
        instructions: Its standing instructions, written as to the agent.
        days: mon..sun, or ["daily"] / ["weekdays"] / ["weekends"]; omit (and
            time) for a chat that runs only when asked.
        time: HH:MM, local time.
        grants: The tools it may use on its runs, e.g. ["garmin_connect"]. A
            write level ("todoist:write") lets it change things there;
            without it, changes wait for the user's approval.
        fresh_context: true = each run starts fresh; false = runs see the chat.
        confirm: true only after the user agreed to the preview in their reply.
    """
    from src.agent.executor import get_agent_context  # noqa: PLC0415 - cycle: executor imports the tools

    if get_agent_context() is not None:
        return tool_error("A scheduled run cannot set up new chats.", retriable=False)
    conversation_id, user_id = get_conversation_context()
    if not conversation_id or not user_id:
        return tool_error("No conversation context available.", retriable=False)
    conv = db.get_conversation(conversation_id, user_id)
    if conv is not None and (conv.is_agent or conv.is_sports or conv.is_language):
        return tool_error(
            "This is a standing chat: set up new ones from an ordinary chat.", retriable=False
        )
    if confirm:
        return _confirm(conversation_id, user_id)
    grant_list = list(grants or [])
    if refusal := _refusal(user_id, name, instructions, grant_list):
        return tool_error(refusal)
    cron = _schedule(days, time)
    if isinstance(cron, ScheduleError):
        return tool_error(str(cron))
    spec: dict[str, object] = {
        "name": name.strip(),
        "instructions": instructions.strip(),
        "schedule": cron,
        "grants": grant_list,
        "fresh_context": fresh_context,
    }
    keep_pending(user_id, PENDING_NAMESPACE, conversation_id, spec)
    return _preview(spec)
