"""What a standing chat adds to an ordinary chat turn.

Agents and sports / language programs are standing chats
(docs/superpowers/specs/2026-11-08-standing-chats-design.md): writing in one is
an ordinary chat turn - the user's full chat tools, facts, freshness, cache,
compaction - plus the chat's standing instructions (an agent's goals, a
program's coaching prompt), its data (a program's stored kv data) and the kv
namespace its `kv_store` writes to. Loaded once per turn.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from src.agent.daily_briefing import resolve_agent_system_prompt
from src.agent.prompt_programs import PROGRAM_QUICK_ACTION_NOTE, format_program_kv_data
from src.agent.prompt_texts.language import LANGUAGE_TUTOR_SYSTEM_PROMPT
from src.agent.prompt_texts.sports import SPORTS_TRAINER_SYSTEM_PROMPT
from src.agent.standing import StandingContext
from src.api.helpers.program_context import load_language_context, load_sports_context
from src.db.models import db
from src.utils.schedule_spec import describe_cron

if TYPE_CHECKING:
    from src.db.models import Conversation, User

# Where a program's coaching prompt points for its stored data
_DATA_POINTER = (
    "## Stored Data\n\nThe stored program data is in the Data part of this standing-chat section."
)


def _describe_schedule(schedule: str | None) -> str:
    if not schedule:
        return "it runs only when started by hand or by another agent"
    try:
        return f"it runs {describe_cron(schedule)}"
    except ValueError, IndexError:  # a cron the schedule tool would not build
        return f"it runs on the schedule `{schedule}`"


def _agent_context(conv: Conversation, user: User) -> StandingContext | None:
    agent = db.get_agent(conv.agent_id or "", user.id)
    if agent is None:
        return None
    goals = resolve_agent_system_prompt(agent) or "(no instructions yet)"
    instructions = (
        f'This chat belongs to the agent "{agent.name}"; {_describe_schedule(agent.schedule)} '
        "and its reports appear in this chat. The user is here now, talking to it directly.\n\n"
        f"Its standing instructions:\n{goals}"
    )
    return StandingContext(
        "agent", agent.name, instructions, None, f"agent:{agent.id}", agent_id=agent.id
    )


def standing_for_program(
    kind: Literal["sports", "language"], context: Mapping[str, object]
) -> StandingContext:
    """A program chat's standing context from its loaded program context
    ({program_name, program_id, kv_data}; program_context.py) - shared with
    the eval harness so evals see what production builds."""
    template = SPORTS_TRAINER_SYSTEM_PROMPT if kind == "sports" else LANGUAGE_TUTOR_SYSTEM_PROMPT
    instructions = (
        template.format(
            program_name=context["program_name"],
            program_id=context["program_id"],
            kv_data_section=_DATA_POINTER,
        )
        + PROGRAM_QUICK_ACTION_NOTE
    )
    return StandingContext(
        kind,
        str(context["program_name"]),
        instructions,
        format_program_kv_data(kind, context),
        kind,
    )


def _program_context(
    kind: Literal["sports", "language"], conv: Conversation, user: User
) -> StandingContext | None:
    program_id = conv.sports_program if kind == "sports" else conv.language_program
    load = load_sports_context if kind == "sports" else load_language_context
    context = load(user.id, program_id or "")
    return standing_for_program(kind, context) if context is not None else None


def load_standing_context(conv: Conversation, user: User) -> StandingContext | None:
    """The chat's standing context; None for ordinary chats and the planner."""
    if conv.is_agent:
        return _agent_context(conv, user)
    if conv.is_sports:
        return _program_context("sports", conv, user)
    if conv.is_language:
        return _program_context("language", conv, user)
    return None
