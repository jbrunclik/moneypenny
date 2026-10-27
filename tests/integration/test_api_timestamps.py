"""Every instant the API sends carries its UTC offset (rule B12).

A timestamp without an offset is parsed as browser-local time by
`new Date()`, so it is an hour or two off wherever the browser is not in the
server's zone. The spec marks each one `format: date-time` (the `Timestamp`
alias in src/api/schemas/base.py), and the endpoints send them in the fixed
`to_api` form.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from apiflask import APIFlask
from flask.testing import FlaskClient

from src.db.models import Conversation, Database, User

_TIMESTAMP_NAME = re.compile(r"(_at|_time|^last_seen|^first_seen|^last_reset)$")
_API_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")


def _properties(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    yield from schema.get("properties", {}).items()


def _is_string(prop: dict[str, Any]) -> bool:
    types = [prop.get("type")] + [option.get("type") for option in prop.get("anyOf", [])]
    return "string" in types


def _format(prop: dict[str, Any]) -> str | None:
    if "format" in prop:
        return str(prop["format"])
    formats = [option.get("format") for option in prop.get("anyOf", []) if option.get("format")]
    return formats[0] if formats else None


def test_response_timestamps_are_date_time_in_the_spec(app: APIFlask) -> None:
    schemas = app.spec["components"]["schemas"]
    undeclared = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        for field, prop in _properties(schema)
        if _TIMESTAMP_NAME.search(field) and _is_string(prop) and _format(prop) != "date-time"
    ]
    assert undeclared == [], "use the Timestamp alias for: " + ", ".join(undeclared)


def _timestamp_values(payload: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _TIMESTAMP_NAME.search(key) and (value is None or isinstance(value, str)):
                yield f"{path}.{key}", value
            else:
                yield from _timestamp_values(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from _timestamp_values(item, f"{path}[{index}]")


@pytest.fixture
def seeded(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> dict[str, str]:
    """One of each timestamped thing a user sees."""
    test_database.add_message(test_conversation.id, "user", "Hello")
    test_database.add_message(test_conversation.id, "assistant", "Hi")
    trashed = test_database.create_conversation(user_id=test_user.id, title="Old")
    test_database.trash_conversation(trashed.id, test_user.id)
    archived = test_database.create_conversation(user_id=test_user.id, title="Kept")
    test_database.archive_conversation(archived.id, test_user.id)
    agent = test_database.create_agent(user_id=test_user.id, name="Watcher", schedule="0 9 * * *")
    execution = test_database.create_execution(agent.id, "manual")
    test_database.update_execution(execution.id, status="completed")
    test_database.create_approval_request(
        agent.id, test_user.id, "send_push", None, "Send a notification"
    )
    test_database.add_memory(test_user.id, "Likes tea", category="preference")
    return {"conversation": test_conversation.id, "agent": agent.id}


def test_endpoints_send_instants_with_an_offset(
    client: FlaskClient, auth_headers: dict[str, str], seeded: dict[str, str]
) -> None:
    paths = [
        "/api/conversations",
        "/api/conversations/archived",
        "/api/conversations/trash",
        "/api/conversations/sync",
        f"/api/conversations/{seeded['conversation']}",
        f"/api/conversations/{seeded['conversation']}/messages",
        "/api/search?q=Hello",
        "/api/agents",
        f"/api/agents/{seeded['agent']}",
        f"/api/agents/{seeded['agent']}/executions",
        f"/api/agents/{seeded['agent']}/conversation/sync",
        "/api/agents/approvals",
        "/api/agents/command-center",
        "/api/memories",
    ]
    seen = 0
    offending = []
    for path in paths:
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200, (path, response.get_json())
        for where, value in _timestamp_values(response.get_json()):
            if value is None:
                continue
            seen += 1
            if not _API_INSTANT.match(value):
                offending.append(f"{path} {where} = {value!r}")
    assert offending == []
    assert seen > 30  # the walk found the timestamps it is meant to check
