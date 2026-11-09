"""The jobs overview as API data: every job in the user's live chats, with its
recent runs, week's stats and what needs the user's attention."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from src.agent.tools.scheduling import describe_ends, describe_when
from src.api.helpers.standing_responses import run_proposal_to_response
from src.config import Config
from src.db.models import db
from src.db.models.scheduled_items import NEVER_RUN_AT
from src.services.costs import convert_currency, format_cost
from src.utils.clock import to_api

if TYPE_CHECKING:
    from src.db.models import Conversation
    from src.db.models.dataclasses import JobRun, ScheduledItem

_TITLE_MAX_CHARS = 60
_ERROR_MAX_CHARS = 160
_LATEST = datetime.max.replace(tzinfo=NEVER_RUN_AT.tzinfo)


class RunData(TypedDict):
    status: str
    trigger_type: str
    started_at: str
    error: str | None


class JobData(TypedDict):
    id: str
    kind: str
    standing: bool
    area: str
    title: str
    conversation_id: str
    conversation_title: str
    when: str
    ends: str
    status: str
    paused_reason: str | None
    next_run_at: str | None
    system_type: str | None
    editable: bool
    unread_count: int
    has_pending_approval: bool
    cost_7d_display: str | None
    runs_7d: int
    recent_runs: list[RunData]


def _cost(usd: float) -> str:
    return format_cost(convert_currency(usd, Config.COST_CURRENCY), Config.COST_CURRENCY)


def _area(conv: Conversation | None) -> str:
    if conv is None:
        return "chat"
    if conv.is_agent:
        return "agents"
    if conv.is_sports:
        return "sports"
    return "language" if conv.is_language else "chat"


def _title(item: ScheduledItem, conv: Conversation | None) -> str:
    if item.standing and conv is not None and conv.standing_name:
        return conv.standing_name
    text = item.text
    return text if len(text) <= _TITLE_MAX_CHARS else text[: _TITLE_MAX_CHARS - 1] + "…"


def _run(run: JobRun) -> RunData:
    error = run.error_message
    return {
        "status": run.status,
        "trigger_type": run.trigger_type,
        "started_at": to_api(run.started_at),
        "error": error[:_ERROR_MAX_CHARS] if error else None,
    }


def _job(
    item: ScheduledItem,
    conv: Conversation | None,
    runs: list[JobRun],
    week: dict[str, float],
) -> JobData:
    agent_job = conv is not None and conv.is_agent and conv.job_id == item.id
    never = item.next_run_at >= NEVER_RUN_AT
    return {
        "id": item.id,
        "kind": item.kind,
        "standing": item.standing,
        "area": _area(conv),
        "title": _title(item, conv),
        "conversation_id": item.conversation_id,
        "conversation_title": (conv.title if conv else None) or "Chat",
        "when": describe_when(item) if not (never and not item.schedule) else "on demand",
        "ends": describe_ends(item),
        "status": item.status,
        "paused_reason": item.paused_reason,
        "next_run_at": None if never else to_api(item.next_run_at),
        "system_type": conv.standing_type if agent_job and conv else None,
        "editable": bool(agent_job and conv and not conv.standing_type),
        "unread_count": db.standing_unread_count(item.id) if agent_job else 0,
        "has_pending_approval": bool(item.standing and db.has_pending_run_proposal(item.id)),
        "cost_7d_display": _cost(week["cost_usd"]) if week else None,
        "runs_7d": int(week.get("runs", 0)),
        "recent_runs": [_run(r) for r in runs],
    }


def _last_failed(job: JobData) -> bool:
    return bool(job["recent_runs"]) and job["recent_runs"][0]["status"] == "failed"


def _needs_attention(job: JobData) -> bool:
    return job["has_pending_approval"] or job["paused_reason"] == "failures" or _last_failed(job)


def jobs_overview(user_id: str) -> dict[str, object]:
    """JobsOverviewResponse data for the user."""
    items = db.list_all_items(user_id)
    convs = {cid: db.get_conversation(cid, user_id) for cid in {i.conversation_id for i in items}}
    standing_ids = [i.id for i in items if i.standing]
    runs = db.recent_runs(standing_ids)
    week = db.job_week_stats(user_id)
    jobs = [
        _job(i, convs[i.conversation_id], runs.get(i.id, []), week.get(i.id, {})) for i in items
    ]
    jobs.sort(
        key=lambda j: (
            not _needs_attention(j),
            j["next_run_at"] or to_api(_LATEST),
            j["title"].casefold(),
        )
    )
    names = {j["id"]: j["title"] for j in jobs}
    approvals = [
        run_proposal_to_response(p, names.get(p.job_id or "", "Agent"))
        for p in db.pending_run_proposals(user_id)
    ]
    totals = {k: sum(w.get(k, 0) for w in week.values()) for k in ("runs", "completed", "failed")}
    return {
        "jobs": jobs,
        "pending_approvals": approvals,
        "stats": {
            "days": 7,
            "total_runs": int(totals["runs"]),
            "total_completed": int(totals["completed"]),
            "total_failed": int(totals["failed"]),
            "total_cost_display": _cost(sum(w.get("cost_usd", 0.0) for w in week.values())),
        },
        "total_unread": sum(j["unread_count"] for j in jobs),
        "jobs_waiting": sum(1 for j in jobs if j["has_pending_approval"]),
        "jobs_with_errors": sum(1 for j in jobs if _last_failed(j)),
    }
