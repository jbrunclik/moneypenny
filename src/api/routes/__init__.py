"""API routes module - registers all route blueprints.

This module imports all route blueprints and provides a function to register them with the Flask app.

Route Organization:
- auth.py: Google authentication (4 routes)
- todoist.py: Todoist integration (4 routes)
- calendar.py: Google Calendar integration (7 routes)
- conversations.py: Conversation management (9 routes)
- planner.py: Planner dashboard (4 routes)
- agents.py: Autonomous agents (11 routes)
- chat.py: Chat endpoints (2 routes)
- files.py: File serving (2 routes)
- costs.py: Cost tracking (4 routes)
- settings.py: User settings (2 routes)
- memory.py: User memory management (2 routes)
- system.py: System routes (5 routes)

Total: 54 endpoints across 12 modules
"""

from apiflask import APIFlask

# Import all route modules
from src.api.routes import (
    agents,
    auth,
    calendar,
    chat,
    conversations,
    costs,
    files,
    memory,
    planner,
    settings,
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


__all__ = [
    "api",
    "auth_blueprint",
    "register_blueprints",
]
