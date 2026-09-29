"""API routes module - registers all route blueprints.

This module imports all route blueprints and provides a function to register them with the Flask app.

Route Organization:
- auth.py: Google authentication (4 routes)
- todoist.py: Todoist integration (4 routes)
- calendar.py: Google Calendar integration (7 routes)
- garmin.py: Garmin Connect integration (4 routes)
- conversations.py: Conversation management (9 routes)
- planner.py: Planner dashboard (4 routes)
- agents.py: Autonomous agents CRUD and execution (9 routes)
- agent_command_center.py: Agents command center (1 route, on agents.api)
- agent_approvals.py: Agent approval requests (3 routes, on agents.api)
- agent_assist.py: Agent AI assist - schedule parsing, prompt enhancer (2 routes, on agents.api)
- chat.py: Chat endpoints (2 routes)
- files.py: File serving (2 routes)
- costs.py: Cost tracking (4 routes)
- settings.py: User settings (2 routes)
- memory.py: User memory management (2 routes)
- system.py: System routes (5 routes)
- kv_store.py: K/V store management (6 routes)
- sports.py: Sports tracking (5 routes)
- language.py: Language learning (5 routes)

Total: 74 endpoints across 19 modules
"""

from apiflask import APIFlask

# Import all route modules. agent_approvals, agent_assist and
# agent_command_center attach their routes to agents.api (one shared "Agents"
# blueprint keeps a single OpenAPI tag and the original endpoint names), so
# they are imported only for that side effect.
from src.api.routes import (
    agent_approvals,  # noqa: F401
    agent_assist,  # noqa: F401
    agent_command_center,  # noqa: F401
    agents,
    auth,
    calendar,
    chat,
    conversations,
    costs,
    files,
    garmin,
    kv_store,
    language,
    memory,
    planner,
    push,
    rouvy,
    settings,
    sports,
    system,
    todoist,
)

# Import db and get_blob_store for backwards compatibility with tests
from src.db.blob_store import get_blob_store  # noqa: F401
from src.db.models import db  # noqa: F401

# For backwards compatibility, export the two main blueprints
# These match the original names used in src/app.py
api = conversations.api  # Primary API blueprint for backwards compatibility
auth_blueprint = auth.auth  # Primary Auth blueprint for backwards compatibility


def register_blueprints(app: APIFlask) -> None:
    """Register all route blueprints with the Flask app.

    Args:
        app: APIFlask application instance
    """
    # Register auth-related blueprints (under /auth prefix)
    app.register_blueprint(auth.auth)
    app.register_blueprint(todoist.auth)
    app.register_blueprint(calendar.auth)
    app.register_blueprint(garmin.auth)
    app.register_blueprint(rouvy.auth)

    # Register API blueprints (under /api prefix)
    app.register_blueprint(system.api)
    app.register_blueprint(memory.api)
    app.register_blueprint(settings.api)
    app.register_blueprint(conversations.api)
    app.register_blueprint(planner.api)
    app.register_blueprint(agents.api)
    app.register_blueprint(chat.api)
    app.register_blueprint(files.api)
    app.register_blueprint(costs.api)
    app.register_blueprint(kv_store.api)
    app.register_blueprint(sports.api)
    app.register_blueprint(language.api)
    app.register_blueprint(push.api)


__all__ = [
    "api",
    "auth_blueprint",
    "register_blueprints",
]
