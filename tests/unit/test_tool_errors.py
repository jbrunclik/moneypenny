"""Rule B5: agent tools report failures in one shape (tool_error).

check_tool_results recognises a failure only as a JSON object with an "error"
key (or an exception the ToolNode catches); a plain "Error: ..." string reads
as a success, so the model gets no retry guidance and the UI shows no failure.
"""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import ToolMessage

from src.agent.graph import tool_message_error
from src.agent.tools.agent_kv import kv_store
from src.agent.tools.conversation_search import search_conversations
from src.agent.tools.errors import action_result, tool_error
from src.agent.tools.google_calendar import google_calendar
from src.agent.tools.memory import search_memory
from src.agent.tools.todoist import todoist
from src.agent.tools.trigger_agent import trigger_agent

TOOLS = Path(__file__).resolve().parents[2] / "src" / "agent" / "tools"


def _recognised(content: str) -> tuple[str, bool] | None:
    return tool_message_error(ToolMessage(content=content, tool_call_id="1"))


def test_tool_error_is_recognised_as_a_retriable_failure() -> None:
    assert _recognised(tool_error("Key too long")) == ("Key too long", True)


def test_a_permanent_failure_says_so() -> None:
    assert _recognised(tool_error("Not configured", retriable=False)) == ("Not configured", False)


def test_extra_fields_ride_along() -> None:
    assert json.loads(tool_error("No query", results=[])) == {"error": "No query", "results": []}


def test_kv_store_failures_are_recognised() -> None:
    with (
        patch("src.agent.tools.agent_kv.get_conversation_context", return_value=("c1", "u1")),
        patch("src.agent.tools.agent_kv.get_sports_context", return_value={"id": "p1"}),
    ):
        result = kv_store.invoke({"action": "explode"})
    assert _recognised(result) == (
        "Invalid action 'explode'. Use 'get', 'set', 'merge', 'delete', or 'list'.",
        True,
    )


def test_search_failures_are_recognised() -> None:
    for tool, module in (
        (search_memory, "src.agent.tools.memory"),
        (search_conversations, "src.agent.tools.conversation_search"),
    ):
        with patch(f"{module}.get_conversation_context", return_value=("c1", "u1")):
            result = tool.invoke({"query": "  "})
        assert _recognised(result) == ("'query' is required.", True), tool.name


def test_trigger_agent_outside_an_agent_is_a_permanent_failure() -> None:
    result = trigger_agent.invoke({"agent_name": "Mailer", "message": "go"})
    recognised = _recognised(result)
    assert recognised is not None
    assert recognised[1] is False


def test_an_action_result_without_error_is_serialized_as_is() -> None:
    assert json.loads(action_result({"action": "x", "success": True})) == {
        "action": "x",
        "success": True,
    }


def test_an_action_result_with_error_becomes_the_envelope() -> None:
    result = action_result({"action": "x", "success": False, "error": "Nope"})
    assert result == tool_error("Nope", action="x", success=False)
    assert _recognised(result) == ("Nope", True)


def test_an_action_result_keeps_a_permanent_failure_permanent() -> None:
    assert _recognised(action_result({"error": "Gone", "retriable": False})) == ("Gone", False)


def test_a_non_text_action_error_becomes_its_json() -> None:
    result = json.loads(action_result({"error": {"error": "Item not found", "error_code": 22}}))
    assert result == {"error": '{"error": "Item not found", "error_code": 22}'}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"action": "update_task", "task_id": "t1"}, "No fields to update provided"),
        (
            {"action": "update_project", "project_id": "p1"},
            "No project fields provided for update",
        ),
        (
            {"action": "move_task", "task_id": "t1"},
            "Exactly one of section_id, project_id, or parent_id must be provided for move_task",
        ),
    ],
)
def test_todoist_action_failures_are_recognised(args: dict[str, str], message: str) -> None:
    with (
        patch("src.agent.tools.todoist_client.get_todoist_token", return_value="tok"),
        patch("src.agent.tools.todoist_client.todoist_api_request") as api,
    ):
        result = todoist.invoke(args)
    assert _recognised(result) == (message, True)
    api.assert_not_called()


def test_todoist_invalid_filter_is_recognised() -> None:
    rejected = Exception('Todoist API error (400): {"error_tag":"INVALID_SEARCH_QUERY"}')
    with (
        patch("src.agent.tools.todoist_client.get_todoist_token", return_value="tok"),
        patch("src.agent.tools.todoist_client.todoist_api_request", side_effect=rejected),
    ):
        result = todoist.invoke({"action": "list_tasks", "filter_string": "due soon"})
    recognised = _recognised(result)
    assert recognised is not None
    assert recognised[0].startswith("Todoist rejected the filter 'due soon'")
    assert recognised[1] is True
    assert json.loads(result)["failed_filter"] == "due soon"


def test_calendar_update_without_fields_is_recognised() -> None:
    with (
        patch("src.agent.tools.google_calendar._is_google_calendar_configured", return_value=True),
        patch(
            "src.agent.tools.google_calendar._get_google_calendar_access_token",
            return_value=("tok", "user@example.com"),
        ),
        patch("src.agent.tools.google_calendar._google_calendar_api_request") as api,
    ):
        result = google_calendar.invoke({"action": "update_event", "event_id": "e1"})
    assert _recognised(result) == ("No fields to update provided", True)
    api.assert_not_called()


def _error_string_returns(path: Path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        first = value.values[0] if isinstance(value, ast.JoinedStr) and value.values else value
        if isinstance(first, ast.Constant) and str(first.value).startswith("Error"):
            lines.append(node.lineno)
    return lines


def test_no_tool_returns_a_plain_error_string() -> None:
    found = [
        f"{path.relative_to(TOOLS.parents[2])}:{line}"
        for path in sorted(TOOLS.rglob("*.py"))
        for line in _error_string_returns(path)
    ]
    assert not found, "Return tool_error(...) instead of an 'Error: ...' string:\n" + "\n".join(
        found
    )
