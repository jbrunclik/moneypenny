"""Run proposals: how an unattended run asks for a yes (docs/features/proposals.md).

The write and destructive gates (src/agent/tools/permission_check.py) no
longer ask the model to request an approval: a call that needs one files a
card from the call itself - its tool, its full arguments (call_signature),
a plain-language summary - and pauses the run. Approving resumes the run, and
only the identical call consumes the approval (once); a call with other
arguments files a new card. request_approval files an unbound card for
actions no gate covers (it only pauses for consent).

Answers apply here: an approved agent_action closes the paused execution,
tells the run which call to re-issue, and resumes it in the background;
"Always allow" also grants the tool's write level; a decline closes the run
as rejected. The run's report is the reply - no chat turn of its own.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.agent.permissions import WRITE_LEVEL_TOOLS, WRITE_SUFFIX, base_tool
from src.agent.proposals import ProposalFailedError, register_kind
from src.agent.tool_loops import call_signature
from src.agent.tools.request_approval import ApprovalRequestedException
from src.config import Config
from src.db.models import Proposal, ProposalOption, db
from src.enums import MessageRole
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.agent.run_context import JobContext

logger = get_logger(__name__)

KIND = "agent_action"
APPROVE_LABEL = "Approve"
_ALL_TOOLS = "*"
_DETAIL_MAX_CHARS = 300
_EXPIRED_RUN = "The approval was not answered in time"
_TOOL_LABELS = {
    "todoist": "Todoist",
    "google_calendar": "Calendar",
    "garmin_workout": "Garmin workouts",
    "rouvy_workout": "Rouvy",
}


def tool_label(tool: str) -> str:
    """A tool as people call it."""
    return _TOOL_LABELS.get(tool, tool)


def describe_call(tool: str, args: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    """A call in words: the summary line and one row per argument."""
    operation = str(args.get("operation") or args.get("action") or "change").replace("_", " ")
    summary = f"{tool_label(tool)}: {operation}"
    rows: dict[str, object] = {}
    for key, value in args.items():
        if key in {"operation", "action"} or value in (None, "", [], {}):
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        rows[key.replace("_", " ").capitalize()] = text[:_DETAIL_MAX_CHARS]
    return summary, rows


def _can_always_allow(context: JobContext, tool: str) -> bool:
    """Always allow: a writable integration the job already holds (never a new tool)."""
    held = context.item.grants
    if tool not in WRITE_LEVEL_TOOLS or held is None or _ALL_TOOLS in held:
        return False
    return tool in {base_tool(g) for g in held}


def file_run_card(
    context: JobContext,
    kind: str,
    summary: str,
    details: Mapping[str, object],
    options: list[ProposalOption],
) -> Proposal:
    """File the run's card (linked to its message and execution when the
    run is parked: link_run_card)."""
    return db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=context.user.id,
            conversation_id=context.item.conversation_id or "",
            message_id=None,
            request_id="",
            kind=kind,
            summary=summary,
            details=dict(details),
            options=options,
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
            origin="run",
            job_id=context.item.id,
            expires_at=utc_now() + timedelta(hours=Config.AGENT_APPROVAL_TTL_HOURS),
        )
    )


def require_call_approval(
    context: JobContext, tool: str, args: Mapping[str, object], *, destructive: bool
) -> None:
    """Let the call through when the user approved exactly it; otherwise
    file its card and pause the run."""
    signature = call_signature(tool, args)
    if db.consume_run_approval(context.item.id, signature):
        logger.info("Run call authorized by its approved card", extra={"tool": tool})
        return
    summary, rows = describe_call(tool, args)
    payload: dict[str, object] = {"tool": tool, "args": dict(args), "signature": signature}
    options: list[ProposalOption] = [
        {"label": APPROVE_LABEL, "description": "", "payload": payload}
    ]
    if not destructive and _can_always_allow(context, tool):
        label = f"Always allow {tool_label(tool)} changes"
        options.append({"label": label, "description": "", "payload": {**payload, "always": True}})
    card = file_run_card(context, KIND, summary, rows, options)
    raise ApprovalRequestedException(card.id, summary, tool)


def _close_execution(proposal: Proposal, status: str) -> None:
    if proposal.execution_id:
        db.update_execution(proposal.execution_id, status=status)


def _grant_write(proposal: Proposal, tool: str) -> None:
    """Always allow: add <tool>:write to a job that holds the tool."""
    job = db.get_item(proposal.job_id or "", proposal.user_id)
    held = job.grants if job else None
    if job is None or held is None or tool not in {base_tool(g) for g in held}:
        raise ProposalFailedError(f"This agent has no {tool_label(tool)} access to extend.")
    grant = f"{tool}{WRITE_SUFFIX}"
    db.update_standing_chat(job.id, proposal.user_id, grants=list(dict.fromkeys([*held, grant])))
    logger.info("Write access granted from a card", extra={"job_id": job.id, "tool": tool})


def _resume(proposal: Proposal, message: str) -> None:
    """Resume the job's run with the outcome (background: the request returns)."""
    from src.agent.item_scheduler import JobBusyError, JobHeldError, run_job_now  # noqa: PLC0415 - cycle: the scheduler imports the tools

    job = db.get_item(proposal.job_id or "", proposal.user_id)
    user = db.get_user_by_id(proposal.user_id)
    if job is None or user is None:
        return

    def run() -> None:
        try:
            run_job_now(job, user, message=message)
        except (JobHeldError, JobBusyError) as held:  # the approval stands
            logger.info(
                "Job not resumed after a card", extra={"job_id": job.id, "reason": str(held)}
            )
        except Exception:
            logger.exception("Resumed job run crashed", extra={"job_id": job.id})

    threading.Thread(target=run, name=f"resume-{job.id[:8]}", daemon=True).start()


def apply_agent_action(proposal: Proposal, option: ProposalOption) -> str:
    """Approved: re-run the paused run, which may now make exactly this call."""
    payload = option["payload"]
    tool = str(payload.get("tool") or "")
    if payload.get("always"):
        _grant_write(proposal, tool)
    _close_execution(proposal, "completed")
    args = payload.get("args")
    call = (
        f" Re-issue exactly: {tool}({json.dumps(args, ensure_ascii=False)})."
        if payload.get("signature")
        else ""
    )
    message = f"[Action approved: {proposal.summary}]{call}"
    db.add_message(proposal.conversation_id, MessageRole.USER, message)
    _resume(proposal, message)
    return "Approved - continuing."


def decline_agent_action(proposal: Proposal) -> None:
    """Declined: the paused run ends; the agent hears it next time."""
    _close_execution(proposal, "rejected")
    db.add_message(
        proposal.conversation_id, MessageRole.USER, f"[Action rejected: {proposal.summary}]"
    )


def expire_stale_run_cards(now: datetime) -> int:
    """Cards nobody answered within AGENT_APPROVAL_TTL_HOURS expire, and
    their paused runs close as failed (the next run can ask again)."""
    expired = db.expire_run_proposals(now)
    for proposal in expired:
        if proposal.execution_id:
            db.update_execution(proposal.execution_id, status="failed", error_message=_EXPIRED_RUN)
    if expired:
        logger.info("Run cards expired", extra={"count": len(expired)})
    return len(expired)


register_kind(KIND, apply_agent_action, decline=decline_agent_action)
