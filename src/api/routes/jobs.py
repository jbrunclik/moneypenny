"""Jobs: the one list of everything that runs on a schedule - items set from
chats and standing jobs (agents) - and the standing chat editor's CRUD on a
standing job, its runs and its conversation. Standing chats phase 3.

Sibling modules approvals and agent_assist attach their routes to this
module's blueprint (one "Jobs" OpenAPI tag). Pause, resume and cancel live in
schedules.py (a job is a scheduled item).
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from apiflask import APIBlueprint
from croniter import croniter

from src.agent.item_scheduler import JobBusyError, JobHeldError, run_job_now
from src.api.errors import raise_conflict_error, raise_not_found_error, raise_validation_error
from src.api.helpers.agent_draft import PROMOTABLE_KINDS
from src.api.helpers.job_responses import jobs_overview
from src.api.helpers.standing_responses import run_to_response, standing_to_response
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.common import StatusResponse
from src.api.schemas.jobs import (
    CreateJobRequest,
    JobConversationSyncResponse,
    JobDetailResponse,
    JobRunsListResponse,
    JobsOverviewResponse,
    RunJobResponse,
    UpdateJobRequest,
)
from src.api.validation import validate_request
from src.auth.admin import check_model_allowed
from src.auth.jwt_auth import require_auth
from src.db.models import StandingChat, User, db
from src.utils.clock import to_api, utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("jobs", __name__, url_prefix="/api", tag="Jobs")

_RUN_MESSAGES = {
    "report": "Ran: the result is in its chat",
    "done": "Ran: the result is in its chat",
    "approval": "Waiting for your approval",
    "silent": "Ran: nothing new",
    "failed": "The run failed",
}


@api.route("/jobs", methods=["GET"])
@api.output(JobsOverviewResponse)
@api.doc(responses=[401])
@require_auth
def get_jobs(user: User) -> dict[str, object]:
    """Every job, needs attention first: each with its recent runs and next run."""
    return jobs_overview(user.id)


def _check_schedule(schedule: str | None, timezone: str | None) -> None:
    if schedule:
        try:
            croniter(schedule)
        except ValueError:  # croniter's CroniterError is a ValueError
            raise_validation_error("Invalid cron expression")
    if timezone:
        try:
            ZoneInfo(timezone)
        except KeyError, ValueError, OSError:  # not found / malformed / unreadable
            raise_validation_error(f"Invalid timezone: {timezone}")


def _standing_chat(user: User, job_id: str) -> StandingChat:
    chat = db.get_standing_chat(job_id, user.id)
    if chat is None:
        raise_not_found_error("Job")
    return chat


def _editable(user: User, job_id: str) -> StandingChat:
    """Built-ins are defined by the app and changed from Settings only."""
    chat = _standing_chat(user, job_id)
    if chat.standing_type:
        raise_validation_error("This built-in agent is managed from Settings.")
    return chat


@api.route("/jobs", methods=["POST"])
@api.output(JobDetailResponse, status_code=201)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
@validate_request(CreateJobRequest)
def create_job(user: User, data: CreateJobRequest) -> dict[str, Any]:
    """A new standing chat with its job (its chat is "Agent: <name>"); with
    replaces_item_id it takes over a chat's watcher or recurring check."""
    _check_schedule(data.schedule, data.timezone)
    if data.replaces_item_id:
        _check_replaceable(user, data.replaces_item_id)
    if db.get_standing_chat_by_name(user.id, data.name):
        raise_validation_error(f"An agent named '{data.name}' already exists")
    if data.model is not None:
        check_model_allowed(user, data.model)
    chat = db.create_standing_chat(
        user.id,
        data.name,
        data.instructions,
        schedule=data.schedule,
        timezone=data.timezone,
        grants=data.grants,
        model=data.model,
        budget_usd=data.budget_usd,
        fresh_context=data.fresh_context,
        enabled=data.enabled,
        description=data.description,
    )
    if data.replaces_item_id:
        db.delete_item(data.replaces_item_id, user.id)
        logger.info("Chat item became an agent", extra={"job_id": chat.id})
    return standing_to_response(chat)


def _check_replaceable(user: User, item_id: str) -> None:
    """The user's own watcher or recurring check (404 / 409 otherwise)."""
    item = db.get_item(item_id, user.id)
    if item is None:
        raise_not_found_error("Scheduled item")
    if item.standing or item.kind not in PROMOTABLE_KINDS:
        raise_conflict_error("Only a watcher or a recurring check can become an agent.")


