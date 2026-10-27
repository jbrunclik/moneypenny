"""/test/* feature fixtures: planner, Garmin, agents, KV store, programs."""

from typing import Any

from flask import Blueprint, g

from tests.e2e_server.context import MOCK_CONFIG, ProxyDatabase

fixtures_bp = Blueprint("test_fixtures", __name__)
# The same stateless proxy the app's global db is swapped for
proxy_db = ProxyDatabase()


@fixtures_bp.route("/test/set-planner-integrations", methods=["POST"])
def set_planner_integrations() -> tuple[dict[str, Any], int]:
    """Set planner integration status for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["planner_todoist_connected"] = data.get("todoist", False)
    MOCK_CONFIG["planner_calendar_connected"] = data.get("calendar", False)
    return {
        "status": "set",
        "todoist": MOCK_CONFIG["planner_todoist_connected"],
        "calendar": MOCK_CONFIG["planner_calendar_connected"],
    }, 200


@fixtures_bp.route("/test/set-planner-dashboard", methods=["POST"])
def set_planner_dashboard() -> tuple[dict[str, Any], int]:
    """Set custom planner dashboard data for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["planner_dashboard"] = data.get("dashboard")
    return {"status": "set"}, 200


@fixtures_bp.route("/test/add-planner-message", methods=["POST"])
def add_planner_message() -> tuple[dict[str, Any], int]:
    """Add a dummy message to planner conversation to prevent proactive analysis."""
    user = g.db.get_or_create_user(
        email="local@localhost",
        name="Local User",
    )
    conv = g.db.get_or_create_planner_conversation(user.id)

    # Add a simple assistant message
    g.db.add_message(
        conversation_id=conv.id,
        role="assistant",
        content="Ready to help with your planning!",
        files=None,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )
    return {"status": "message_added"}, 200


@fixtures_bp.route("/test/clear-planner-config", methods=["POST"])
def clear_planner_config() -> tuple[dict[str, str], int]:
    """Clear planner mock config to restore defaults."""
    MOCK_CONFIG["planner_todoist_connected"] = False
    MOCK_CONFIG["planner_calendar_connected"] = False
    MOCK_CONFIG["planner_dashboard"] = None
    return {"status": "cleared"}, 200


# =============================================================================
# Garmin test routes
# =============================================================================


@fixtures_bp.route("/test/set-garmin-status", methods=["POST"])
def set_garmin_status() -> tuple[dict[str, Any], int]:
    """Set Garmin integration status for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["garmin_connected"] = data.get("connected", False)
    MOCK_CONFIG["garmin_needs_reconnect"] = data.get("needs_reconnect", False)
    return {
        "status": "set",
        "connected": MOCK_CONFIG["garmin_connected"],
        "needs_reconnect": MOCK_CONFIG["garmin_needs_reconnect"],
    }, 200


@fixtures_bp.route("/test/clear-garmin-config", methods=["POST"])
def clear_garmin_config() -> tuple[dict[str, str], int]:
    """Clear Garmin mock config to restore defaults."""
    MOCK_CONFIG["garmin_connected"] = False
    MOCK_CONFIG["garmin_needs_reconnect"] = False
    return {"status": "cleared"}, 200


# =============================================================================
# Agents test routes
# =============================================================================


@fixtures_bp.route("/test/set-agents-command-center", methods=["POST"])
def set_agents_command_center() -> tuple[dict[str, Any], int]:
    """Set custom agents command center data for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["agents_command_center"] = data.get("command_center")
    return {"status": "set"}, 200


@fixtures_bp.route("/test/clear-agents-config", methods=["POST"])
def clear_agents_config() -> tuple[dict[str, str], int]:
    """Clear agents mock config to restore defaults."""
    MOCK_CONFIG["agents_command_center"] = None
    MOCK_CONFIG["agents_by_id"] = {}
    return {"status": "cleared"}, 200


@fixtures_bp.route("/test/set-agent", methods=["POST"])
def set_agent() -> tuple[dict[str, Any], int]:
    """Set individual agent data for testing GET /api/agents/:id."""
    from flask import request

    data = request.get_json() or {}
    agent_id = data.get("id")
    if not agent_id:
        return {"error": "Agent ID required"}, 400

    if "agents_by_id" not in MOCK_CONFIG:
        MOCK_CONFIG["agents_by_id"] = {}
    MOCK_CONFIG["agents_by_id"][agent_id] = data
    return {"status": "set"}, 200


