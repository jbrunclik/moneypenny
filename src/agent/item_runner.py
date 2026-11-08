"""Run a watcher, a recurring item or a standing job; deliver a result into its chat.

A run uses the agent machinery (ChatAgent in autonomous mode, the agent
context that permission checks and the schedule tool read) with an in-memory
Agent - no agent row.

- A light item (no grants) reads untrusted web pages, so it gets only the web
  tools (RUN_TOOL_NAMES: no files, no kv store), not the user's memories, and
  a stored report that looks like injected instructions is not replayed into
  the next run. In a standing chat it also sees the chat's instructions and
  state, so a coach's check-in knows the program.
- A standing job (grants set: an agent's schedule) runs with its grants (plus
  the safe basics, request_approval and kv_store), its model, the chat's
  standing context, and the chat's history unless fresh_context; the user's
  memories only when manage_memory is granted. Its synthetic Agent carries the
  job's id, so approvals and execution rows name the job, and its cost rows
  carry job_id (its daily budget).

Cost is recorded against the item's chat: on the delivered message, or for a
silent run under a synthetic message id.
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
    build_trigger_message,
    clear_agent_context,
    is_silent_reply,
    record_approval_request,
    run_history,
    set_agent_context,
)
from src.agent.prompt_texts.scheduled_items import (
    NO_PREVIOUS_RESULT,
    RECURRING_RUN_PROMPT,
    STANDING_JOB_TASK,
    WATCHER_RUN_PROMPT,
)
from src.agent.standing_context import load_standing_context
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import get_tools_for_agent, set_conversation_context
from src.agent.tools.request_approval import ApprovalRequestedException
from src.config import Config
from src.db.models import Agent, db
from src.enums import MessageRole
from src.services.costs import calculate_and_save_message_cost
from src.services.push import send_push_to_user
from src.utils.clock import utc_now
from src.utils.logging import get_logger
from src.utils.threat_patterns import find_injection

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from src.db.models import Message, User
    from src.db.models.dataclasses import ItemKind, ScheduledItem

logger = get_logger(__name__)

_MARKS = r"[`*]*"
# [DONE] opening the reply (with a following '.', ':' or dash), closing it,
# or alone on a line of its own anywhere - never quoted inside a sentence
_DONE_AT_START = re.compile(
    rf"^\s*{_MARKS}\[done\]{_MARKS}\s*[.:\-\u2013\u2014]?\s*", re.IGNORECASE
)
_DONE_AT_END = re.compile(rf"\s*{_MARKS}\[done\]{_MARKS}\.?\s*$", re.IGNORECASE)
_DONE_LINE = re.compile(
    rf"^[ \t]*{_MARKS}\[done\]{_MARKS}\.?[ \t]*(?:\n|$)", re.IGNORECASE | re.MULTILINE
)
_NAME_MAX_CHARS = 40
ALL_GRANTS = "*"
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

    # "approval": a standing job paused on an approval request (already
    # posted into the chat and pushed)
    status: Literal["silent", "report", "done", "failed", "approval"]
    text: str
    error: str | None = None
    # Saves the run's cost against a message id (the delivered turn, or a
    # synthetic one for a silent run); None when there is no cost to record
    record_cost: Callable[[str], None] | None = None


def parse_reply(raw: str) -> RunOutcome:
    """Silent, done (the [DONE] marker at the very start or end), or a report."""
    if is_silent_reply(raw):
        return RunOutcome("silent", "")
    for pattern in (_DONE_AT_START, _DONE_AT_END, _DONE_LINE):
        if pattern.search(raw):
            return RunOutcome("done", pattern.sub("", raw, count=1).strip())
    return RunOutcome("report", raw.strip())


def _tool_permissions(item: ScheduledItem) -> list[str] | None:
    """The synthetic Agent's permission list: [] for a light item (narrowed
    to RUN_TOOL_NAMES), None (unrestricted) for an all-tools job."""
    if item.grants is None:
        return []
    return None if ALL_GRANTS in item.grants else list(item.grants)


def _standing_goals(item: ScheduledItem, user: User) -> str:
    """The run's goals: the item's text, after the chat's standing context
    (instructions and state) when the chat is a standing chat."""
    conv = db.get_conversation(item.conversation_id, user.id)
    standing = load_standing_context(conv, user) if conv else None
    task = STANDING_JOB_TASK.format(text=item.text) if item.standing else item.text
    if standing is None:
        return task
    parts = [f"# This chat: {standing.name}", standing.instructions]
    # A light item reads the web with no grants: never hand it the chat's
    # personal data (an injected page could send it out via fetch_url)
    if standing.data and item.standing:
        parts.append(standing.data)
    return "\n\n".join([*parts, task])


def _ephemeral_agent(item: ScheduledItem, user: User) -> Agent:
    now = utc_now()
    return Agent(
        # A standing job's approvals and execution rows name the job itself
        id=item.id if item.standing else f"item-{item.id}",
        user_id=item.user_id,
        conversation_id=item.conversation_id,
        name=item.text[:_NAME_MAX_CHARS],
        description=None,
        system_prompt=_standing_goals(item, user),
        schedule=item.schedule,
        timezone=item.timezone or Config.APP_TIMEZONE,
        enabled=True,
        tool_permissions=_tool_permissions(item),
        model=item.model or Config.DEFAULT_MODEL,
        created_at=now,
        updated_at=now,
        fresh_context=item.fresh_context if item.standing else True,
        budget_limit=item.budget_usd,
    )


def _remembers(item: ScheduledItem) -> bool:
    """Memories feed only standing jobs granted manage_memory (or all tools)."""
    return item.grants is not None and bool({"manage_memory", ALL_GRANTS} & set(item.grants))


def _run_message(item: ScheduledItem, trigger: str, message: str | None) -> str:
    if item.standing and trigger == "manual" and message:
        return message  # an approval's outcome resuming the run
    if item.standing:
        return build_trigger_message(trigger, message)
    previous = item.last_result or NO_PREVIOUS_RESULT
    if find_injection(previous):
        previous = NO_PREVIOUS_RESULT
    if item.kind == "watcher":
        return WATCHER_RUN_PROMPT.format(
            text=item.text, end_condition=item.end_condition or "", last_result=previous
        )
    return RECURRING_RUN_PROMPT.format(text=item.text, last_result=previous)


RunTrigger = Literal["scheduled", "manual", "agent_trigger"]


def _tools(agent: Agent, item: ScheduledItem) -> list[BaseTool]:
    tools = get_tools_for_agent(agent)
    return tools if item.standing else [t for t in tools if t.name in RUN_TOOL_NAMES]


def _chat(
    agent: Agent,
    user: User,
    item: ScheduledItem,
    request_id: str,
    run: tuple[RunTrigger, str | None],
) -> tuple[str, Callable[[str], None]]:
    trigger, message = run
    tools = _tools(agent, item)
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
            "fresh_context": agent.fresh_context,
        },
        tools=tools,
        # The user's memories only for a job granted manage_memory; the rest
        # of the user context (language, saved places) always
        include_memories=_remembers(item),
    )
    # A resumed run's message was saved into the chat already (the approval
    # route): it is the run message, so it must not repeat in the history
    resumed = trigger == "manual" and message is not None
    history = (
        []
        if agent.fresh_context
        else run_history(agent, item.conversation_id, keep_last=not resumed)
    )
    raw, _, usage, _ = chat_agent.chat_batch(
        text=_run_message(item, trigger, message),
        files=None,
        history=history,
        force_tools=None,
        user_name=user.name,
        # Light items get no user context at all (web-reading, no grants)
        user_id=user.id if item.standing else None,
        custom_instructions=user.custom_instructions,
        is_planning=False,
        conversation_id=item.conversation_id,
    )
    tool_results = get_full_tool_results(request_id)  # pops: read once, now

    def record_cost(message_id: str) -> None:
        try:
            _save_cost(message_id)
        except Exception:  # the result reached the user: a lost cost row is not a failed run
            logger.warning(
                "Scheduled item cost not recorded", extra={"item_id": item.id}, exc_info=True
            )

    def _save_cost(message_id: str) -> None:
        calculate_and_save_message_cost(
            message_id,
            item.conversation_id,
            item.user_id,
            agent.model,
            usage,
            tool_results,
            len(raw),
            mode="item",
            job_id=item.id if item.standing else None,
        )

    return raw, record_cost


def run_model_item(
    item: ScheduledItem,
    user: User,
    *,
    trigger: RunTrigger = "scheduled",
    message: str | None = None,
    trigger_chain: list[str] | None = None,
) -> RunOutcome:
    """Run a watcher, recurring item or standing job; never raises (errors are 'failed').

    `message` carries a triggering agent's instructions or an approval's
    outcome into a standing job's run; `trigger_chain` the agents upstream.
    """
    agent = _ephemeral_agent(item, user)
    execution_id = db.create_execution(agent.id, trigger).id if item.standing else None
    request_id = str(uuid.uuid4())
    set_current_request_id(request_id)
    set_conversation_context(item.conversation_id, user.id)
    chain = [*(trigger_chain or []), agent.id]
    set_agent_context(AgentContext(agent=agent, user=user, trigger_chain=chain))
    try:
        raw, record_cost = _chat(agent, user, item, request_id, (trigger, message))
    except ApprovalRequestedException as e:
        if execution_id is None:  # a light item has no request_approval tool
            return RunOutcome("failed", "", error=str(e))
        record_approval_request(e, agent, user, item.conversation_id, execution_id)
        return RunOutcome("approval", "")
    except Exception as e:  # any tool/model error: the scheduler counts a failure
        logger.warning(
            "Scheduled item run failed",
            extra={"item_id": item.id, "user_id": user.id, "error": str(e)},
            exc_info=True,
        )
        if execution_id is not None:
            db.update_execution(execution_id, status="failed", error_message=str(e))
        return RunOutcome("failed", "", error=str(e))
    finally:
        set_current_request_id(None)
        set_conversation_context(None, None)
        clear_agent_context()
    if execution_id is not None:
        db.update_execution(execution_id, status="completed")
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


def _push_title(item: ScheduledItem) -> str:
    """A standing job's push is titled with its chat (the Daily Briefing, the
    coach); a light item's with its kind."""
    if item.standing:
        conv = db.get_conversation(item.conversation_id, item.user_id)
        if conv is not None and conv.title:
            return conv.title
    return _KIND_TITLES[item.kind]


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
        title, tag = _push_title(item), f"item-{item.id}"
        if item.standing:  # one notification per job, replaced by its next run
            tag = f"job-{item.id}"
        send_push_to_user(
            item.user_id,
            title,
            text.strip().split("\n", 1)[0][:_PUSH_BODY_CHARS],
            url=f"/#/conversations/{item.conversation_id}",
            tag=tag,
        )
    logger.info(
        "Scheduled item delivered",
        extra={"item_id": item.id, "user_id": item.user_id, "label": label, "pushed": push},
    )
    return message
