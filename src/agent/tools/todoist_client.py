"""Todoist HTTP layer: token lookup, REST and Sync API requests.

Action modules call these through the module (``todoist_client.todoist_api_request``)
so tests and the eval fakes have a single patch point.
"""

from __future__ import annotations

import json as json_module
import uuid
from typing import Any

import httpx

from src.agent.tools.context import get_conversation_context
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Todoist JSON as the API sends it: untyped beyond these shapes
TodoistParams = dict[str, Any]
TodoistItems = list[dict[str, Any]]
TodoistResponse = dict[str, Any] | TodoistItems


class TodoistTokenRejectedError(Exception):
    """Todoist rejected the stored token (revoked or expired)."""


def get_todoist_token() -> str | None:
    """Get the current user's Todoist access token.

    Returns None if user is not connected to Todoist.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None

    user = db.get_user_by_id(user_id)
    if not user:
        return None

    return user.todoist_access_token


# A list beyond this many pages (50 items each by default) is cut: the task
# action caps what reaches the model far below it anyway (TODOIST_MAX_TASK_RESULTS)
MAX_LIST_PAGES = 10


def todoist_api_request(
    method: str,
    endpoint: str,
    token: str,
    data: TodoistParams | None = None,
    params: TodoistParams | None = None,
) -> TodoistResponse | None:
    """Make a request to the Todoist REST API; a list comes back whole.

    API v1 pages list responses ({"results": [...], "next_cursor": ...}, 50 per
    page): the cursor is followed, up to MAX_LIST_PAGES, and the items are
    returned as one list. Stopping at the first page handed a user with 51+
    tasks the first 50 as if they were all.

    Raises:
        Exception: On API errors
    """
    result = _todoist_request(method, endpoint, token, data, params)
    if isinstance(result, dict) and "results" in result:
        return _collect_pages(endpoint, token, params, result)
    return result


def _collect_pages(
    endpoint: str, token: str, params: TodoistParams | None, first: TodoistParams
) -> TodoistItems:
    """The items of a paged list response, following next_cursor."""
    items: TodoistItems = list(first["results"])
    cursor = first.get("next_cursor")
    pages = 1
    while cursor and pages < MAX_LIST_PAGES:
        page = _todoist_request("GET", endpoint, token, None, {**(params or {}), "cursor": cursor})
        if not isinstance(page, dict):
            break
        items.extend(page.get("results") or [])
        cursor = page.get("next_cursor")
        pages += 1
    if cursor:
        logger.warning(
            "Todoist list cut at the page bound", extra={"endpoint": endpoint, "items": len(items)}
        )
    return items


def _todoist_request(
    method: str,
    endpoint: str,
    token: str,
    data: TodoistParams | None,
    params: TodoistParams | None,
) -> TodoistResponse | None:
    """One request to the Todoist REST API, the JSON response as sent.

    Args:
        method: HTTP method (GET, POST, DELETE)
        endpoint: API endpoint path (e.g., "/tasks")
        token: Todoist access token
        data: Request body for POST requests
        params: Query parameters

    Returns:
        JSON response or None for DELETE requests

    Raises:
        Exception: On API errors
    """
    url = f"{Config.TODOIST_API_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if method == "GET":
            response = httpx.get(
                url,
                headers=headers,
                params=params,
                timeout=Config.TODOIST_API_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            response = httpx.post(
                url, headers=headers, json=data, timeout=Config.TODOIST_API_TIMEOUT_SECONDS
            )
        elif method == "DELETE":
            response = httpx.delete(
                url, headers=headers, timeout=Config.TODOIST_API_TIMEOUT_SECONDS
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code == 204:  # No content (successful DELETE)
            return None

        if response.status_code >= 400:
            error_msg = response.text
            logger.warning(
                "Todoist API error",
                extra={
                    "status_code": response.status_code,
                    "error": error_msg,
                    "endpoint": endpoint,
                },
            )
            # Revoked/expired token: surfaced as "disconnected" by the tool
            if response.status_code in (401, 403, 410):
                raise TodoistTokenRejectedError(
                    f"Todoist rejected the token ({response.status_code})"
                )
            raise Exception(f"Todoist API error ({response.status_code}): {error_msg}")

        result: TodoistResponse = response.json()
        return result

    except (httpx.HTTPError, json_module.JSONDecodeError) as e:
        logger.error(  # noqa: TRY400 - network or JSON error, re-raised with context
            "Todoist API request failed", extra={"error": str(e), "endpoint": endpoint}
        )
        raise Exception(f"Failed to connect to Todoist: {e}") from e


def todoist_sync_request(
    token: str,
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make a request to the Todoist Sync API.

    The Sync API is used for operations not supported by the REST API,
    such as moving tasks between sections.

    Args:
        token: Todoist access token
        commands: List of command objects (e.g., [{"type": "item_move", "uuid": ..., "args": {...}}])

    Returns:
        Sync response with sync_status for each command

    Raises:
        Exception: On API errors
    """

    url = "https://api.todoist.com/api/v1/sync"
    headers = {"Authorization": f"Bearer {token}"}

    # Add UUIDs to commands if not present
    for cmd in commands:
        if "uuid" not in cmd:
            cmd["uuid"] = str(uuid.uuid4())

    # Sync API expects form-encoded data, not JSON
    data = {"commands": json_module.dumps(commands)}

    try:
        response = httpx.post(
            url, headers=headers, data=data, timeout=Config.TODOIST_API_TIMEOUT_SECONDS
        )

        if response.status_code >= 400:
            error_msg = response.text
            logger.warning(
                "Todoist Sync API error",
                extra={"status_code": response.status_code, "error": error_msg},
            )
            if response.status_code in (401, 403, 410):
                raise TodoistTokenRejectedError(
                    f"Todoist rejected the token ({response.status_code})"
                )
            raise Exception(f"Todoist Sync API error ({response.status_code}): {error_msg}")

        result: dict[str, Any] = response.json()
        return result

    except (httpx.HTTPError, json_module.JSONDecodeError) as e:
        logger.error(  # noqa: TRY400 - network or JSON error, re-raised with context
            "Todoist Sync API request failed", extra={"error": str(e)}
        )
        raise Exception(f"Failed to connect to Todoist Sync API: {e}") from e
