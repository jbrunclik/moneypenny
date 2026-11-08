"""API routes module - registers all route blueprints.

This module imports all route blueprints and provides a function to register them with the Flask app.

Route Organization:
- auth.py: Google authentication (4 routes)
- todoist.py: Todoist integration (4 routes)
- calendar.py: Google Calendar integration (7 routes)
- garmin.py: Garmin Connect integration (4 routes)
- conversations.py: Conversation list, CRUD, anonymous mode, sync (7 routes)
- conversation_messages.py: Message fetch/delete, message pages, truncation (4 routes, on conversations.api)
- conversation_organize.py: Archive, unarchive, pin, archived list (5 routes, on conversations.api)
- conversation_search.py: Full-text search (1 route, on conversations.api)
- conversation_trash.py: Trash list, restore, permanent delete, empty (4 routes, on conversations.api)
- schedules.py: Scheduled items - a chat's items, cancel, pause, resume (4 routes, on conversations.api)
- planner.py: Planner dashboard (4 routes)
- jobs.py: The job list; standing chat CRUD, runs, run now, viewed, sync (9 routes)
- approvals.py: Approval requests from job runs (3 routes, on jobs.api)
- agent_assist.py: Editor AI assist - schedule parsing, prompt enhancer (2 routes, on jobs.api)
- chat.py: Chat endpoints (2 routes)
- files.py: File serving (2 routes)
- costs.py: Cost tracking (4 routes)
- settings.py: User settings (2 routes)
- memory.py: User memory management (2 routes)
- system.py: System routes (5 routes)
- kv_store.py: K/V store management (6 routes)
- artifacts.py: Artifact versions and saved state (2 routes)
- sports.py: Sports tracking (5 routes)
- language.py: Language learning (5 routes)

Total: 78 endpoints across 20 modules
"""

from apiflask import APIFlask

# Import all route modules. approvals and agent_assist
# attach their routes to jobs.api (one shared "Jobs"
# blueprint keeps a single OpenAPI tag and the original endpoint names), so
# they are imported only for that side effect (admin_device_checks does the
# same for admin.api). conversation_messages,
# conversation_organize, conversation_search and conversation_trash do the
# same for conversations.api.
from src.api.routes import (
    admin,
    admin_device_checks,  # noqa: F401 - imported for its routes
    agent_assist,  # noqa: F401 - imported for its routes
    approvals,  # noqa: F401 - imported for its routes
    artifacts,
    auth,
    calendar,
    chat,
    client_errors,
    conversation_messages,  # noqa: F401 - imported for its routes
    conversation_organize,  # noqa: F401 - imported for its routes
    conversation_search,  # noqa: F401 - imported for its routes
    conversation_trash,  # noqa: F401 - imported for its routes
    conversations,
    costs,
    files,
    garmin,
    jobs,
    kv_store,
    language,
    memory,
    planner,
    push,
    rouvy,
    schedules,  # noqa: F401 - imported for its routes
    settings,
    sports,
    system,
    todoist,
)

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
    app.register_blueprint(jobs.api)
    app.register_blueprint(chat.api)
    app.register_blueprint(files.api)
    app.register_blueprint(artifacts.api)
    app.register_blueprint(costs.api)
    app.register_blueprint(kv_store.api)
    app.register_blueprint(sports.api)
    app.register_blueprint(language.api)
    app.register_blueprint(push.api)
    app.register_blueprint(admin.api)
    app.register_blueprint(client_errors.api)


__all__ = [
    "api",
    "auth_blueprint",
    "register_blueprints",
]
