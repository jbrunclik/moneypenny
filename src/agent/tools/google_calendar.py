"""Google Calendar management tool."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import requests
from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.auth.google_calendar import (
    GoogleCalendarAuthError,
)
from src.auth.google_calendar import (
    refresh_access_token as refresh_google_calendar_access_token,
)
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _is_google_calendar_configured() -> bool:
    return bool(Config.GOOGLE_CALENDAR_CLIENT_ID and Config.GOOGLE_CALENDAR_CLIENT_SECRET)


def _get_google_calendar_access_token() -> tuple[str, str | None] | None:
    """Fetch the user's Google Calendar access token, refreshing if needed."""
    _, user_id = get_conversation_context()
    if not user_id:
        return None

    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user or not user.google_calendar_access_token:
        return None

    access_token = user.google_calendar_access_token
    refresh_token = user.google_calendar_refresh_token
    expires_at = user.google_calendar_token_expires_at

    # Proactively refresh if token expires within 5 minutes
    refresh_threshold = datetime.now() + timedelta(minutes=5)
    if expires_at and expires_at <= refresh_threshold:
        if not refresh_token:
            logger.warning(
                "Google Calendar token expiring soon and no refresh token available",
                extra={"user_id": user_id},
            )
            return None
        try:
            refreshed = refresh_google_calendar_access_token(refresh_token)
            access_token = refreshed["access_token"]
            new_refresh = refreshed.get("refresh_token", refresh_token)
            expires_in = refreshed.get("expires_in", 3600)
            try:
                expires_in_int = int(expires_in)
            except TypeError, ValueError:
                expires_in_int = 3600
            expires_delta = max(60, expires_in_int - 60)
            new_expires = datetime.now() + timedelta(seconds=expires_delta)
            db.update_user_google_calendar_tokens(
                user_id,
                access_token=access_token,
                refresh_token=new_refresh,
                expires_at=new_expires,
                email=user.google_calendar_email,
                connected_at=user.google_calendar_connected_at,
            )
        except GoogleCalendarAuthError:
            logger.warning(
                "Refreshing Google Calendar token failed",
                extra={"user_id": user_id},
            )
            return None

    return access_token, user.google_calendar_email


def _calendar_time_range(
    time_min: str | None, time_max: str | None, default_days: int = 7
) -> tuple[str, str]:
    if time_min and time_max:
        return time_min, time_max
    start = datetime.utcnow().replace(microsecond=0)
    end = start + timedelta(days=default_days)
    return f"{start.isoformat()}Z", f"{end.isoformat()}Z"


