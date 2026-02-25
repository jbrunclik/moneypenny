"""Planner routes: Dashboard, conversation, reset, sync.

This module handles the AI planner feature, which provides a daily
dashboard with events from Google Calendar and tasks from Todoist,
plus an ephemeral chat that resets daily.
"""

from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import request

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.calendar import _get_valid_calendar_access_token
from src.api.schemas import (
    PlannerConversationResponse,
    PlannerDashboardResponse,
    PlannerResetResponse,
    PlannerSyncResponse,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger
from src.utils.planner_data import build_planner_dashboard

logger = get_logger(__name__)

api = APIBlueprint("planner", __name__, url_prefix="/api", tag="Planner")


# ============================================================================
# Helper Functions
# ============================================================================


def _optimize_messages_for_response(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Message objects to optimized response format.

    Only includes file metadata (name, type, messageId, fileIndex), not full data.
    """
    from src.api.utils import normalize_generated_images

    optimized_messages = []
    for m in messages:
        optimized_files = []
        if m.files:
            for idx, file in enumerate(m.files):
                optimized_file = {
                    "name": file.get("name", ""),
                    "type": file.get("type", ""),
                    "messageId": m.id,
                    "fileIndex": idx,
                }
                optimized_files.append(optimized_file)

        msg_data: dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "files": optimized_files,
            "created_at": m.created_at.isoformat(),
        }
        if m.sources:
            msg_data["sources"] = m.sources
        if m.generated_images:
            # Normalize generated_images to ensure proper structure
            # (LLM sometimes returns just strings instead of {"prompt": "..."} objects)
            msg_data["generated_images"] = normalize_generated_images(m.generated_images)
        if m.language:
            msg_data["language"] = m.language

        optimized_messages.append(msg_data)
    return optimized_messages


# ============================================================================
# Planner Routes
# ============================================================================


@api.route("/planner", methods=["GET"])
@api.output(PlannerDashboardResponse)
@api.doc(responses=[401, 429])
@rate_limit_conversations
@require_auth
def get_planner_dashboard(user: User) -> dict[str, Any]:
    """Get planner dashboard data for the next 7 days.

    Returns events from Google Calendar and tasks from Todoist,
    organized by day. Requires at least one integration to be connected.

    The dashboard includes:
    - days: Array of 7 days (Today, Tomorrow, then weekday names)
    - Each day contains events and tasks for that date
    - overdue_tasks: Tasks that are past their due date
    - Connection status flags for both integrations
    - server_time: Current server time for cache invalidation

    Query parameters:
    - force_refresh: Set to "true" to bypass cache and fetch fresh data
    """
    # Check for force_refresh parameter (for refresh button)
    force_refresh = request.args.get("force_refresh", "false").lower() == "true"

    logger.debug(
        "Fetching planner dashboard",
        extra={"user_id": user.id, "force_refresh": force_refresh},
    )

    # Refresh user data to get latest tokens
    current_user = db.get_user_by_id(user.id)
    if not current_user:
        raise_not_found_error("User")

    # Get valid tokens (with refresh if needed)
    todoist_token = current_user.todoist_access_token
    calendar_token = _get_valid_calendar_access_token(current_user)

    # Build the dashboard with caching
    dashboard = build_planner_dashboard(
        todoist_token=todoist_token,
        calendar_token=calendar_token,
        garmin_token=current_user.garmin_token,
        user_id=user.id,
        force_refresh=force_refresh,
        db=db,
    )

    logger.info(
        "Planner dashboard built",
        extra={
            "user_id": user.id,
            "todoist_connected": dashboard.todoist_connected,
            "calendar_connected": dashboard.calendar_connected,
            "total_events": sum(len(d.events) for d in dashboard.days),
            "total_tasks": sum(len(d.tasks) for d in dashboard.days),
            "overdue_tasks": len(dashboard.overdue_tasks),
        },
    )

    # Convert dataclasses to dict for response
    return {
        "days": [
            {
                "date": day.date,
                "day_name": day.day_name,
                "events": [
                    {
                        "id": e.id,
                        "summary": e.summary,
                        "description": e.description,
                        "start": e.start,
                        "end": e.end,
                        "start_date": e.start_date,
                        "end_date": e.end_date,
                        "location": e.location,
                        "html_link": e.html_link,
                        "is_all_day": e.is_all_day,
                        "attendees": e.attendees,
                        "organizer": e.organizer,
                        "calendar_id": e.calendar_id,
                        "calendar_summary": e.calendar_summary,
                    }
                    for e in day.events
                ],
                "tasks": [
                    {
                        "id": t.id,
                        "content": t.content,
                        "description": t.description,
                        "due_date": t.due_date,
                        "due_string": t.due_string,
                        "priority": t.priority,
                        "project_name": t.project_name,
                        "section_name": t.section_name,
                        "labels": t.labels,
                        "is_recurring": t.is_recurring,
                        "url": t.url,
                    }
                    for t in day.tasks
                ],
                "weather": {
                    "temperature_high": day.weather.temperature_high,
                    "temperature_low": day.weather.temperature_low,
                    "precipitation": day.weather.precipitation,
                    "symbol_code": day.weather.symbol_code,
                    "summary": day.weather.summary,
                }
                if day.weather
                else None,
            }
            for day in dashboard.days
        ],
        "overdue_tasks": [
            {
                "id": t.id,
                "content": t.content,
                "description": t.description,
                "due_date": t.due_date,
                "due_string": t.due_string,
                "priority": t.priority,
                "project_name": t.project_name,
                "section_name": t.section_name,
                "labels": t.labels,
                "is_recurring": t.is_recurring,
                "url": t.url,
            }
            for t in dashboard.overdue_tasks
        ],
        "todoist_connected": dashboard.todoist_connected,
        "calendar_connected": dashboard.calendar_connected,
        "garmin_connected": dashboard.garmin_connected,
        "weather_connected": dashboard.weather_connected,
        "todoist_error": dashboard.todoist_error,
        "calendar_error": dashboard.calendar_error,
        "garmin_error": dashboard.garmin_error,
        "weather_error": dashboard.weather_error,
        "weather_location": dashboard.weather_location,
        "health_summary": {
            "training_readiness": dashboard.health_summary.training_readiness,
            "sleep": dashboard.health_summary.sleep,
            "stress_avg": dashboard.health_summary.stress_avg,
            "resting_hr": dashboard.health_summary.resting_hr,
            "body_battery": dashboard.health_summary.body_battery,
            "steps_today": dashboard.health_summary.steps_today,
            "recent_activities": dashboard.health_summary.recent_activities,
        }
        if dashboard.health_summary
        else None,
        "server_time": dashboard.server_time,
    }


@api.route("/planner/conversation", methods=["GET"])
@api.output(PlannerConversationResponse)
@api.doc(responses=[401, 429])
@rate_limit_conversations
@require_auth
def get_planner_conversation(user: User) -> dict[str, Any]:
    """Get the planner conversation for the current user.

    Creates a new planner conversation if one doesn't exist.
    Automatically resets the conversation at 4am daily (lazy check).

    The planner conversation is a single, special conversation per user:
    - Excluded from search results
    - Has ephemeral chat that resets daily
    - Appears at the top of the conversation list with special treatment

    Returns:
    - The planner conversation with its messages
    - was_reset: True if the conversation was auto-reset this request
    """
    logger.debug("Getting planner conversation", extra={"user_id": user.id})

    # Get or create planner conversation with auto-reset check
    conv, was_reset = db.get_planner_conversation_with_auto_reset(user, model=Config.DEFAULT_MODEL)

    # Get messages for the conversation
    messages = db.get_messages(conv.id)

    # Optimize file data
    optimized_messages = _optimize_messages_for_response(messages)

    logger.info(
        "Planner conversation retrieved",
        extra={
            "user_id": user.id,
            "conversation_id": conv.id,
            "message_count": len(messages),
            "was_reset": was_reset,
        },
    )

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": optimized_messages,
        "was_reset": was_reset,
    }


@api.route("/planner/reset", methods=["POST"])
@api.output(PlannerResetResponse)
@api.doc(responses=[401, 429])
@rate_limit_conversations
@require_auth
def reset_planner_conversation(user: User) -> dict[str, Any]:
    """Manually reset the planner conversation.

    Physically deletes all messages from the planner conversation
    (not soft delete). Message costs are preserved for accurate
    cost tracking.

    This also clears the dashboard cache so the next request fetches
    fresh data.

    Returns:
    - success: True if reset was successful
    - message: Human-readable status message
    """
    logger.info("Resetting planner conversation", extra={"user_id": user.id})

    # Reset the planner conversation
    db.reset_planner_conversation(user.id)

    # Clear dashboard cache to ensure fresh data on next request
    db.delete_cached_dashboard(user.id)

    logger.info("Planner conversation reset complete", extra={"user_id": user.id})

    return {
        "success": True,
        "message": "Planner conversation reset successfully",
    }


@api.route("/planner/sync", methods=["GET"])
@api.output(PlannerSyncResponse)
@api.doc(responses=[401])
@require_auth
def sync_planner_conversation(user: User) -> dict[str, Any]:
    """Get planner conversation state for sync.

    Returns the planner conversation state for real-time synchronization.
    This allows the frontend to detect:
    - New messages added in another tab/device
    - Planner reset in another tab
    - Planner deletion

    Returns:
    - conversation: Planner conversation state (id, updated_at, message_count, last_reset)
      or null if no planner exists
    - server_time: Server timestamp for clock-skew-proof comparisons
    """
    # Get planner conversation without creating it (sync shouldn't create)
    planner_conv = db.get_planner_conversation(user.id)

    server_time = datetime.utcnow().isoformat()

    if not planner_conv:
        return {"conversation": None, "server_time": server_time}

    message_count = db.count_messages(planner_conv.id)

    return {
        "conversation": {
            "id": planner_conv.id,
            "updated_at": planner_conv.updated_at.isoformat(),
            "message_count": message_count,
            "last_reset": planner_conv.last_reset.isoformat() if planner_conv.last_reset else None,
        },
        "server_time": server_time,
    }
