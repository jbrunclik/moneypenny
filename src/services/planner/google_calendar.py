"""Google Calendar events for the planner dashboard, fetched in parallel."""

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx

from src.config import Config
from src.services.planner.models import PlannerEvent
from src.utils.clock import to_api, utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

# (calendar_id, events, calendar_name, error_message, is_primary)
_CalendarResult = tuple[str, list[dict[str, Any]] | None, str | None, str | None, bool]


def format_event(event: dict[str, Any]) -> PlannerEvent:
    """Convert a raw Google Calendar event to a PlannerEvent."""
    start = event.get("start", {})
    end = event.get("end", {})

    is_all_day = "date" in start and "dateTime" not in start

    # Extract organizer information
    organizer_data = event.get("organizer")
    organizer = None
    if organizer_data:
        organizer = {
            "email": organizer_data.get("email"),
            "display_name": organizer_data.get("displayName"),
            "self": organizer_data.get("self", False),
        }

    return PlannerEvent(
        id=event.get("id", ""),
        summary=event.get("summary", "(No title)"),
        description=event.get("description"),
        start=start.get("dateTime"),
        end=end.get("dateTime"),
        start_date=start.get("date"),
        end_date=end.get("date"),
        location=event.get("location"),
        html_link=event.get("htmlLink"),
        is_all_day=is_all_day,
        attendees=[
            {
                "email": a.get("email"),
                "response_status": a.get("responseStatus"),
                "self": a.get("self", False),
            }
            for a in event.get("attendees", [])
        ],
        organizer=organizer,
    )


