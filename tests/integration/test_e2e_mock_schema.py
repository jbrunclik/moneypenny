"""The E2E mock server's hand-built responses match the API spec (T5).

Playwright runs against the real app with some endpoints answered by
`tests/e2e_server/intercepts.py` from hand-built JSON. A field added or
renamed in a Pydantic schema (and so in `static/openapi.json` and the
generated frontend types) but not in an intercept leaves E2E testing a shape
production never sends. Each intercepted route is called here with
representative mock config and its status and body validated against the
spec.
"""

import itertools
import re
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from openapi_core import OpenAPI
from openapi_core.contrib.werkzeug import WerkzeugOpenAPIRequest, WerkzeugOpenAPIResponse
from openapi_core.exceptions import OpenAPIError
from werkzeug.test import TestResponse

from src.db.models import Database
from tests.e2e_server import intercepts
from tests.e2e_server.context import DEFAULT_CONFIG, isolated_configs
from tests.e2e_server.intercepts import register_intercepts

PROJECT_ROOT = Path(__file__).parent.parent.parent
SPEC_PATH = PROJECT_ROOT / "static" / "openapi.json"

Call = Callable[[str, str, dict[str, Any]], TestResponse]

_SEARCH_RESULT = {
    "conversation_id": "conv-123",
    "conversation_title": "Test Conversation Title",
    "message_id": "msg-456",
    "message_snippet": "A [[HIGHLIGHT]]test[[/HIGHLIGHT]] snippet",
    "match_type": "message",
    "created_at": "2026-10-26T10:00:00",
}

# (method, url, mock config overrides) - every intercepted route, in the
# states the E2E specs put it in
CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/api/search?q=test", {"search_results": [], "search_total": 0}),
    ("GET", "/api/search?q=test", {"search_results": [_SEARCH_RESULT], "search_total": 1}),
    ("GET", "/api/planner", {}),
    (
        "GET",
        "/api/planner",
        {"planner_todoist_connected": True, "planner_calendar_connected": True},
    ),
    ("GET", "/api/planner/conversation", {}),
    ("POST", "/api/planner/reset", {}),
    ("GET", "/auth/todoist/status", {}),
    ("GET", "/auth/todoist/status", {"planner_todoist_connected": True}),
    ("GET", "/auth/calendar/status", {}),
    ("GET", "/auth/calendar/status", {"planner_calendar_connected": True}),
    ("GET", "/auth/garmin/status", {}),
    ("GET", "/auth/garmin/status", {"garmin_connected": True, "garmin_needs_reconnect": True}),
    ("GET", "/auth/rouvy/status", {}),
    ("GET", "/auth/rouvy/status", {"rouvy_connected": True}),
    ("GET", "/api/agents/command-center", {}),
    ("GET", "/api/kv", {"kv_namespaces": []}),
    ("GET", "/api/kv/sports", {"kv_keys": {"sports": []}}),
    ("GET", "/api/memories", {"memories": []}),
    ("GET", "/api/memories/deleted", {}),
]

# Mock config the intercepts return as is: the Playwright test supplies the
# payload, so its shape is that test's business, not the mock's
PASS_THROUGH = {
    "planner_dashboard": "GET /api/planner returns the dashboard posted to /test/set-planner-dashboard",
    "agents_command_center": (
        "GET /api/agents/command-center returns the payload posted to /test/set-agents-command-center"
    ),
    "agents_by_id": "GET /api/agents/<id> returns the agent posted to /test/set-agent",
}


@pytest.fixture
def mock_app(app: Flask, test_database: Database) -> Flask:
    """The app with the E2E intercepts in front of the real routes."""

    @app.before_request
    def _use_test_db() -> None:
        # The E2E server's resolve_db hook sets g.db before the intercepts run
        g.db = test_database

    register_intercepts(app)
    return app


@pytest.fixture
def call(mock_app: Flask) -> Generator[Call]:
    """Call a route with the given mock config (isolated per test id)."""
    client: FlaskClient = mock_app.test_client()
    test_ids = (f"schema-check-{n}" for n in itertools.count())
    used: list[str] = []

    def _call(method: str, url: str, config: dict[str, Any]) -> TestResponse:
        test_id = next(test_ids)
        used.append(test_id)
        isolated_configs[test_id] = {**DEFAULT_CONFIG, **config}
        return client.open(url, method=method, headers={"X-Test-Execution-Id": test_id})

    yield _call
    for test_id in used:
        isolated_configs.pop(test_id, None)


def test_intercepted_responses_match_the_spec(call: Call) -> None:
    # One app for every case: building it (migrations) is the slow part
    openapi = OpenAPI.from_file_path(str(SPEC_PATH))
    errors = []
    for method, url, config in CASES:
        response = call(method, url, config)
        label = f"{method} {url} {config}"
        if response.status_code != 200:
            errors.append(f"{label}: status {response.status_code}")
            continue
        try:
            openapi.validate_response(
                WerkzeugOpenAPIRequest(response.request), WerkzeugOpenAPIResponse(response)
            )
        except OpenAPIError as exc:
            errors.append(f"{label}: {exc.__cause__ or exc}")
    assert not errors, "\n".join(errors)


def test_every_intercepted_path_is_checked() -> None:
    """A new intercept joins CASES, or PASS_THROUGH with its reason."""
    source = Path(intercepts.__file__).read_text()
    paths = {url.split("?")[0] for _, url, _ in CASES}
    exact = set(re.findall(r'request\.path == "([^"]+)"', source))
    prefixes = set(re.findall(r'request\.path\.startswith\("([^"]+)"\)', source))
    assert exact - paths == set()
    assert {p for p in prefixes if not any(path.startswith(p) for path in paths)} == set()
    assert {key for key in PASS_THROUGH if f'"{key}"' not in source} == set()
