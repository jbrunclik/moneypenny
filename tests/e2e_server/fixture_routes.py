"""/test/* feature fixtures: planner, Garmin, agents, KV store, programs."""

from typing import Any

from flask import Blueprint, g, request

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


@fixtures_bp.route("/test/set-jobs-overview", methods=["POST"])
def set_jobs_overview() -> tuple[dict[str, Any], int]:
    """Set the job list (GET /api/jobs) a test renders."""
    from flask import request

    data = request.get_json() or {}
    MOCK_CONFIG["jobs_overview"] = data.get("overview")
    return {"status": "set"}, 200


@fixtures_bp.route("/test/set-job", methods=["POST"])
def set_job() -> tuple[dict[str, Any], int]:
    """Set a standing chat's editor data for GET /api/jobs/:id."""
    from flask import request

    data = request.get_json() or {}
    agent_id = data.get("id")
    if not agent_id:
        return {"error": "Job ID required"}, 400

    if "jobs_by_id" not in MOCK_CONFIG:
        MOCK_CONFIG["jobs_by_id"] = {}
    MOCK_CONFIG["jobs_by_id"][agent_id] = data
    return {"status": "set"}, 200


@fixtures_bp.route("/test/seed-whats-new", methods=["POST"])
def seed_whats_new() -> tuple[dict[str, Any], int]:
    """Seed the local user's What's new chat with one announcement, or with
    the posts in the body ({"posts": [markdown, ...]})."""
    from src.enums import MessageRole

    user = g.db.get_or_create_user(email="local@localhost", name="Local User")
    conv_id = g.db.whats_new_conversation_for_post(user.id, "Novinky")
    body = request.get_json(silent=True) or {}
    if posts := body.get("posts"):
        for text in posts:
            g.db.add_message(conv_id, MessageRole.ASSISTANT, str(text), language="cs")
        return {"status": "seeded", "conversation_id": conv_id}, 200
    post = (
        # The stored form: announcements.py turns the file's "# Title" into "## Title"
        "## Novinka\nTady se dozvíte, co je nového.\n\n"
        "**Agenti**\n- Agenty teď založíte v chatu.\n- Jeden seznam všeho, co běží.\n\n"
        "**Drobnosti**\n- Ťuknutí na tlačítko dolů se už neztratí.\n\n"
        "Tenhle chat je jen pro čtení."
    )
    g.db.add_message(conv_id, MessageRole.ASSISTANT, post, language="cs")
    return {"status": "seeded", "conversation_id": conv_id}, 200


@fixtures_bp.route("/test/seed-proposal", methods=["POST"])
def seed_proposal() -> tuple[dict[str, Any], int]:
    """A chat whose last reply shows one pending reminder card (a real
    schedule_item proposal: approving it stores the reminder)."""
    import uuid

    from src.agent.tools import scheduling  # noqa: F401 - registers the kind
    from src.db.models import Proposal
    from src.enums import MessageRole
    from src.utils.clock import utc_now

    user = g.db.get_or_create_user(email="local@localhost", name="Local User")
    conv = g.db.create_conversation(user.id, "Plumber")
    g.db.add_message(conv.id, MessageRole.USER, "Remind me Friday at 8 to call the plumber")
    reply = g.db.add_message(
        conv.id, MessageRole.ASSISTANT, "I can remind you on Friday at 8:00 - shall I?"
    )
    payload: dict[str, object] = {
        "kind": "reminder",
        "text": "Call the plumber",
        "next_run_at": "2099-11-13T07:00:00+00:00",
        "when": "Fri 13 Nov 2099 08:00",
        "ends": "then done",
    }
    g.db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=user.id,
            conversation_id=conv.id,
            message_id=reply.id,
            request_id="e2e-seed",
            kind="schedule_item",
            summary='Reminder: "Call the plumber"',
            details={"When": "Fri 13 Nov 2099 08:00 (Europe/Prague)", "Ends": "then done"},
            options=[{"label": "Set it up", "description": "", "payload": payload}],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
        )
    )
    return {"status": "seeded", "conversation_id": conv.id}, 200


@fixtures_bp.route("/test/seed-agent", methods=["POST"])
def seed_agent() -> tuple[dict[str, Any], int]:
    """Seed a real agent (a standing chat + its standing job) for job list tests."""
    from flask import request

    data = request.get_json() or {}
    user = g.db.get_or_create_user(email="local@localhost", name="Local User")
    agent = g.db.create_standing_chat(
        user_id=user.id,
        name=data.get("name", "Coach"),
        instructions=data.get("instructions", "Coach my rides."),
        schedule=data.get("schedule", "0 20 * * *"),
        timezone="Europe/Prague",
    )
    return {"job_id": agent.id, "conversation_id": agent.conversation_id}, 200


@fixtures_bp.route("/test/seed-agent-with-approval", methods=["POST"])
def seed_agent_with_approval() -> tuple[dict[str, Any], int]:
    """Seed an agent whose run is parked on its card: the waiting message
    and a pending run proposal under it (step 2 of the one approval mechanism)."""
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
    agent = g.db.create_standing_chat(
        user_id=user.id,
        name=agent_name,
        description="Test agent for E2E",
        instructions="You are a test agent.",
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

    # The run is parked: its waiting message, and its card (a run proposal)
    import uuid
    from datetime import timedelta

    from src.db.models import Proposal

    waiting = g.db.add_message(
        conversation_id=agent.conversation_id,
        role="assistant",
        content=f"**Waiting for your approval**\n\n{approval_description}",
    )
    card = g.db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=user.id,
            conversation_id=agent.conversation_id or "",
            message_id=waiting.id,
            request_id="",
            kind="agent_action",
            summary=approval_description,
            details={"Tool": tool_name},
            options=[
                {
                    "label": "Approve",
                    "description": "",
                    "payload": {"tool": tool_name, "args": {}, "signature": None},
                }
            ],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
            origin="run",
            job_id=agent.id,
            expires_at=utc_now() + timedelta(hours=24),
        )
    )

    return {
        "status": "seeded",
        "job_id": agent.id,
        "conversation_id": agent.conversation_id,
        "approval_id": card.id,
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
