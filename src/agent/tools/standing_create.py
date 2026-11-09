"""create_standing_chat: a new agent by talking (standing chats phase 3, F1).

"Be my cycle coach, check my Garmin every evening and ask how I feel" in an
ordinary chat previews a standing chat with a job: its name, instructions,
schedule and tools - each tool that can change things spelled out - as a
proposal card (src/agent/proposals.py, shared with schedule and
edit_standing_chat). The server creates it with exactly those settings when
the user approves. Never in a standing chat or an unattended run.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, TypedDict, cast

from langchain_core.tools import tool

from src.agent.permissions import WRITE_LEVEL_TOOLS, WRITE_SUFFIX, base_tool
from src.agent.proposals import ProposalFailedError, card_shown, file_proposal, register_kind
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.standing_settings import ALL_GRANTS, unknown_grants
from src.config import Config
from src.constants import AGENT_INSTRUCTIONS_MAX_CHARS, AGENT_NAME_MAX_CHARS
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.schedule_spec import ScheduleError, describe_cron, recurring_cron
from src.utils.threat_patterns import find_injection

if TYPE_CHECKING:
    from src.db.models import Proposal, ProposalOption

logger = get_logger(__name__)

PROPOSAL_KIND = "create_agent"
_APPROVE_LABEL = "Create agent"


class Spec(TypedDict):
    """The proposed standing chat (the proposal's payload)."""

    name: str
    instructions: str
    schedule: str | None
    grants: list[str]
    fresh_context: bool


_TOOL_LABELS = {
    "todoist": "Todoist",
    "google_calendar": "Calendar",
    "garmin_workout": "Garmin workouts",
    "rouvy_workout": "Rouvy",
}


# Tools that act without a write level: what each one lets a run do
_ACTING_TOOLS = {
    "browser": "can browse and fill in web forms",
    "create_file": "can attach files",
    "delegate_task": "can hand work to a helper agent",
    "delete_place": "can delete your saved places",
    "execute_code": "can run code",
    "generate_image": "can create images",
    "kv_store": "keeps its own notes",
    "manage_memory": "can edit your memories",
    "save_place": "can save places for you",
    "trigger_agent": "can start your other agents",
    "whatsapp": "can send WhatsApp messages",
}
# What every run may use without a grant (ALWAYS_SAFE_TOOLS, in words)
_BASE_TOOLS_TEXT = "web lookups, files, places lookups and its own notes"


def _tool_text(tool_name: str, writes: set[str]) -> str:
    if tool_name in writes:
        return f"{tool_name} (can change your {_TOOL_LABELS.get(tool_name, tool_name)})"
    if tool_name in WRITE_LEVEL_TOOLS:
        return f"{tool_name} (reads; changes wait for your approval)"
    return f"{tool_name} ({_ACTING_TOOLS.get(tool_name, 'read only')})"


def _tools_text(grants: list[str]) -> str:
    """Each tool, and what it lets a run do - changes spelled out."""
    writes = {base_tool(g) for g in grants if g.endswith(WRITE_SUFFIX)}
    parts = [_tool_text(t, writes) for t in dict.fromkeys(base_tool(g) for g in grants)]
    return ", ".join(parts) or f"none beyond {_BASE_TOOLS_TEXT}"


def _schedule(days: list[str] | None, time: str | None) -> str | ScheduleError | None:
    """The cron for days + time; None runs only on demand."""
    if not days and not time:
        return None
    if not time:
        return ScheduleError(
            "Give a time (HH:MM) for those days, or no days for a chat run only on demand."
        )
    return recurring_cron(days or ["daily"], time)


def _refusal(user_id: str, name: str, instructions: str, grants: list[str]) -> str | None:
    if not name.strip() or not instructions.strip():
        return "Give the new chat a name and its standing instructions."
    if len(name.strip()) > AGENT_NAME_MAX_CHARS:
        return f"The name is too long (at most {AGENT_NAME_MAX_CHARS} characters)."
    if len(instructions.strip()) > AGENT_INSTRUCTIONS_MAX_CHARS:
        return f"The instructions are too long (at most {AGENT_INSTRUCTIONS_MAX_CHARS} characters)."
    for value in (name, instructions):
        if reason := find_injection(value):
            return f"Refused: {reason}. Describe it in your own words."
    if db.get_standing_chat_by_name(user_id, name.strip()) is not None:
        return f'An agent named "{name.strip()}" exists already - pick another name.'
    cap = Config.STANDING_CHATS_MAX_PER_USER
    if len(db.list_standing_chats(user_id)) >= cap:
        return f"You have reached the limit of {cap} standing chats; remove one first."
    if ALL_GRANTS in grants:
        return (
            "All tools cannot be granted from a chat: list the tools it needs (the user can "
            "widen it later under Agents)."
        )
    if unknown := unknown_grants(grants):
        return f"Unknown tools: {', '.join(sorted(unknown))}."
    return None


def _settings(spec: Spec) -> dict[str, object]:
    """What the card shows: every setting, the tools and what they can change too."""
    cron = spec["schedule"]
    when = describe_cron(cron) if cron else "only when you ask it"
    return {
        "Instructions": spec["instructions"],
        "Runs": f"{when} ({Config.APP_TIMEZONE})",
        "Tools": _tools_text(spec["grants"]),
        "Each run": "starts fresh" if spec["fresh_context"] else "sees the chat so far",
        "Daily budget": f"${Config.STANDING_CREATE_BUDGET_USD:.2f} (changeable under Agents)",
    }


def apply_create_agent(proposal: Proposal, option: ProposalOption) -> str:
    """Create exactly the approved standing chat (the proposal's payload)."""
    spec = cast("Spec", option["payload"])
    user_id = proposal.user_id
    if refusal := _refusal(user_id, spec["name"], spec["instructions"], spec["grants"]):
        raise ProposalFailedError(refusal)
    try:
        chat = db.create_standing_chat(
            user_id,
            spec["name"],
            spec["instructions"],
            schedule=spec["schedule"],
            timezone=Config.APP_TIMEZONE,
            grants=spec["grants"],
            fresh_context=spec["fresh_context"],
            budget_usd=Config.STANDING_CREATE_BUDGET_USD,
        )
    except sqlite3.IntegrityError:  # created meanwhile (another request, another device)
        raise ProposalFailedError(
            f'An agent named "{spec["name"]}" exists already - pick another name.'
        ) from None
    logger.info("Standing chat created by talking", extra={"user_id": user_id, "job_id": chat.id})
    return f'Created "{chat.name}" under Agents - its reports arrive in its own chat.'


register_kind(PROPOSAL_KIND, apply_create_agent)


@tool
def create_standing_chat(
    name: str = "",
    instructions: str = "",
    days: list[str] | None = None,
    time: str | None = None,
    grants: list[str] | None = None,
    fresh_context: bool = True,
) -> str:
    """Set up a new standing chat - a lasting role with its own schedule, like
    "be my cycle coach, check my Garmin every evening and ask how I feel" or
    "watch my bills every Monday". It appears under Agents with its own chat.
    For a one-off reminder or a single check, use schedule instead.

    It shows the user a card with every setting (and what each tool can
    change) and creates nothing itself: the server creates exactly that when
    the user approves (on the card, or by replying yes). Never say it exists
    before you hear it was approved.

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
    """
    from src.agent.run_context import get_job_context  # noqa: PLC0415 - cycle: run_context imports the tools

    if get_job_context() is not None:
        return tool_error("A scheduled run cannot set up new chats.", retriable=False)
    conversation_id, user_id = get_conversation_context()
    if not conversation_id or not user_id:
        return tool_error("No conversation context available.", retriable=False)
    conv = db.get_conversation(conversation_id, user_id)
    if conv is not None and (conv.is_agent or conv.is_sports or conv.is_language):
        return tool_error(
            "This is a standing chat: set up new ones from an ordinary chat.", retriable=False
        )
    grant_list = list(grants or [])
    if refusal := _refusal(user_id, name, instructions, grant_list):
        return tool_error(refusal)
    cron = _schedule(days, time)
    if isinstance(cron, ScheduleError):
        return tool_error(str(cron))
    spec: Spec = {
        "name": name.strip(),
        "instructions": instructions.strip(),
        "schedule": cron,
        "grants": grant_list,
        "fresh_context": fresh_context,
    }
    proposal = file_proposal(
        PROPOSAL_KIND,
        f'New agent "{spec["name"]}" under Agents',
        _settings(spec),
        [{"label": _APPROVE_LABEL, "description": "", "payload": dict(spec)}],
    )
    return card_shown(proposal)