@api.route("/jobs/<job_id>", methods=["GET"])
@api.output(JobDetailResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_job(user: User, job_id: str) -> dict[str, Any]:
    """A standing chat and its job, as the editor shows it."""
    return standing_to_response(_standing_chat(user, job_id))


@api.route("/jobs/<job_id>", methods=["PATCH"])
@api.output(JobDetailResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
@validate_request(UpdateJobRequest)
def update_job(user: User, data: UpdateJobRequest, job_id: str) -> dict[str, Any]:
    """Change a standing chat: only the fields sent change (grants are the
    complete list, write levels included)."""
    current = _editable(user, job_id)
    _check_schedule(data.schedule, data.timezone)
    if data.model is not None:
        check_model_allowed(user, data.model)
    sent = data.model_dump(exclude_unset=True)
    name = sent.get("name")
    if name and name != current.name and db.get_standing_chat_by_name(user.id, name):
        raise_validation_error(f"An agent named '{name}' already exists")
    changes = {k: v for k, v in sent.items() if not (k in _NOT_NULL and v is None)}
    chat = db.update_standing_chat(job_id, user.id, **changes)
    if chat is None:
        raise_not_found_error("Job")
    return standing_to_response(chat)


# Fields a null in the request leaves alone: they cannot be blank, and a
# null grants must never widen a job to all tools ("*" is sent as such)
_NOT_NULL = frozenset({"name", "timezone", "enabled", "fresh_context", "grants"})


@api.route("/jobs/<job_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
def delete_job(user: User, job_id: str) -> dict[str, Any]:
    """Delete a standing chat: its chat, runs, approvals, notes and job.
    Message costs stay (cost tracking)."""
    _editable(user, job_id)
    if not db.delete_standing_chat(job_id, user.id):
        raise_not_found_error("Job")
    return {"status": "deleted"}


@api.route("/jobs/<job_id>/viewed", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@require_auth
def mark_job_viewed(user: User, job_id: str) -> dict[str, Any]:
    """The user opened the standing chat: its messages so far are read."""
    if not db.mark_standing_viewed(job_id, user.id):
        raise_not_found_error("Job")
    return {"status": "viewed"}


@api.route("/jobs/<job_id>/conversation/sync", methods=["GET"])
@api.output(JobConversationSyncResponse)
@api.doc(responses=[401, 404])
@require_auth
def sync_job_conversation(user: User, job_id: str) -> dict[str, Any]:
    """The standing chat's message count and updated_at, for live sync."""
    chat = _standing_chat(user, job_id)
    conv_data = db.get_conversation_with_message_count(chat.conversation_id)
    conversation = None
    if conv_data:
        conv, message_count = conv_data
        conversation = {"message_count": message_count, "updated_at": to_api(conv.updated_at)}
    return {"conversation": conversation, "server_time": to_api(utc_now())}


@api.route("/jobs/<job_id>/run", methods=["POST"])
@api.output(RunJobResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
def run_job(user: User, job_id: str) -> dict[str, Any]:
    """Run a standing chat's job now (claimed like a due run, so the
    scheduler cannot start it at the same time)."""
    chat = _standing_chat(user, job_id)
    if not chat.enabled:
        raise_validation_error("This agent is paused")
    try:
        outcome = run_job_now(chat.job, user)
    except JobHeldError as held:
        raise_validation_error(f"Not run: it is {held}.")
    except JobBusyError:
        raise_validation_error("It is running already")
    message = _RUN_MESSAGES.get(outcome.status, "Ran")
    if outcome.status == "failed" and outcome.error:
        message = f"The run failed: {outcome.error}"
    runs = db.get_job_runs(job_id, limit=1)
    if not runs:
        raise_not_found_error("Job run")
    return {"run": run_to_response(runs[0]), "message": message}


@api.route("/jobs/<job_id>/runs", methods=["GET"])
@api.output(JobRunsListResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_job_runs(user: User, job_id: str) -> dict[str, Any]:
    """A standing job's 20 most recent runs, newest first."""
    _standing_chat(user, job_id)
    return {"runs": [run_to_response(r) for r in db.get_job_runs(job_id, limit=20)]}
