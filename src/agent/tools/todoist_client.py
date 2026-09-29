"""Todoist HTTP layer: token lookup, REST and Sync API requests.

Action modules call these through the module (``todoist_client.todoist_api_request``)
so tests and the eval fakes have a single patch point.
"""

from __future__ import annotations

import json as json_module
import uuid
from typing import Any

from src.agent.tools.context import get_conversation_context
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class TodoistTokenRejectedError(Exception):
    """Todoist rejected the stored token (revoked or expired)."""


def get_todoist_token() -> str | None:
    """Get the current user's Todoist access token.

    Returns None if user is not connected to Todoist.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None

    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user:
        return None

    return user.todoist_access_token


def todoist_api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Make a request to the Todoist REST API.

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
    import requests

    url = f"{Config.TODOIST_API_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if method == "GET":
            response = requests.get(
                url, headers=headers, params=params, timeout=Config.TODOIST_API_TIMEOUT
            )
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            response = requests.post(
                url, headers=headers, json=data, timeout=Config.TODOIST_API_TIMEOUT
            )
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=Config.TODOIST_API_TIMEOUT)
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

        result: dict[str, Any] | list[dict[str, Any]] = response.json()

        # API v1 wraps list responses in {"results": [...], "next_cursor": ...}
        if isinstance(result, dict) and "results" in result:
            result = result["results"]

        return result

    except requests.RequestException as e:
        logger.error("Todoist API request failed", extra={"error": str(e), "endpoint": endpoint})
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

    import requests

    url = "https://api.todoist.com/api/v1/sync"
    headers = {"Authorization": f"Bearer {token}"}

    # Add UUIDs to commands if not present
    for cmd in commands:
        if "uuid" not in cmd:
            cmd["uuid"] = str(uuid.uuid4())

    # Sync API expects form-encoded data, not JSON
    data = {"commands": json_module.dumps(commands)}

    try:
        response = requests.post(
            url, headers=headers, data=data, timeout=Config.TODOIST_API_TIMEOUT
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

    except requests.RequestException as e:
        logger.error("Todoist Sync API request failed", extra={"error": str(e)})
        raise Exception(f"Failed to connect to Todoist Sync API: {e}") from e
