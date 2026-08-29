"""Rouvy workout CRUD tool.

Uses the stored session cookie (see src/auth/rouvy_auth.py) to call the
riders.rouvy.com React-Router `.data` endpoints via httpx. On an expired session
it re-logs-in headlessly with the stored credentials, re-persists the cookie,
and retries once. Playwright is only used for (re)login, never for CRUD.

Endpoint contract (confirmed by recon, cookies-only auth, turbo-stream responses):
- create: POST /resources/workout-upload.data, multipart field `file`
          -> response contains `"workoutId",<id>` (error null on success)
- delete: POST /workouts/{id}.data, urlencoded body id=<id>
- list:   GET /workouts/collections/created.data  (user's created workouts)
- get:    GET /workouts/{id}.data
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from langchain_core.tools import tool

from src.agent.tools.browser import is_browser_available
from src.auth import rouvy_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class RouvyNotConnected(Exception):
    """User has not connected Rouvy."""


class RouvySessionExpired(Exception):
    """Session expired and automated refresh failed — user must reconnect."""


def _base() -> str:
    return Config.ROUVY_RIDERS_URL


def _client_request(
    method: str, url: str, kwargs: dict[str, Any], jar: dict[str, str]
) -> httpx.Response:
    """Single httpx request with the given cookie jar. Isolated for test seams."""
    with httpx.Client(cookies=jar, timeout=Config.ROUVY_HTTP_TIMEOUT, follow_redirects=False) as c:
        return c.request(method, url, **kwargs)


def _looks_expired(resp: httpx.Response) -> bool:
    if resp.status_code in (401, 403):
        return True
    if resp.status_code in (302, 307) and "sign-in" in resp.headers.get("location", ""):
        return True
    ctype = resp.headers.get("content-type", "")
    # A `.data` endpoint returning an HTML login page means the cookie is dead.
    if "text/html" in ctype and "sign in" in resp.text[:500].lower():
        return True
    return False


def _authed_request(user: User, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue a request, refreshing the session once on expiry."""
    if not user.rouvy_session:
        raise RouvyNotConnected()
    jar = rouvy_auth.cookies_to_jar(user.rouvy_session)
    resp = _client_request(method, url, kwargs, jar)
    if not _looks_expired(resp):
        return resp
    # Refresh: re-login with stored creds, persist, retry once.
    if not (user.rouvy_email and user.rouvy_password):
        raise RouvySessionExpired()
    try:
        new_session = rouvy_auth.login(user.rouvy_email, user.rouvy_password)
    except rouvy_auth.RouvyAuthError as e:
        raise RouvySessionExpired() from e
    db.update_user_rouvy_session(user.id, new_session)
    user.rouvy_session = new_session
    jar = rouvy_auth.cookies_to_jar(new_session)
    resp = _client_request(method, url, kwargs, jar)
    if _looks_expired(resp):
        raise RouvySessionExpired()
    return resp


def _parse_created_id(resp: httpx.Response) -> int:
    """Extract the new workout id from a create response (turbo-stream).

    Success looks like `[...,"error",<null-ref>,"workoutId",4183941]`.
    """
    m = re.search(r'"workoutId"\s*,\s*(\d+)', resp.text)
    if not m:
        raise ValueError("could not parse created workout id from Rouvy response")
    return int(m.group(1))


def _parse_workout_list(resp: httpx.Response) -> list[dict[str, Any]]:
    """Extract [{id, name}] from the created-collection turbo-stream payload.

    The payload interleaves values; created workouts appear as a stringified id
    immediately followed by the name string, e.g.
    `...,"4183941","ZZ PROBE4 - delete me",...`.
    """
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for wid, wname in re.findall(r'"(\d{5,})"\s*,\s*"([^"]+)"', resp.text):
        i = int(wid)
        if i not in seen:
            seen.add(i)
            out.append({"id": i, "name": wname})
    return out


def rouvy_create(
    user: User, content: str, name: str, description: str | None = None
) -> dict[str, Any]:
    """Upload a workout (ZWO/ERG/MRC text) → returns {id, workout_url}.

    The multipart field name is `file` (not `workout`).
    """
    filename = f"{(name[:60] or 'workout')}.zwo"
    resp = _authed_request(
        user,
        "POST",
        f"{_base()}/resources/workout-upload.data",
        files={"file": (filename, content, "application/xml")},
    )
    resp.raise_for_status()
    wid = _parse_created_id(resp)
    return {"id": wid, "workout_url": f"{_base()}/workouts/{wid}"}