@fixtures_bp.route("/test/seed-agent-with-approval", methods=["POST"])
def seed_agent_with_approval() -> tuple[dict[str, Any], int]:
    """Seed an agent with a conversation containing a pending approval message.

    This is used to test the input blocking when a conversation has a pending approval.
    """
    from flask import request

    data = request.get_json() or {}
    agent_name = data.get("name", "Test Agent")
    approval_description = data.get("description", "Add task: Buy groceries")
    tool_name = data.get("tool_name", "todoist_add_task")

    # Get or create the test user
    user = g.db.get_or_create_user(
        email="local@localhost",
        name="Local User",
    )

    # Create the agent using the proper method
    agent = g.db.create_agent(
        user_id=user.id,
        name=agent_name,
        description="Test agent for E2E",
        system_prompt="You are a test agent.",
        enabled=True,
    )

    # Add trigger message
    from src.utils.clock import utc_now

    now = utc_now().strftime("%Y-%m-%d %H:%M")
    g.db.add_message(
        conversation_id=agent.conversation_id,
        role="user",
        content=f"[Manual trigger at {now} UTC]",
    )

    # Create the pending approval using the proper method
    approval = g.db.create_approval_request(
        agent_id=agent.id,
        user_id=user.id,
        tool_name=tool_name,
        tool_args="{}",
        description=approval_description,
    )

    # Add approval request message with explicit \n to ensure pattern matching works
    approval_content = (
        f"[approval-request:{approval.id}]\n"
        f"I need your permission to: **{approval_description}**\n\n"
        f"Tool: `{tool_name}`\n\n"
        f"Please approve or reject this action."
    )
    g.db.add_message(
        conversation_id=agent.conversation_id,
        role="assistant",
        content=approval_content,
    )

    return {
        "status": "seeded",
        "agent_id": agent.id,
        "conversation_id": agent.conversation_id,
        "approval_id": approval.id,
    }, 200


# =============================================================================
# KV Store test routes
# =============================================================================


@fixtures_bp.route("/test/set-kv-store-data", methods=["POST"])
def set_kv_store_data() -> tuple[dict[str, Any], int]:
    """Set custom KV store data for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["kv_namespaces"] = data.get("namespaces")
    MOCK_CONFIG["kv_keys"] = data.get("keys")  # dict: namespace -> keys list
    return {"status": "set"}, 200


@fixtures_bp.route("/test/set-memories-data", methods=["POST"])
def set_memories_data() -> tuple[dict[str, Any], int]:
    """Set custom memories data for testing."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["memories"] = data.get("memories")
    if "deleted_memories" in data:
        MOCK_CONFIG["deleted_memories"] = data.get("deleted_memories")
    return {"status": "set"}, 200


@fixtures_bp.route("/test/clear-kv-store-config", methods=["POST"])
def clear_kv_store_config() -> tuple[dict[str, str], int]:
    """Clear KV store mock config to restore defaults."""
    MOCK_CONFIG["kv_namespaces"] = None
    MOCK_CONFIG["kv_keys"] = None
    MOCK_CONFIG["memories"] = None
    MOCK_CONFIG["deleted_memories"] = None
    return {"status": "cleared"}, 200


# =============================================================================
# Sports test routes
# =============================================================================


@fixtures_bp.route("/test/set-sports-programs", methods=["POST"])
def set_sports_programs() -> tuple[dict[str, Any], int]:
    """Seed sports programs into KV store for the test user."""
    import json

    from flask import request as flask_request

    data = flask_request.get_json() or {}
    programs = data.get("programs", [])

    # Get or create the same user that auth bypass uses
    # (get_user_by_email never existed on Database - this endpoint
    # 500'd from birth and the visual specs depending on it with it)
    user = g.db.get_or_create_user(email="local@localhost", name="Local User")

    proxy_db.kv_set(user.id, "sports", "programs", json.dumps(programs))
    return {"status": "set", "count": len(programs)}, 200


@fixtures_bp.route("/test/set-language-programs", methods=["POST"])
def set_language_programs() -> tuple[dict[str, Any], int]:
    """Seed language programs into KV store for the test user."""
    import json

    from flask import request as flask_request

    data = flask_request.get_json() or {}
    programs = data.get("programs", [])

    # Get or create the same user that auth bypass uses
    user = g.db.get_or_create_user(email="local@localhost", name="Local User")

    proxy_db.kv_set(user.id, "language", "programs", json.dumps(programs))
    return {"status": "set", "count": len(programs)}, 200
