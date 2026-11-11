"""Rouvy workout CRUD tool.

Uses the stored session cookie (see src/auth/rouvy_auth.py) to call the
riders.rouvy.com React-Router `.data` endpoints via httpx. On an expired session
it re-logs-in headlessly with the stored credentials, re-persists the cookie,
and retries once. Playwright is only used for (re)login, never for CRUD.

Session refresh: ``rouvy_session`` wraps a 1h Firebase id token. Once it has
expired, Rouvy refreshes it server-side, rotates the cookie via Set-Cookie and
answers with a turbo-stream redirect to the SAME url instead of running the
loader/action. We persist the rotated cookie and retry the request once.

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
from collections.abc import Mapping
from typing import Any

import httpx
from langchain_core.tools import tool

from src.agent.tools.browser import is_browser_available
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.integration_status import not_connected_result
from src.agent.tools.permission_check import call_arguments, check_autonomous_permission
from src.auth import rouvy_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger
from src.utils.tls import shared_ssl_context

logger = get_logger(__name__)


class RouvyNotConnectedError(Exception):
    """User has not connected Rouvy."""


class RouvySessionExpiredError(Exception):
    """Session expired and automated refresh failed — user must reconnect."""


class RouvyBlockedError(Exception):
    """Rouvy's Cloudflare answered with its bot challenge: no session problem,
    so no re-login (that only ran into the same wall for ~50 s, Nov 2026)."""


_SESSION_COOKIE = "rouvy_session"  # a cookie name, not a secret


def _base() -> str:
    return Config.ROUVY_RIDERS_URL


def _client_request(
    method: str, url: str, kwargs: dict[str, Any], jar: dict[str, str]
) -> httpx.Response:
    """Single httpx request with the given cookie jar. Isolated for test seams."""
    with httpx.Client(
        cookies=jar,
        timeout=Config.ROUVY_HTTP_TIMEOUT_SECONDS,
        follow_redirects=False,
        verify=shared_ssl_context(),
    ) as c:
        return c.request(method, url, **kwargs)


def _is_cloudflare_challenge(resp: httpx.Response) -> bool:
    """Cloudflare's "Just a moment..." bot challenge (403, or 503, HTML)."""
    if resp.headers.get("cf-mitigated") == "challenge":
        return True
    html = "text/html" in resp.headers.get("content-type", "")
    return resp.status_code in (403, 503) and html and "Just a moment" in resp.text[:1000]


def _is_sign_in_redirect(resp: httpx.Response) -> bool:
    """A dead or missing session since Nov 2026: a 202 single-fetch redirect to
    account.rouvy.com/sign-in instead of a 401/403 or an HTML login page."""
    return (
        resp.status_code == 202
        and '"redirect"' in resp.text[:400]
        and "/sign-in" in resp.text[:600]
    )


def _looks_expired(resp: httpx.Response) -> bool:
    if _is_sign_in_redirect(resp):
        return True
    if resp.status_code in (401, 403):
        return True
    if resp.status_code in (302, 307) and "sign-in" in resp.headers.get("location", ""):
        return True
    ctype = resp.headers.get("content-type", "")
    # A `.data` endpoint returning an HTML login page means the cookie is dead.
    return bool("text/html" in ctype and "sign in" in resp.text[:500].lower())


def _is_refresh_redirect(resp: httpx.Response) -> bool:
    """Token-refresh response: rotated session cookie + turbo-stream redirect body."""
    return bool(resp.cookies.get(_SESSION_COOKIE)) and '"redirect"' in resp.text[:400]


def _persist_rotated_cookies(user: User, resp: httpx.Response) -> dict[str, str] | None:
    """Persist cookies Rouvy rotated on this response; return the new jar (or None)."""
    updates = {name: value for name, value in resp.cookies.items() if value}
    if not updates.get(_SESSION_COOKIE) or not user.rouvy_session:
        return None
    new_session = rouvy_auth.merge_cookie_values(user.rouvy_session, updates)
    db.update_user_rouvy_session(user.id, new_session)
    user.rouvy_session = new_session
    return rouvy_auth.cookies_to_jar(new_session)