def _fetch_calendar_names(headers: dict[str, str]) -> dict[str, str]:
    """Map calendar ids (and "primary") to their names; failures give {}."""
    calendar_names: dict[str, str] = {}
    try:
        response = httpx.get(
            f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/users/me/calendarList",
            headers=headers,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        if response.status_code != 200:
            logger.warning(
                "Failed to fetch calendar list",
                extra={"status": response.status_code},
            )
            return calendar_names
        for cal in response.json().get("items", []):
            cal_id = cal.get("id")
            cal_summary = cal.get("summary")
            if cal_id and cal_summary:
                calendar_names[cal_id] = cal_summary
            # Also map "primary" to the actual primary calendar's name
            if cal.get("primary", False):
                calendar_names["primary"] = cal_summary
    except Exception as e:  # names are optional; events fall back to calendar ids
        logger.warning("Failed to fetch calendar names", extra={"error": str(e)}, exc_info=True)
    return calendar_names


def _event_window_params() -> dict[str, Any]:
    """Query parameters for the next 7 days of events."""
    now = utc_now()
    return {
        "timeMin": to_api(now),
        "timeMax": to_api(now + timedelta(days=7)),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 30,  # whole dashboard JSON lands in the LLM prompt each turn
    }


def _status_error(calendar_id: str, status_code: int) -> str | None:
    """The per-calendar error for an HTTP status, or None when it succeeded."""
    if status_code == 401:
        return "Access expired"
    if status_code == 403:
        return "Permission denied"
    if status_code == 404:
        return "Calendar not found"
    if status_code >= 400:
        logger.warning(
            "Calendar API error",
            extra={"calendar_id": calendar_id, "status": status_code},
        )
        return f"API error ({status_code})"
    return None


def _fetch_single_calendar(
    calendar_id: str,
    headers: dict[str, str],
    params: dict[str, Any],
    calendar_names: dict[str, str],
) -> _CalendarResult:
    """Fetch events from a single calendar."""
    try:
        # URL-encode the calendar ID to handle special characters like # in holiday calendars
        encoded_calendar_id = quote(calendar_id, safe="")
        response = httpx.get(
            f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events",
            headers=headers,
            params=params,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        error = _status_error(calendar_id, response.status_code)
        if error:
            return calendar_id, None, None, error, False

        events = response.json().get("items", [])
        calendar_name = calendar_names.get(calendar_id, calendar_id)
        return calendar_id, events, calendar_name, None, calendar_id == "primary"

    except httpx.TimeoutException:
        logger.warning("Calendar fetch timeout", extra={"calendar_id": calendar_id})
        return calendar_id, None, None, "Request timeout", False
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error(  # noqa: TRY400 - network or JSON error; shown on the dashboard
            "Calendar fetch failed", extra={"calendar_id": calendar_id, "error": str(e)}
        )
        return calendar_id, None, None, "Connection error", False
    except Exception as e:
        logger.exception(
            "Unexpected calendar fetch error",
            extra={"calendar_id": calendar_id, "error": str(e)},
        )
        return calendar_id, None, None, "Unexpected error", False


def _add_calendar_events(
    result: _CalendarResult,
    all_events: list[PlannerEvent],
    seen_event_ids: set[str],
) -> None:
    """Append one calendar's live events, skipping ones already seen."""
    calendar_id, events, calendar_name, _, is_primary = result
    for event in events or []:
        event_id = event.get("id")
        # Skip id-less and cancelled events (deleted occurrences of recurring series)
        if not event_id or event.get("status") == "cancelled":
            continue
        # Duplicates happen when both "primary" and the actual primary calendar ID are selected
        if event_id in seen_event_ids:
            logger.debug(
                "Skipping duplicate event",
                extra={"event_id": event_id, "calendar_id": calendar_id},
            )
            continue
        seen_event_ids.add(event_id)

        planner_event = format_event(event)
        # Normalize calendar_id - always use "primary" for the primary calendar
        planner_event.calendar_id = "primary" if is_primary else calendar_id
        planner_event.calendar_summary = calendar_name or calendar_id
        all_events.append(planner_event)


def _merge_results(
    futures: list[Future[_CalendarResult]],
) -> tuple[list[PlannerEvent], list[tuple[str, str]]]:
    """Merge calendars as they finish: (events, [(calendar_id, error_message)])."""
    all_events: list[PlannerEvent] = []
    errors: list[tuple[str, str]] = []
    seen_event_ids: set[str] = set()
    for future in as_completed(futures):
        result = future.result()
        calendar_id, _, _, error, _ = result
        if error:
            errors.append((calendar_id, error))
            logger.debug(
                "Calendar fetch failed", extra={"calendar_id": calendar_id, "error": error}
            )
            continue
        _add_calendar_events(result, all_events, seen_event_ids)
    return all_events, errors


def _overall_error(
    errors: list[tuple[str, str]],
    calendar_ids: list[str],
    calendar_names: dict[str, str],
) -> str | None:
    """One dashboard message for all calendar failures, or None when none failed."""
    if len(errors) == len(calendar_ids):
        if any("expired" in err.lower() for _, err in errors):
            return "Google Calendar access has expired. Please reconnect in Settings."
        return "Failed to fetch any calendars. Please check your connection."
    if not errors:
        return None
    # Partial failure - show which calendars failed
    failed_names = ", ".join(calendar_names.get(cid, cid) for cid, _ in errors[:3])
    if len(errors) > 3:
        return f"Some calendars failed to load: {failed_names}, and {len(errors) - 3} more"
    return f"Some calendars failed to load: {failed_names}"


def fetch_calendar_dashboard_data(
    access_token: str,
    calendar_ids: list[str] | None = None,
) -> tuple[list[PlannerEvent], str | None]:
    """Fetch Google Calendar events from multiple calendars in parallel.

    Args:
        access_token: The user's Google Calendar access token
        calendar_ids: List of calendar IDs to fetch (defaults to ["primary"])

    Returns:
        Tuple of (events, error_message)
        - events: Combined events from all calendars
        - error_message: Error message if any failures occurred
    """
    logger.debug("Fetching calendar dashboard data")
    if not calendar_ids:
        calendar_ids = ["primary"]
    headers = {"Authorization": f"Bearer {access_token}"}
    calendar_names = _fetch_calendar_names(headers)
    params = _event_window_params()

    with ThreadPoolExecutor(max_workers=min(len(calendar_ids), 5)) as executor:
        futures = [
            executor.submit(_fetch_single_calendar, cid, headers, params, calendar_names)
            for cid in calendar_ids
        ]
        all_events, errors = _merge_results(futures)

    all_events.sort(key=lambda e: e.start or e.start_date or "")
    logger.debug(
        "Calendar dashboard data fetched",
        extra={
            "event_count": len(all_events),
            "calendars_requested": len(calendar_ids),
            "calendars_succeeded": len(calendar_ids) - len(errors),
            "calendars_failed": len(errors),
        },
    )
    return all_events, _overall_error(errors, calendar_ids, calendar_names)