def _google_calendar_api_request(
    method: str,
    endpoint: str,
    token: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Call the Google Calendar REST API."""
    url = f"{Config.GOOGLE_CALENDAR_API_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if method == "GET":
            response = requests.get(
                url, headers=headers, params=params, timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT
            )
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=data,
                timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
            )
        elif method == "PATCH":
            headers["Content-Type"] = "application/json"
            response = requests.patch(
                url,
                headers=headers,
                params=params,
                json=data,
                timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
            )
        elif method == "DELETE":
            response = requests.delete(
                url, headers=headers, params=params, timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error(
            "Google Calendar API request failed",
            extra={"endpoint": endpoint, "error": str(exc)},
            exc_info=True,
        )
        raise Exception("Failed to connect to Google Calendar") from exc

    if response.status_code == 204:
        return None

    if response.status_code >= 400:
        logger.warning(
            "Google Calendar API error",
            extra={
                "endpoint": endpoint,
                "status_code": response.status_code,
                "error": response.text,
            },
        )
        raise Exception(f"Google Calendar API error ({response.status_code}): {response.text}")

    result: dict[str, Any] | list[dict[str, Any]] = response.json()
    return result


def _format_calendar_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize Google Calendar event payload."""
    formatted: dict[str, Any] = {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "description": event.get("description"),
        "status": event.get("status"),
        "creator": event.get("creator", {}).get("email"),
        "organizer": event.get("organizer", {}).get("email"),
        "html_link": event.get("htmlLink"),
        "hangout_link": event.get("hangoutLink"),
        "conference": event.get("conferenceData", {}).get("entryPoints"),
        "location": event.get("location"),
    }

    if event.get("start"):
        start = event["start"]
        if start.get("dateTime"):
            formatted["start"] = start["dateTime"]
            formatted["start_timezone"] = start.get("timeZone")
        elif start.get("date"):
            formatted["start_date"] = start["date"]

    if event.get("end"):
        end = event["end"]
        if end.get("dateTime"):
            formatted["end"] = end["dateTime"]
            formatted["end_timezone"] = end.get("timeZone")
        elif end.get("date"):
            formatted["end_date"] = end["date"]

    if event.get("attendees"):
        formatted["attendees"] = [
            {
                "email": attendee.get("email"),
                "response_status": attendee.get("responseStatus"),
                "self": attendee.get("self", False),
                "organizer": attendee.get("organizer", False),
            }
            for attendee in event["attendees"]
        ]

    if event.get("reminders"):
        formatted["reminders"] = event["reminders"].get("overrides")

    if event.get("recurrence"):
        formatted["recurrence"] = event["recurrence"]

    return formatted


def _google_calendar_list_calendars(token: str) -> dict[str, Any]:
    """List calendars - filtered to only show user's selected calendars."""
    from src.db.models import db

    # Get user's selected calendar IDs
    _, user_id = get_conversation_context()
    selected_calendar_ids = ["primary"]  # Default
    if user_id:
        user = db.get_user_by_id(user_id)
        if user and user.google_calendar_selected_ids:
            selected_calendar_ids = user.google_calendar_selected_ids

    calendars = _google_calendar_api_request("GET", "/users/me/calendarList", token)
    if not isinstance(calendars, dict):
        raise Exception("Unexpected response from Google Calendar")
    entries = calendars.get("items", [])

    # Filter to only show selected calendars
    # Note: Google API returns actual calendar ID (email), but we store "primary" as alias
    formatted = [
        {
            "id": cal.get("id"),
            "summary": cal.get("summary"),
            "primary": cal.get("primary", False),
            "access_role": cal.get("accessRole"),
            "time_zone": cal.get("timeZone"),
        }
        for cal in entries
        if (
            cal.get("id") in selected_calendar_ids
            or (cal.get("primary", False) and "primary" in selected_calendar_ids)
        )
    ]

    return {"action": "list_calendars", "count": len(formatted), "calendars": formatted}


def _google_calendar_list_events(
    token: str,
    calendar_id: str,
    time_min: str | None,
    time_max: str | None,
    max_results: int | None,
    query: str | None,
) -> dict[str, Any]:
    time_min_val, time_max_val = _calendar_time_range(time_min, time_max)
    params: dict[str, Any] = {
        "timeMin": time_min_val,
        "timeMax": time_max_val,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if query:
        params["q"] = query
    if max_results:
        params["maxResults"] = max(1, min(max_results, 100))

    events = _google_calendar_api_request(
        "GET", f"/calendars/{calendar_id}/events", token, params=params
    )
    if not isinstance(events, dict):
        raise Exception("Unexpected response from Google Calendar")
    formatted_events = [_format_calendar_event(e) for e in events.get("items", [])]
    return {
        "action": "list_events",
        "calendar_id": calendar_id,
        "time_min": time_min_val,
        "time_max": time_max_val,
        "count": len(formatted_events),
        "events": formatted_events,
    }


def _google_calendar_get_event(token: str, calendar_id: str, event_id: str) -> dict[str, Any]:
    event = _google_calendar_api_request(
        "GET", f"/calendars/{calendar_id}/events/{event_id}", token
    )
    if not isinstance(event, dict):
        raise Exception("Unexpected response when fetching event")
    return {"action": "get_event", "event": _format_calendar_event(event)}


def _build_event_times(
    start_time: str | None,
    end_time: str | None,
    timezone: str | None,
    all_day: bool | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tz = timezone or "UTC"
    if all_day:
        if not start_time:
            raise Exception("start_time is required for all-day events")
        start = {"date": start_time}
        end = {"date": end_time or start_time}
    else:
        if not start_time or not end_time:
            raise Exception("start_time and end_time are required")
        start = {"dateTime": start_time, "timeZone": tz}
        end = {"dateTime": end_time, "timeZone": tz}
    return start, end


def _build_event_payload(
    summary: str | None,
    description: str | None,
    location: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone: str | None,
    all_day: bool | None,
    attendees: list[str] | None,
    reminders: list[int] | None,
    recurrence: list[str] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if summary is not None:
        payload["summary"] = summary
    if description is not None:
        payload["description"] = description
    if location is not None:
        payload["location"] = location

    if start_time or end_time:
        start, end = _build_event_times(start_time, end_time, timezone, all_day)
        payload["start"] = start
        payload["end"] = end

    if attendees is not None:
        payload["attendees"] = [{"email": email.strip()} for email in attendees if email.strip()]

    if reminders is not None:
        overrides = [{"method": "popup", "minutes": max(0, int(minutes))} for minutes in reminders]
        payload["reminders"] = {"useDefault": False, "overrides": overrides}

    if recurrence is not None:
        payload["recurrence"] = recurrence

    return payload


def _google_calendar_create_event(
    token: str,
    calendar_id: str,
    summary: str | None,
    description: str | None,
    location: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone: str | None,
    all_day: bool | None,
    attendees: list[str] | None,
    reminders: list[int] | None,
    recurrence: list[str] | None,
    conference: bool | None,
    send_updates: str | None,
) -> dict[str, Any]:
    if not summary:
        raise Exception("summary is required to create an event")

    payload = _build_event_payload(
        summary,
        description,
        location,
        start_time,
        end_time,
        timezone,
        all_day,
        attendees,
        reminders,
        recurrence,
    )
    params: dict[str, Any] = {}
    if conference:
        params["conferenceDataVersion"] = 1
        payload.setdefault("conferenceData", {}).setdefault(
            "createRequest", {"requestId": str(uuid.uuid4())}
        )
    if send_updates:
        params["sendUpdates"] = send_updates

    event = _google_calendar_api_request(
        "POST", f"/calendars/{calendar_id}/events", token, params=params, data=payload
    )
    if not isinstance(event, dict):
        raise Exception("Unexpected response when creating event")
    return {"action": "create_event", "event": _format_calendar_event(event)}


def _google_calendar_update_event(
    token: str,
    calendar_id: str,
    event_id: str,
    summary: str | None,
    description: str | None,
    location: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone: str | None,
    all_day: bool | None,
    attendees: list[str] | None,
    reminders: list[int] | None,
    recurrence: list[str] | None,
    conference: bool | None,
    send_updates: str | None,
) -> dict[str, Any]:
    payload = _build_event_payload(
        summary,
        description,
        location,
        start_time,
        end_time,
        timezone,
        all_day,
        attendees,
        reminders,
        recurrence,
    )

    if not payload and not conference:
        return {"error": "No fields to update provided"}

    params: dict[str, Any] = {}
    if conference:
        params["conferenceDataVersion"] = 1
    if send_updates:
        params["sendUpdates"] = send_updates

    event = _google_calendar_api_request(
        "PATCH",
        f"/calendars/{calendar_id}/events/{event_id}",
        token,
        params=params,
        data=payload,
    )
    if not isinstance(event, dict):
        raise Exception("Unexpected response when updating event")
    return {"action": "update_event", "event": _format_calendar_event(event)}


def _google_calendar_delete_event(
    token: str, calendar_id: str, event_id: str, send_updates: str | None
) -> dict[str, Any]:
    params = {"sendUpdates": send_updates} if send_updates else None
    _google_calendar_api_request(
        "DELETE", f"/calendars/{calendar_id}/events/{event_id}", token, params=params
    )
    return {
        "action": "delete_event",
        "success": True,
        "event_id": event_id,
        "calendar_id": calendar_id,
        "message": "Event deleted",
    }


def _google_calendar_respond_event(
    token: str,
    calendar_id: str,
    event_id: str,
    response_status: str,
    user_email: str | None,
    send_updates: str | None,
) -> dict[str, Any]:
    if not user_email:
        raise Exception(
            "Connected Google account email unknown. Ask the user to reconnect Google Calendar."
        )
    allowed_status = {"accepted", "tentative", "declined"}
    status_lower = response_status.lower()
    if status_lower not in allowed_status:
        raise Exception("response_status must be one of 'accepted', 'tentative', or 'declined'")

    payload = {
        "attendees": [
            {
                "email": user_email,
                "responseStatus": status_lower,
            }
        ]
    }
    params = {"sendUpdates": send_updates} if send_updates else None
    event = _google_calendar_api_request(
        "PATCH",
        f"/calendars/{calendar_id}/events/{event_id}",
        token,
        params=params,
        data=payload,
    )
    if not isinstance(event, dict):
        raise Exception("Unexpected response when updating RSVP")
    return {
        "action": "respond_event",
        "event": _format_calendar_event(event),
        "response_status": status_lower,
    }


# Map of action names for validation
_CALENDAR_ACTIONS = {
    "list_calendars",
    "list_events",
    "get_event",
    "create_event",
    "update_event",
    "delete_event",
    "respond_event",
}


@tool
def google_calendar(
    action: str,
    calendar_id: str | None = None,
    event_id: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int | None = None,
    query: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    location: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    all_day: bool | None = None,
    timezone: str | None = None,
    attendees: list[str] | None = None,
    reminders: list[int] | None = None,
    recurrence: list[str] | None = None,
    conference: bool | None = None,
    response_status: str | None = None,
    send_updates: str | None = None,
) -> str:
    """Manage Google Calendar events and calendars.

    Actions:
    - "list_calendars": List calendars available to the user.
    - "list_events": List events in a calendar within a time range.
    - "get_event": Fetch a single event by ID.
    - "create_event": Create a new event (requires summary, start_time, end_time or all_day date).
    - "update_event": Update an existing event (requires event_id and at least one field to change).
    - "delete_event": Delete an event permanently (requires event_id).
    - "respond_event": RSVP to an event invitation (event_id + response_status: accepted/tentative/declined).

    Dates must be ISO 8601 strings. Use calendar_id="primary" when unsure.
    Use Todoist for flexible tasks and Google Calendar for time-bound commitments.
    """

    if not _is_google_calendar_configured():
        return json.dumps({"error": "Google Calendar integration not configured"})

    token_info = _get_google_calendar_access_token()
    if not token_info:
        return json.dumps(
            {
                "error": "Google Calendar not connected",
                "message": "Ask the user to connect Google Calendar in Settings first.",
            }
        )

    # Check permission for autonomous agents (write operations require approval)
    check_autonomous_permission("google_calendar", {"operation": action})

    token, calendar_email = token_info
    calendar_id = calendar_id or "primary"

    try:
        if action == "list_calendars":
            result = _google_calendar_list_calendars(token)
        elif action == "list_events":
            result = _google_calendar_list_events(
                token, calendar_id, time_min, time_max, max_results, query
            )
        elif action == "get_event":
            if not event_id:
                return json.dumps({"error": "event_id is required for get_event"})
            result = _google_calendar_get_event(token, calendar_id, event_id)
        elif action == "create_event":
            result = _google_calendar_create_event(
                token,
                calendar_id,
                summary,
                description,
                location,
                start_time,
                end_time,
                timezone,
                all_day,
                attendees,
                reminders,
                recurrence,
                conference,
                send_updates,
            )
        elif action == "update_event":
            if not event_id:
                return json.dumps({"error": "event_id is required for update_event"})
            result = _google_calendar_update_event(
                token,
                calendar_id,
                event_id,
                summary,
                description,
                location,
                start_time,
                end_time,
                timezone,
                all_day,
                attendees,
                reminders,
                recurrence,
                conference,
                send_updates,
            )
        elif action == "delete_event":
            if not event_id:
                return json.dumps({"error": "event_id is required for delete_event"})
            result = _google_calendar_delete_event(token, calendar_id, event_id, send_updates)
        elif action == "respond_event":
            if not event_id or not response_status:
                return json.dumps(
                    {
                        "error": "event_id and response_status are required for respond_event",
                    }
                )
            result = _google_calendar_respond_event(
                token,
                calendar_id,
                event_id,
                response_status,
                calendar_email,
                send_updates,
            )
        else:
            return json.dumps(
                {
                    "error": f"Unknown action: {action}",
                    "available_actions": list(_CALENDAR_ACTIONS),
                }
            )

        return json.dumps(result)

    except Exception as exc:  # pragma: no cover - network interaction
        logger.error(
            "Google Calendar tool error",
            extra={"action": action, "error": str(exc)},
            exc_info=True,
        )
        return json.dumps({"error": str(exc), "action": action})


def is_google_calendar_available() -> bool:
    """Check if Google Calendar integration is configured."""
    return _is_google_calendar_configured()