def _authed_request(user: User, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue a request, retrying once on token rotation and re-logging-in once on expiry."""
    if not user.rouvy_session:
        raise RouvyNotConnectedError()
    jar = rouvy_auth.cookies_to_jar(user.rouvy_session)
    # The login's browser identity: Cloudflare challenges httpx's default (Nov 2026)
    headers = {
        **kwargs.pop("headers", {}),
        "User-Agent": rouvy_auth.session_user_agent(user.rouvy_session),
    }
    kwargs = {**kwargs, "headers": headers}
    resp = _client_request(method, url, kwargs, jar)
    if _is_cloudflare_challenge(resp):
        logger.warning(
            "Rouvy request met the Cloudflare challenge", extra={"status": resp.status_code}
        )
        raise RouvyBlockedError()
    rotated_jar = _persist_rotated_cookies(user, resp)
    if rotated_jar is not None and _is_refresh_redirect(resp):
        resp = _client_request(method, url, kwargs, rotated_jar)
    if not _looks_expired(resp):
        return resp
    # Refresh: re-login with stored creds, persist, retry once.
    if not (user.rouvy_email and user.rouvy_password):
        raise RouvySessionExpiredError()
    try:
        new_session = rouvy_auth.login(user.rouvy_email, user.rouvy_password)
    except rouvy_auth.RouvyAuthError as e:
        raise RouvySessionExpiredError() from e
    db.update_user_rouvy_session(user.id, new_session)
    user.rouvy_session = new_session
    jar = rouvy_auth.cookies_to_jar(new_session)
    kwargs["headers"]["User-Agent"] = rouvy_auth.session_user_agent(new_session)
    resp = _client_request(method, url, kwargs, jar)
    if _looks_expired(resp):
        raise RouvySessionExpiredError()
    return resp


def _turbo_data(text: str) -> dict[str, object]:
    """The flat fields of a turbo-stream reply's ``data`` object.

    A reply is one JSON array of interned values: objects map ``"_<key
    index>"`` to a value index, negative indexes are sentinels (undefined), e.g.
    `[{"_1":2},"data",{"_3":-5,"_6":7},"error",...,"workoutId","4904455"]`.
    Returns {} for anything that doesn't decode that way.
    """
    try:
        values = json.loads(text.splitlines()[0] if text else "")
    except json.JSONDecodeError, IndexError:
        return {}
    if not (isinstance(values, list) and values and isinstance(values[0], dict)):
        return {}

    def at(index: object) -> object:
        if isinstance(index, int) and 0 <= index < len(values):
            return values[index]
        return None

    def key(ref: str) -> str | None:
        name = at(int(ref[1:])) if ref.startswith("_") and ref[1:].isdigit() else None
        return name if isinstance(name, str) else None

    data = next((at(v) for k, v in values[0].items() if key(k) == "data"), None)
    if not isinstance(data, dict):
        return {}
    return {name: at(v) for k, v in data.items() if (name := key(k)) is not None}


def _parse_created_id(resp: httpx.Response) -> int:
    """Extract the new workout id from a create response (turbo-stream).

    Since Nov 2026 the id comes back quoted (`"workoutId","4904455"`; before,
    `"workoutId",4183941`), and a rejected upload names its reason in
    ``error`` ("Failed to import workout") with no id. Reading only an unquoted
    number reported real uploads as failures, so retries made duplicates.
    """
    data = _turbo_data(resp.text)
    error = data.get("error")
    if isinstance(error, str) and error:
        raise ValueError(f"Rouvy rejected the workout: {error}")
    wid = data.get("workoutId")
    if isinstance(wid, int) or (isinstance(wid, str) and wid.isdigit()):
        return int(wid)
    m = re.search(r'"workoutId"\s*,\s*"?(\d+)', resp.text)
    if m:
        return int(m.group(1))
    logger.warning(
        "Rouvy create reply not understood",
        # Shape only, never values: replies can carry the user's profile
        extra={
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "chars": len(resp.text),
            "fields": sorted(data),
        },
    )
    raise ValueError("could not parse created workout id from Rouvy response")


def _parse_workout_list(resp: httpx.Response) -> list[dict[str, Any]]:
    """Extract [{id, name}] from the created-collection turbo-stream payload.

    The payload interleaves values; created workouts appear as a stringified id
    immediately followed by the name string, e.g.
    `...,"4183941","ZZ PROBE4 - delete me",...`. Workout ids are 7 digits today;
    the cap at 10 keeps the 12-digit Firebase sender id in the embedded app ENV
    (`"219456523004","FIREBASE_PROJECT_ID"`) from being mistaken for one.
    """
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for wid, wname in re.findall(r'"(\d{5,10})"\s*,\s*"([^"]+)"', resp.text):
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
    _, user_id = get_conversation_context()
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


def _read_workouts(user: User, action: str, workout_id: int | None) -> str:
    """list or get."""
    if action == "list":
        return json.dumps({"success": True, "workouts": rouvy_list(user)})
    if not workout_id:
        return tool_error("get needs workout_id.", success=False)
    return json.dumps({"success": True, "workout": rouvy_get(user, int(workout_id))})


def _write_workout(
    user: User,
    action: str,
    workout_id: int | None,
    content: str | None,
    name: str | None,
    description: str | None,
) -> str:
    """create, update or delete."""
    if action == "create":
        if not content or not name:
            return tool_error("create needs content and name.", success=False)
        return json.dumps({"success": True, **rouvy_create(user, content, name, description)})
    if action == "update":
        if not workout_id or not content or not name:
            return tool_error("update needs workout_id, content, name.", success=False)
        res = rouvy_update(user, int(workout_id), content, name, description)
        return json.dumps({"success": True, "note": "workout id/URL changed", **res})
    if not workout_id:
        return tool_error("delete needs workout_id.", success=False)
    return json.dumps({"success": True, **rouvy_delete(user, int(workout_id))})


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
    # In a run its grants decide (a change without the write level is a
    # draft, a delete always needs approval); in chat a delete waits on the
    # turn's card. Before anything runs
    if held := check_autonomous_permission(
        "rouvy_workout", call_arguments(rouvy_workout, locals())
    ):
        return held
    user = _resolve_user()
    if user is None or not user.rouvy_session:
        return not_connected_result("rouvy", success=False)
    try:
        if action in ("list", "get"):
            return _read_workouts(user, action, workout_id)
        if action in ("create", "update", "delete"):
            return _write_workout(user, action, workout_id, content, name, description)
        return tool_error(f"Unknown action: {action}", success=False)
    except RouvyNotConnectedError:
        return not_connected_result("rouvy", success=False)
    except RouvySessionExpiredError:
        # Automatic re-login failed: the stored credentials no longer work
        return not_connected_result("rouvy", was_connected=True, success=False)
    except RouvyBlockedError:
        return tool_error(
            "Rouvy is blocking automated access right now (its bot protection), so this did not"
            " reach Rouvy. Tell the user; reconnecting will not help.",
            success=False,
        )
    except Exception as e:  # tool must return, not raise
        logger.exception("rouvy_workout failed", extra={"action": action, "error": str(e)})
        return tool_error(f"Rouvy request failed: {e}", success=False)


def workout_name(args: Mapping[str, object]) -> str | None:
    """The workout a delete removes, by name (for its card, src/agent/chat_changes.py)."""
    user = _resolve_user()
    if user is None or not user.rouvy_session or not args.get("workout_id"):
        return None
    wanted = str(args["workout_id"])
    return next((str(w.get("name")) for w in rouvy_list(user) if str(w.get("id")) == wanted), None)