def rouvy_delete(user: User, workout_id: int) -> dict[str, Any]:
    """Delete a workout: POST /workouts/{id}.data with urlencoded body id=<id>."""
    resp = _authed_request(
        user, "POST", f"{_base()}/workouts/{workout_id}.data", data={"id": str(workout_id)}
    )
    resp.raise_for_status()
    return {"deleted": True, "id": workout_id}


def rouvy_get(user: User, workout_id: int) -> dict[str, Any]:
    resp = _authed_request(user, "GET", f"{_base()}/workouts/{workout_id}.data")
    resp.raise_for_status()
    return {"id": workout_id, "url": f"{_base()}/workouts/{workout_id}", "raw": resp.text[:4000]}


def rouvy_list(user: User) -> list[dict[str, Any]]:
    """List the user's created workouts (Created collection)."""
    resp = _authed_request(user, "GET", f"{_base()}/workouts/collections/created.data")
    resp.raise_for_status()
    return _parse_workout_list(resp)


def rouvy_update(
    user: User, workout_id: int, content: str, name: str, description: str | None = None
) -> dict[str, Any]:
    """Rouvy has no ZWO edit endpoint, so update = delete + create.

    The workout id/URL changes as a result — callers must surface the new URL.
    """
    rouvy_delete(user, workout_id)
    return rouvy_create(user, content, name, description)


def is_rouvy_available() -> bool:
    """Rouvy needs Chromium for (re)login, so it is gated on the browser."""
    return Config.BROWSER_ENABLED and is_browser_available()


def _resolve_user() -> User | None:
    """Resolve the current request's user (same seam garmin.py uses)."""
    from src.agent.tools.context import get_conversation_context

    _, user_id = get_conversation_context()
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


@tool
def rouvy_workout(
    action: str,
    workout_id: int | None = None,
    content: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> str:
    """Manage the user's Rouvy cycling workouts (Rouvy is an indoor cycling app).

    Actions:
    - "list": list the user's created Rouvy workouts (id + name).
    - "get": fetch one workout's details (needs workout_id).
    - "create": upload a workout you authored (needs content = the full ZWO XML,
      and name; optional description). Returns the Rouvy workout URL.
    - "update": REPLACE a workout (needs workout_id, content, name). Implemented
      as delete + create, so the workout's id and URL CHANGE — always give the
      user the new URL from the result.
    - "delete": remove a workout (needs workout_id).

    The user must have connected Rouvy in Settings first.
    """
    user = _resolve_user()
    if user is None or not user.rouvy_session:
        return json.dumps(
            {
                "success": False,
                "error": "Rouvy is not connected. Ask the user to connect Rouvy in Settings first.",
                "retriable": False,
            }
        )
    try:
        if action == "list":
            return json.dumps({"success": True, "workouts": rouvy_list(user)})
        if action == "get":
            if not workout_id:
                return json.dumps({"success": False, "error": "get needs workout_id."})
            return json.dumps({"success": True, "workout": rouvy_get(user, int(workout_id))})
        if action == "create":
            if not content or not name:
                return json.dumps({"success": False, "error": "create needs content and name."})
            return json.dumps({"success": True, **rouvy_create(user, content, name, description)})
        if action == "update":
            if not workout_id or not content or not name:
                return json.dumps(
                    {"success": False, "error": "update needs workout_id, content, name."}
                )
            res = rouvy_update(user, int(workout_id), content, name, description)
            return json.dumps({"success": True, "note": "workout id/URL changed", **res})
        if action == "delete":
            if not workout_id:
                return json.dumps({"success": False, "error": "delete needs workout_id."})
            return json.dumps({"success": True, **rouvy_delete(user, int(workout_id))})
        return json.dumps({"success": False, "error": f"Unknown action: {action}"})
    except RouvyNotConnected:
        return json.dumps(
            {"success": False, "error": "Rouvy is not connected.", "retriable": False}
        )
    except RouvySessionExpired:
        return json.dumps(
            {
                "success": False,
                "error": (
                    "Rouvy session expired and automatic refresh failed. "
                    "Please reconnect in Settings."
                ),
                "retriable": False,
            }
        )
    except Exception as e:  # noqa: BLE001 - tool must return, not raise
        logger.error("rouvy_workout failed", extra={"action": action, "error": str(e)})
        return json.dumps(
            {"success": False, "error": f"Rouvy request failed: {e}", "retriable": True}
        )
