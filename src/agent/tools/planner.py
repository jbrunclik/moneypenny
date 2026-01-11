"""Planner dashboard refresh tool.

This tool allows the LLM to refresh the planner dashboard data after making
changes to tasks or calendar events, ensuring it has up-to-date information
about the user's schedule.
"""

from dataclasses import asdict

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.planner_data import build_planner_dashboard

logger = get_logger(__name__)


def _get_user_tokens() -> tuple[str | None, str | None, str | None]:
    """Get the current user's ID and integration tokens.

    Returns:
        Tuple of (user_id, todoist_token, calendar_token)
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None, None, None

    user = db.get_user_by_id(user_id)
    if not user:
        return None, None, None

    # Get calendar token (may need refresh)
    calendar_token = user.google_calendar_access_token
    if calendar_token and user.google_calendar_refresh_token:
        from src.auth.google_calendar import refresh_access_token

        # Try to refresh if token might be expired
        refreshed_data = refresh_access_token(user.google_calendar_refresh_token)
        if refreshed_data and "access_token" in refreshed_data:
            calendar_token = refreshed_data["access_token"]

    return user.id, user.todoist_access_token, calendar_token


@tool
def refresh_planner_dashboard() -> str:
    """Refresh the planner dashboard with the latest data from Todoist and Google Calendar.

    Use this tool AFTER making changes to tasks (via todoist tool) or calendar events
    (via google_calendar tool) to ensure you have the most current information about
    the user's schedule, tasks, and events.

    This tool:
    - Fetches fresh data from Todoist and Google Calendar APIs
    - Updates the in-memory context with the new dashboard state
    - Returns a summary of the refreshed data

    When to use:
    - After adding, updating, completing, or deleting tasks
    - After creating, updating, or deleting calendar events
    - When you need to verify changes were applied correctly
    - Before providing recommendations based on the current schedule state

    Returns:
        A summary of the refreshed dashboard data including counts of
        events, tasks, and any connection errors.
    """
    logger.info("Refreshing planner dashboard data")

    user_id, todoist_token, calendar_token = _get_user_tokens()

    if not user_id:
        return (
            "Error: Unable to refresh dashboard - no active user context. "
            "This tool can only be used in authenticated conversations."
        )

    # Check if at least one integration is connected
    if not todoist_token and not calendar_token:
        return (
            "Error: No integrations connected. Please connect Todoist or "
            "Google Calendar in Settings before using the planner."
        )

    try:
        # Force refresh to bypass cache and get latest data
        dashboard = build_planner_dashboard(
            todoist_token=todoist_token,
            calendar_token=calendar_token,
            user_id=user_id,
            force_refresh=True,
            db=db,
        )

        # Update the contextvar with the refreshed dashboard data
        # Convert dataclass to dict for injection into system prompt
        from src.agent.chat_agent import _planner_dashboard_context

        dashboard_dict = asdict(dashboard)
        _planner_dashboard_context.set(dashboard_dict)

        # Build summary response
        total_events = sum(len(day.events) for day in dashboard.days)
        total_tasks = sum(len(day.tasks) for day in dashboard.days)
        overdue_count = len(dashboard.overdue_tasks)

        summary_parts = [
            "Dashboard refreshed successfully!",
            "\nUpcoming (next 7 days):",
            f"  - {total_events} calendar event(s)",
            f"  - {total_tasks} task(s)",
        ]

        if overdue_count > 0:
            summary_parts.append(f"  - {overdue_count} overdue task(s)")

        # Add error information if any
        errors = []
        if dashboard.todoist_error:
            errors.append(f"Todoist: {dashboard.todoist_error}")
        if dashboard.calendar_error:
            errors.append(f"Calendar: {dashboard.calendar_error}")

        if errors:
            summary_parts.append("\nWarnings:")
            for error in errors:
                summary_parts.append(f"  - {error}")

        logger.info(
            "Dashboard refresh completed",
            extra={
                "user_id": user_id,
                "events": total_events,
                "tasks": total_tasks,
                "overdue": overdue_count,
            },
        )

        return "\n".join(summary_parts)

    except Exception as e:
        error_msg = f"Error refreshing dashboard: {e}"
        logger.error("Dashboard refresh failed", extra={"error": str(e)}, exc_info=True)
        return error_msg


def is_refresh_planner_dashboard_available() -> bool:
    """Check if the refresh_planner_dashboard tool is available.

    The tool is available when the user is in a planner conversation context.
    """
    _, user_id = get_conversation_context()
    return user_id is not None
