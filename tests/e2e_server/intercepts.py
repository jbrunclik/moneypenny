"""Fake integration endpoints: search, planner and connection status, agents,
KV store and memories answer from the per-test mock config when it is set,
and build files a test deleted answer 404."""

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from fnmatch import fnmatch
from typing import Any

from flask import Flask, g, jsonify, request
from pydantic import BaseModel

from tests.e2e_server.context import MOCK_CONFIG


def _as_response(model: type[BaseModel], data: dict[str, Any]) -> Any:
    """Serialize through the route's response model, as the real route does:
    every field present, defaults included (the spec marks them required)."""
    return jsonify(model.model_validate(data).model_dump(mode="json"))


def intercept_missing_assets() -> tuple[str, int] | None:
    """404 the build files a test deleted: the server answers, as in production,
    and no Playwright interception sits on the page's chunk loads."""
    patterns = MOCK_CONFIG.get("missing_assets", ())
    if not patterns or not request.path.startswith("/static/assets/"):
        return None
    name = request.path.removeprefix("/static/assets/")
    if any(fnmatch(name, pattern) for pattern in patterns):
        return "", 404
    return None


# Override search endpoint using before_request to intercept /api/search
def intercept_search() -> Any | None:
    from flask import jsonify, request

    if (
        request.path == "/api/search"
        and request.method == "GET"
        and MOCK_CONFIG.get("search_results") is not None
    ):
        query = request.args.get("q", "")
        return jsonify(
            {
                "results": MOCK_CONFIG["search_results"],
                "total": MOCK_CONFIG.get("search_total", 0),
                "query": query,
            }
        )
    return None


# Override planner endpoints to return mock data
def _mock_planner_day(
    i: int, today: date, calendar_connected: bool, todoist_connected: bool
) -> dict[str, Any]:
    """Day `i` of the default mock dashboard."""
    day = today + timedelta(days=i)
    day_name = ["Today", "Tomorrow"][i] if i < 2 else day.strftime("%A")
    return {
        "date": day.isoformat(),
        "day_name": day_name,
        "events": [
            {
                "id": f"event-{i}-1",
                "summary": f"Meeting {i + 1}",
                "start": f"{day.isoformat()}T10:00:00",
                "end": f"{day.isoformat()}T11:00:00",
                "is_all_day": False,
                "location": "Conference Room",
                "attendees": [],
                "organizer": {
                    "email": "test@example.com",
                    "display_name": "Test User",
                    "self": True,
                },
                "calendar_id": "primary",
                "calendar_summary": "My Calendar",
            }
        ]
        if calendar_connected and i < 3
        else [],
        "tasks": [
            {
                "id": f"task-{i}-1",
                "content": f"Task {i + 1}",
                "priority": 2,
                "project_name": "Work",
                "due_string": day_name,
            }
        ]
        if todoist_connected and i < 4
        else [],
    }


def _planner_dashboard() -> Any:
    """GET /api/planner: the test's dashboard, else a generated week."""
    from src.api.schemas.planner import PlannerDashboardResponse

    todoist_connected = MOCK_CONFIG.get("planner_todoist_connected", False)
    calendar_connected = MOCK_CONFIG.get("planner_calendar_connected", False)

    # Return custom dashboard if set
    if MOCK_CONFIG.get("planner_dashboard"):
        return jsonify(MOCK_CONFIG["planner_dashboard"])

    today = datetime.now().date()
    days = [_mock_planner_day(i, today, calendar_connected, todoist_connected) for i in range(7)]
    return _as_response(
        PlannerDashboardResponse,
        {
            "days": days,
            "overdue_tasks": [
                {
                    "id": "task-overdue-1",
                    "content": "Overdue task",
                    "priority": 1,
                    "project_name": "Urgent",
                    "due_string": "Yesterday",
                }
            ]
            if todoist_connected
            else [],
            "todoist_connected": todoist_connected,
            "calendar_connected": calendar_connected,
            "garmin_connected": False,
            "weather_connected": False,
            "todoist_error": None,
            "calendar_error": None,
            "garmin_error": None,
            "weather_error": None,
            "weather_location": None,
            "health_summary": None,
            "server_time": datetime.now().isoformat(),
        },
    )


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _planner_conversation() -> Any:
    """GET /api/planner/conversation: the local user's planner conversation."""
    from src.api.schemas.planner import PlannerConversationResponse

    user = g.db.get_or_create_user(
        email="local@localhost",
        name="Local User",
    )
    # Get or create planner conversation (single method handles both)
    conv = g.db.get_or_create_planner_conversation(user.id)
    messages = g.db.get_messages(conv.id)

    # For visual tests: always include at least one dummy message to prevent proactive analysis
    if len(messages) == 0:
        messages = [
            type(
                "Message",
                (),
                {
                    "id": "dummy-msg-1",
                    "role": "assistant",
                    "content": "Ready to help with your planning!",
                    "created_at": datetime.now(),
                    "files": [],
                },
            )()
        ]

    return _as_response(
        PlannerConversationResponse,
        {
            "id": conv.id,
            "title": conv.title,
            "model": conv.model,
            "created_at": _iso(conv.created_at),
            "updated_at": _iso(conv.updated_at),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": _iso(m.created_at),
                    "files": m.files or [],
                }
                for m in messages
            ],
            "was_reset": False,
        },
    )


