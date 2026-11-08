"""The unattended run's context and shared pieces.

Agents are standing jobs (standing chats phase 2): their runs go through
src/agent/item_runner.py. This module keeps what those runs share: the run
context permission checks read (AgentContext), the trigger message, the run's
history, recording an approval request, and the [SILENT] marker.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.conversation_compaction import build_compacted_history
from src.agent.history import enrich_history
from src.agent.tools.request_approval import (
    ApprovalRequestedException,
    build_approval_message,
)
from src.db.models import db
from src.enums import MessageRole
from src.services.push import send_push_to_user
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Agent, User

logger = get_logger(__name__)


# ============ Context Management ============


@dataclass
class AgentContext:
    """Context for the currently executing agent."""

    agent: Agent
    user: User
    trigger_chain: list[str]  # List of agent IDs in the trigger chain


# Context variable for the current agent execution
_agent_context: contextvars.ContextVar[AgentContext | None] = contextvars.ContextVar(
    "_agent_context", default=None
)


def get_agent_context() -> AgentContext | None:
    """Get the current agent execution context."""
    return _agent_context.get()


def set_agent_context(context: AgentContext | None) -> None:
    """Set the current agent execution context."""
    _agent_context.set(context)


def clear_agent_context() -> None:
    """Clear the current agent execution context."""
    _agent_context.set(None)


def get_trigger_chain() -> list[str]:
    """Get the current trigger chain (agent IDs)."""
    context = _agent_context.get()
    return context.trigger_chain if context else []


def build_trigger_message(trigger_type: str, extra_message: str | None = None) -> str:
    """Build the synthetic user message that starts an autonomous run.

    extra_message carries instructions from a triggering agent (trigger_agent's
    `message` arg). "Continue" is the legacy default and means "no message".
    """
    now = utc_now()
    templates = {
        "scheduled": f"[Scheduled run at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "manual": f"[Manual trigger at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "agent_trigger": f"[Triggered by another agent at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
    }
    message = templates.get(trigger_type, f"[Triggered: {trigger_type}]")
    extra = (extra_message or "").strip()
    if extra and extra != "Continue":
        message += f"\n\nMessage from triggering agent: {extra}"
    return message


def run_history(
    agent: Agent, conversation_id: str, *, keep_last: bool = False
) -> list[dict[str, Any]]:
    """The conversation history sent with the run (excluding the trigger message).

    Fresh-context agents run every turn from a clean slate (prior runs stay
    readable in the chat but aren't sent - right for report-style agents like
    the Daily Briefing). Others get it through the regular chat compaction -
    the same non-destructive summary + recent messages a chat turn uses, so
    the user's own turns in that chat and the runs never clash over it.
    """
    if agent.fresh_context:
        return []
    messages = db.get_messages(conversation_id)
    # An agent run just saved its trigger message (sent separately); a job run
    # saves none, so its newest message is real history (keep_last)
    kept = messages if keep_last else messages[:-1]
    return build_compacted_history(agent.user_id, conversation_id, enrich_history(kept))


def record_approval_request(
    e: ApprovalRequestedException,
    agent: Agent,
    user: User,
    conversation_id: str,
    execution_id: str,
) -> None:
    """Park the run on the approval the agent asked for and tell the user."""
    logger.info(
        "Agent requesting approval",
        extra={
            "agent_id": agent.id,
            "execution_id": execution_id,
            "approval_id": e.approval_id,
            "description": e.description,
        },
    )

    # Update execution status to waiting_approval
    db.update_execution(execution_id, status="waiting_approval")

    # Add a message to the conversation indicating approval is needed
    # Include approval ID in a parseable format for interactive UI
    approval_message = build_approval_message(
        e.approval_id, e.description, e.tool_name, sibling_results=e.sibling_results
    )
    db.add_message(conversation_id, MessageRole.ASSISTANT, approval_message)

    # The agent is blocked until the user reacts - the most
    # time-sensitive notification in the system
    send_push_to_user(
        user.id,
        f"{agent.name} needs your approval",
        e.description[:160],
        url="/#/agents",
        tag=f"approval-{e.approval_id}",
    )


# A scheduled run with nothing worth telling replies exactly [SILENT]: nothing
# is posted and no push goes out
SILENT_MARKER = "[SILENT]"


def is_silent_reply(text: str) -> bool:
    """The reply is the [SILENT] marker alone (whitespace, a final dot and
    markdown code/bold marks allowed - the prompt shows it in backticks)."""
    return text.strip().strip("`*").rstrip(".").strip().strip("`*").upper() == SILENT_MARKER
