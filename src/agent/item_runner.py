"""Run a watcher or recurring item, and deliver an item's result into its chat.

A run uses the agent machinery (ChatAgent in autonomous mode, the agent
context that permission checks and the schedule tool read) with an in-memory
Agent - no agent row. An unattended run reads untrusted web pages, so it gets
only the web tools (RUN_TOOL_NAMES: no files, no kv store), not the user's
memories, and a stored report that looks like injected instructions is not
replayed into the next run. Its cost is recorded against the item's chat: on the
delivered message, or for a silent run under a synthetic message id.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from src.agent.agent import ChatAgent
from src.agent.executor import (
    AgentContext,
    clear_agent_context,
    is_silent_reply,
    set_agent_context,
)
from src.agent.prompt_texts.scheduled_items import (
    NO_PREVIOUS_RESULT,
    RECURRING_RUN_PROMPT,
    WATCHER_RUN_PROMPT,
)
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import get_tools_for_agent, set_conversation_context
from src.config import Config
from src.db.models import Agent, db
from src.enums import MessageRole
from src.services.costs import calculate_and_save_message_cost
from src.services.push import send_push_to_user
from src.utils.clock import utc_now
from src.utils.logging import get_logger
from src.utils.threat_patterns import find_injection

if TYPE_CHECKING:
    from src.db.models import Message, User
    from src.db.models.dataclasses import ItemKind, ScheduledItem

logger = get_logger(__name__)

_MARKS = r"[`*]*"
_DONE_AT_START = re.compile(rf"^\s*{_MARKS}\[done\]{_MARKS}\.?\s*", re.IGNORECASE)
_DONE_AT_END = re.compile(rf"\s*{_MARKS}\[done\]{_MARKS}\.?\s*$", re.IGNORECASE)
_NAME_MAX_CHARS = 40
RUN_TOOL_NAMES = frozenset({"web_search", "fetch_url", "research"})
_PUSH_BODY_CHARS = 160
_KIND_TITLES: dict[str, str] = {
    "reminder": "Reminder",
    "check_in": "Check-in",
    "watcher": "Watcher",
    "recurring": "Recurring",
}


@dataclass
class RunOutcome:
    """What a run produced: nothing new, a report, the end condition met, or a failure."""

    status: Literal["silent", "report", "done", "failed"]
    text: str
    error: str | None = None
    # Saves the run's cost against a message id (the delivered turn, or a
    # synthetic one for a silent run); None when there is no cost to record
    record_cost: Callable[[str], None] | None = None


def parse_reply(raw: str) -> RunOutcome:
    """Silent, done (the [DONE] marker at the very start or end), or a report."""
    if is_silent_reply(raw):
        return RunOutcome("silent", "")
    for pattern in (_DONE_AT_START, _DONE_AT_END):
        if pattern.search(raw):
            return RunOutcome("done", pattern.sub("", raw, count=1).strip())
    return RunOutcome("report", raw.strip())


def _ephemeral_agent(item: ScheduledItem) -> Agent:
    now = utc_now()
    return Agent(
        id=f"item-{item.id}",
        user_id=item.user_id,
        conversation_id=item.conversation_id,
        name=item.text[:_NAME_MAX_CHARS],
        description=None,
        system_prompt=item.text,
        schedule=item.schedule,
        timezone=Config.APP_TIMEZONE,
        enabled=True,
        tool_permissions=[],  # narrowed further to RUN_TOOL_NAMES in _chat
        model=Config.DEFAULT_MODEL,
        created_at=now,
        updated_at=now,
        fresh_context=True,
    )


def _run_message(item: ScheduledItem) -> str:
    previous = item.last_result or NO_PREVIOUS_RESULT
    if find_injection(previous):
        previous = NO_PREVIOUS_RESULT
    if item.kind == "watcher":
        return WATCHER_RUN_PROMPT.format(
            text=item.text, end_condition=item.end_condition or "", last_result=previous
        )
    return RECURRING_RUN_PROMPT.format(text=item.text, last_result=previous)


def _chat(
    agent: Agent, user: User, item: ScheduledItem, request_id: str
) -> tuple[str, Callable[[str], None]]:
    tools = [t for t in get_tools_for_agent(agent) if t.name in RUN_TOOL_NAMES]
    chat_agent = ChatAgent(
        model_name=agent.model,
        anonymous_mode=False,
        is_planning=False,
        is_autonomous=True,
        agent_context={
            "name": agent.name,
            "description": agent.description,
            "schedule": agent.schedule,
            "timezone": agent.timezone,
            "goals": agent.system_prompt,
            "tools": [t.name for t in tools],
            "trigger_type": "scheduled",
            "fresh_context": True,
        },
        tools=tools,
    )
    raw, _, usage, _ = chat_agent.chat_batch(
        text=_run_message(item),
        files=None,
        history=[],
        force_tools=None,
        user_name=user.name,
        user_id=None,  # only feeds the user's memories in: kept out of unattended runs
        custom_instructions=user.custom_instructions,
        is_planning=False,
        conversation_id=item.conversation_id,
    )
    tool_results = get_full_tool_results(request_id)  # pops: read once, now

    def record_cost(message_id: str) -> None:
        calculate_and_save_message_cost(
            message_id,
            item.conversation_id,
            item.user_id,
            agent.model,
            usage,
            tool_results,
            len(raw),
            mode="item",
        )

    return raw, record_cost


def run_model_item(item: ScheduledItem, user: User) -> RunOutcome:
    """Run a watcher or recurring item; never raises (errors are 'failed')."""
    agent = _ephemeral_agent(item)
    request_id = str(uuid.uuid4())
    set_current_request_id(request_id)
    set_conversation_context(item.conversation_id, user.id)
    set_agent_context(AgentContext(agent=agent, user=user, trigger_chain=[agent.id]))
    try:
        raw, record_cost = _chat(agent, user, item, request_id)
    except Exception as e:  # any tool/model/approval error: the scheduler counts a failure
        logger.warning(
            "Scheduled item run failed",
            extra={"item_id": item.id, "user_id": user.id, "error": str(e)},
            exc_info=True,
        )
        return RunOutcome("failed", "", error=str(e))
    finally:
        set_current_request_id(None)
        set_conversation_context(None, None)
        clear_agent_context()
    outcome = parse_reply(raw)
    outcome.record_cost = record_cost
    if outcome.status == "silent":
        record_cost(f"silent:{uuid.uuid4()}")
    return outcome


def delivery_label(kind: ItemKind, when: datetime, tz: str, outcome: str | None = None) -> str:
    """'Check-in · Fri 18:00', 'Watcher · found', 'Recurring · Mon 09:00'..."""
    title = _KIND_TITLES[kind]
    if outcome:
        return f"{title} · {outcome}"
    return f"{title} · {when.astimezone(ZoneInfo(tz)).strftime('%a %H:%M')}"


def deliver(
    item: ScheduledItem,
    text: str,
    label: str,
    push: bool = True,
    outcome: RunOutcome | None = None,
) -> Message:
    """Post `text` into the item's chat as a labelled assistant turn (and push it)."""
    message = db.add_message(
        item.conversation_id,
        MessageRole.ASSISTANT,
        text,
        delivery={"kind": item.kind, "label": label},
    )
    if outcome is not None and outcome.record_cost is not None:
        outcome.record_cost(message.id)
    if push:
        send_push_to_user(
            item.user_id,
            _KIND_TITLES[item.kind],
            text.strip().split("\n", 1)[0][:_PUSH_BODY_CHARS],
            url=f"/#/conversations/{item.conversation_id}",
            tag=f"item-{item.id}",
        )
    logger.info(
        "Scheduled item delivered",
        extra={"item_id": item.id, "user_id": item.user_id, "label": label, "pushed": push},
    )
    return message
