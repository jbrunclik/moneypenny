"""Fake integration endpoints: search, planner and connection status, agents,
KV store and memories answer from the per-test mock config when it is set."""

from typing import Any

from flask import Flask, g

from tests.e2e_server.context import MOCK_CONFIG


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
def intercept_planner() -> Any | None:  # noqa: C901, PLR0912
    from datetime import datetime, timedelta

    from flask import jsonify, request

    # Intercept /api/planner (dashboard)
    if request.path == "/api/planner" and request.method == "GET":
        todoist_connected = MOCK_CONFIG.get("planner_todoist_connected", False)
        calendar_connected = MOCK_CONFIG.get("planner_calendar_connected", False)

        # Return custom dashboard if set
        if MOCK_CONFIG.get("planner_dashboard"):
            return jsonify(MOCK_CONFIG["planner_dashboard"])

        # Generate default mock dashboard
        today = datetime.now().date()
        days = []
        day_names = ["Today", "Tomorrow"]
        for i in range(7):
            date = today + timedelta(days=i)
            day_name = day_names[i] if i < 2 else date.strftime("%A")
            days.append(
                {
                    "date": date.isoformat(),
                    "day_name": day_name,
                    "events": [
                        {
                            "id": f"event-{i}-1",
                            "summary": f"Meeting {i + 1}",
                            "start": f"{date.isoformat()}T10:00:00",
                            "end": f"{date.isoformat()}T11:00:00",
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
            )

        return jsonify(
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
            }
        )

    # Intercept /api/planner/conversation
    if request.path == "/api/planner/conversation" and request.method == "GET":
        # Get or create a mock planner conversation
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

        return jsonify(
            {
                "id": conv.id,
                "title": conv.title,
                "model": conv.model,
                "created_at": conv.created_at.isoformat()
                if hasattr(conv.created_at, "isoformat")
                else conv.created_at,
                "updated_at": conv.updated_at.isoformat()
                if hasattr(conv.updated_at, "isoformat")
                else conv.updated_at,
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat()
                        if hasattr(m.created_at, "isoformat")
                        else m.created_at,
                        "files": m.files or [],
                    }
                    for m in messages
                ],
                "was_reset": False,
            }
        )

    # Intercept /api/planner/reset
    if request.path == "/api/planner/reset" and request.method == "POST":
        user = g.db.get_or_create_user(
            email="local@localhost",
            name="Local User",
        )
        g.db.reset_planner_conversation(user.id)
        return jsonify({"success": True, "message": "Planner conversation reset"})

    # Intercept /auth/todoist/status for planner visibility
    if request.path == "/auth/todoist/status" and request.method == "GET":
        connected = MOCK_CONFIG.get("planner_todoist_connected", False)
        return jsonify(
            {
                "connected": connected,
                "todoist_email": "test@todoist.com" if connected else None,
                "connected_at": datetime.now().isoformat() if connected else None,
                "needs_reconnect": False,
            }
        )

    # Intercept /auth/calendar/status for planner visibility
    if request.path == "/auth/calendar/status" and request.method == "GET":
        connected = MOCK_CONFIG.get("planner_calendar_connected", False)
        return jsonify(
            {
                "connected": connected,
                "calendar_email": "test@gmail.com" if connected else None,
                "connected_at": datetime.now().isoformat() if connected else None,
                "needs_reconnect": False,
            }
        )

    # Intercept /auth/garmin/status
    if request.path == "/auth/garmin/status" and request.method == "GET":
        garmin_connected = MOCK_CONFIG.get("garmin_connected", False)
        garmin_needs_reconnect = MOCK_CONFIG.get("garmin_needs_reconnect", False)
        return jsonify(
            {
                "connected": garmin_connected,
                "connected_at": datetime.now().isoformat() if garmin_connected else None,
                "needs_reconnect": garmin_needs_reconnect,
            }
        )

    # Intercept /auth/rouvy/status (disconnected by default in E2E)
    if request.path == "/auth/rouvy/status" and request.method == "GET":
        rouvy_connected = MOCK_CONFIG.get("rouvy_connected", False)
        return jsonify(
            {
                "connected": rouvy_connected,
                "connected_at": datetime.now().isoformat() if rouvy_connected else None,
                "needs_reconnect": MOCK_CONFIG.get("rouvy_needs_reconnect", False),
            }
        )

    # Intercept /api/agents/command-center for agents testing
    if request.path == "/api/agents/command-center" and request.method == "GET":
        if MOCK_CONFIG.get("agents_command_center"):
            return jsonify(MOCK_CONFIG["agents_command_center"])
        # Return default empty command center
        return jsonify(
            {
                "pending_approvals": [],
                "agents": [],
                "recent_executions": [],
                "total_unread": 0,
                "agents_waiting": 0,
            }
        )

    # Intercept /api/agents/:id for individual agent testing
    import re

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
    app.before_request(intercept_search)
    app.before_request(intercept_planner)
    app.before_request(intercept_kv_store)