def _planner_reset() -> Any:
    user = g.db.get_or_create_user(
        email="local@localhost",
        name="Local User",
    )
    g.db.reset_planner_conversation(user.id)
    return jsonify({"success": True, "message": "Planner conversation reset"})


def _todoist_status() -> Any:
    """For planner visibility."""
    connected = MOCK_CONFIG.get("planner_todoist_connected", False)
    return jsonify(
        {
            "connected": connected,
            "todoist_email": "test@todoist.com" if connected else None,
            "connected_at": datetime.now().isoformat() if connected else None,
            "needs_reconnect": False,
        }
    )


def _calendar_status() -> Any:
    """For planner visibility."""
    connected = MOCK_CONFIG.get("planner_calendar_connected", False)
    return jsonify(
        {
            "connected": connected,
            "calendar_email": "test@gmail.com" if connected else None,
            "connected_at": datetime.now().isoformat() if connected else None,
            "needs_reconnect": False,
        }
    )


def _garmin_status() -> Any:
    garmin_connected = MOCK_CONFIG.get("garmin_connected", False)
    garmin_needs_reconnect = MOCK_CONFIG.get("garmin_needs_reconnect", False)
    return jsonify(
        {
            "connected": garmin_connected,
            "connected_at": datetime.now().isoformat() if garmin_connected else None,
            "needs_reconnect": garmin_needs_reconnect,
        }
    )


def _rouvy_status() -> Any:
    """Disconnected by default in E2E."""
    rouvy_connected = MOCK_CONFIG.get("rouvy_connected", False)
    return jsonify(
        {
            "connected": rouvy_connected,
            "connected_at": datetime.now().isoformat() if rouvy_connected else None,
            "needs_reconnect": MOCK_CONFIG.get("rouvy_needs_reconnect", False),
        }
    )


def _command_center() -> Any:
    """For agents testing: the test's command center, else an empty one."""
    from src.api.schemas.agents import CommandCenterResponse

    if MOCK_CONFIG.get("agents_command_center"):
        return jsonify(MOCK_CONFIG["agents_command_center"])
    return _as_response(
        CommandCenterResponse,
        {
            "pending_approvals": [],
            "agents": [],
            "recent_executions": [],
            "total_unread": 0,
            "agents_waiting": 0,
            "stats": {},
        },
    )


_PLANNER_INTERCEPTS: dict[tuple[str, str], Callable[[], Any]] = {
    ("GET", "/api/planner"): _planner_dashboard,
    ("GET", "/api/planner/conversation"): _planner_conversation,
    ("POST", "/api/planner/reset"): _planner_reset,
    ("GET", "/auth/todoist/status"): _todoist_status,
    ("GET", "/auth/calendar/status"): _calendar_status,
    ("GET", "/auth/garmin/status"): _garmin_status,
    ("GET", "/auth/rouvy/status"): _rouvy_status,
    ("GET", "/api/agents/command-center"): _command_center,
}


def intercept_planner() -> Any | None:
    handler = _PLANNER_INTERCEPTS.get((request.method, request.path))
    if handler:
        return handler()

    # Intercept /api/agents/:id for individual agent testing
    agent_match = re.match(r"^/api/agents/([a-zA-Z0-9_-]+)$", request.path)
    if agent_match and request.method == "GET":
        agent_id = agent_match.group(1)
        agents_by_id = MOCK_CONFIG.get("agents_by_id", {})
        if agent_id in agents_by_id:
            return jsonify(agents_by_id[agent_id])
        # Fall through to real endpoint if no mock data

    return None


# Override KV store and memories endpoints to return mock data
def intercept_kv_store() -> Any | None:
    from flask import jsonify, request

    from src.config import Config

    if (
        request.path == "/api/kv"
        and request.method == "GET"
        and MOCK_CONFIG.get("kv_namespaces") is not None
    ):
        return jsonify({"namespaces": MOCK_CONFIG["kv_namespaces"]})

    if (
        request.path.startswith("/api/kv/")
        and request.method == "GET"
        and MOCK_CONFIG.get("kv_keys") is not None
    ):
        namespace = request.path[len("/api/kv/") :]
        keys = MOCK_CONFIG["kv_keys"].get(namespace, [])
        return jsonify({"namespace": namespace, "keys": keys})

    if (
        request.path == "/api/memories"
        and request.method == "GET"
        and MOCK_CONFIG.get("memories") is not None
    ):
        return jsonify(
            {
                "memories": MOCK_CONFIG["memories"],
                "limit": Config.MEMORY_MAX_ENTRIES,
            }
        )

    # The storage page also loads the soft-deleted list; served here so
    # tests can drive the "Recently deleted" section explicitly.
    if request.path == "/api/memories/deleted" and request.method == "GET":
        return jsonify(
            {
                "memories": MOCK_CONFIG.get("deleted_memories") or [],
                "limit": Config.MEMORY_MAX_ENTRIES,
            }
        )

    return None


def register_intercepts(app: Flask) -> None:
    """Answer the faked endpoints before their real routes run."""
    app.before_request(intercept_missing_assets)
    app.before_request(intercept_search)
    app.before_request(intercept_planner)
    app.before_request(intercept_kv_store)
