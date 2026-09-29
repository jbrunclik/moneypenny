"""Uniform "integration not connected" tool results.

Integration tools stay bound whenever the integration is configured
server-side, so a user whose connection lapsed still reaches the tool and
gets this result. It distinguishes the two cases, because they need
different replies:

- was connected, no longer works (expired session, revoked token): the user
  believes it is connected, so the agent must say plainly that it got
  disconnected and how to reconnect - not act as if it lacks the capability
  (Sep 2026: "Garmin not connected" 14x in 30 days, mostly expired sessions);
- never connected: offer to use it once the user connects it.

A deliberate disconnect in Settings clears both the token and the
``*_connected_at`` timestamp, so either one still being present means the
connection broke rather than was removed.
"""

from __future__ import annotations

from typing import Any

from src.agent.tools.context import get_conversation_context
from src.db.models import db

_LABELS = {
    "garmin": "Garmin",
    "todoist": "Todoist",
    "google_calendar": "Google Calendar",
    "rouvy": "Rouvy",
}

# User attribute holding each integration's credential
_TOKEN_FIELDS = {
    "garmin": "garmin_token",
    "todoist": "todoist_access_token",
    "google_calendar": "google_calendar_access_token",
    "rouvy": "rouvy_session",
}


def _was_connected(integration: str) -> bool:
    _, user_id = get_conversation_context()
    if not user_id:
        return False
    user = db.get_user_by_id(user_id)
    if not user:
        return False
    return bool(
        getattr(user, _TOKEN_FIELDS[integration], None)
        or getattr(user, f"{integration}_connected_at", None)
    )


def not_connected_result(integration: str, *, was_connected: bool | None = None) -> dict[str, Any]:
    """Tool result for an integration the current user cannot use right now.

    Args:
        integration: One of garmin, todoist, google_calendar, rouvy
        was_connected: Known state (e.g. the API just rejected a stored token);
            looked up from the user record when omitted
    """
    label = _LABELS[integration]
    if was_connected is None:
        was_connected = _was_connected(integration)
    if was_connected:
        return {
            "error": f"{label} disconnected",
            "retriable": False,
            "message": (
                f"The user's {label} connection stopped working (the session expired or "
                f"access was revoked). Tell the user plainly that their {label} integration "
                f"got disconnected and that they can reconnect it in Settings, then help "
                f"with whatever does not need {label}. Do not claim you lack {label} "
                "support or access in general, and do not retry this call."
            ),
        }
    return {
        "error": f"{label} not connected",
        "retriable": False,
        "message": (
            f"The user has not connected {label}. Tell them you can use it once they "
            f"connect {label} in Settings, then help with whatever does not need it. "
            "Do not retry this call."
        ),
    }
