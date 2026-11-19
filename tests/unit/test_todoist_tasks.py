"""Tests for the Todoist task actions (src/agent/tools/todoist_tasks.py).

Covers task formatting, list filtering/enrichment/truncation, invalid-filter
guidance, the add/update payloads, move semantics and how API failures come
back as tool errors. Drives the real ``todoist`` tool; only the HTTP seams
(``todoist_client.todoist_api_request`` / ``todoist_sync_request``) and the
token lookup are faked.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.tools.todoist import todoist
from src.agent.tools.todoist_client import TodoistTokenRejectedError
from src.agent.tools.todoist_tasks import format_task, todoist_move_task
from src.config import Config

Call = tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]

INVALID_FILTER_ERROR = Exception(
    'Todoist API error (400): {"error":"The search query is incorrect",'
    '"error_code":55,"error_tag":"INVALID_SEARCH_QUERY","http_code":400}'
)


class FakeTodoistApi:
    """Records REST and Sync requests; answers from canned responses."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.responses: dict[tuple[str, str], Any] = {}
        self.sync_commands: list[dict[str, Any]] = []
        self.sync_status: str | dict[str, Any] = "ok"

    def __call__(
        self,
        method: str,
        endpoint: str,
        token: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        assert token == "tok"
        self.calls.append((method, endpoint, data, params))
        response = self.responses.get((method, endpoint))
        if isinstance(response, Exception):
            raise response
        return response

    def sync(self, token: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
        """Like the real client: stamps a uuid on each command, reports per-uuid status."""
        assert token == "tok"
        for i, cmd in enumerate(commands):
            cmd.setdefault("uuid", f"uuid-{i}")
        self.sync_commands.extend(commands)
        return {"sync_status": {cmd["uuid"]: self.sync_status for cmd in commands}}

    def endpoints(self) -> list[tuple[str, str]]:
        return [(method, endpoint) for method, endpoint, _, _ in self.calls]


@pytest.fixture
def api() -> Generator[FakeTodoistApi]:
    fake = FakeTodoistApi()
    with (
        patch("src.agent.tools.todoist_client.get_todoist_token", return_value="tok"),
        patch("src.agent.tools.todoist_client.todoist_api_request", fake),
        patch("src.agent.tools.todoist_client.todoist_sync_request", fake.sync),
    ):
        yield fake


def run(**args: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(todoist.invoke(args))
    return result


class TestFormatTask:
    def test_a_bare_task_gets_defaults_for_missing_fields(self) -> None:
        assert format_task({"id": "t1", "content": "Buy milk"}) == {
            "id": "t1",
            "content": "Buy milk",
            "description": "",
            "priority": 1,
            "labels": [],
            "is_completed": False,
        }

    def test_due_prefers_the_human_string_and_keeps_recurrence(self) -> None:
        task = {
            "id": "t1",
            "content": "Water plants",
            "due": {"string": "every monday", "date": "2026-10-26", "is_recurring": True},
        }
        formatted = format_task(task)
        assert formatted["due"] == "every monday"
        assert formatted["is_recurring"] is True

    def test_due_falls_back_to_the_date_when_there_is_no_string(self) -> None:
        formatted = format_task({"id": "t1", "content": "x", "due": {"date": "2026-10-26"}})
        assert formatted["due"] == "2026-10-26"
        assert formatted["is_recurring"] is False

    def test_a_null_due_adds_no_due_keys(self) -> None:
        formatted = format_task({"id": "t1", "content": "x", "due": None})
        assert "due" not in formatted
        assert "is_recurring" not in formatted

    def test_priority_labels_and_completion_pass_through(self) -> None:
        formatted = format_task(
            {"id": "t1", "content": "x", "priority": 4, "labels": ["home"], "checked": True}
        )
        assert (formatted["priority"], formatted["labels"], formatted["is_completed"]) == (
            4,
            ["home"],
            True,
        )

    def test_project_and_section_names_come_from_the_maps(self) -> None:
        formatted = format_task(
            {"id": "t1", "content": "x", "project_id": "p1", "section_id": "s1"},
            section_map={"s1": "Backlog"},
            project_map={"p1": "Work"},
        )
        assert formatted["project_name"] == "Work"
        assert formatted["section_name"] == "Backlog"

    def test_ids_missing_from_the_maps_keep_the_id_without_a_name(self) -> None:
        formatted = format_task(
            {"id": "t1", "content": "x", "project_id": "p9", "section_id": "s9"},
            section_map={"s1": "Backlog"},
            project_map={"p1": "Work"},
        )
        assert formatted["project_id"] == "p9"
        assert formatted["section_id"] == "s9"
        assert "project_name" not in formatted
        assert "section_name" not in formatted

    def test_subtask_assignment_duration_and_comments_are_mapped(self) -> None:
        formatted = format_task(
            {
                "id": "t1",
                "content": "x",
                "parent_id": "t0",
                "responsible_uid": "u1",
                "assigned_by_uid": "u2",
                "duration": {"amount": 30, "unit": "minute"},
                "note_count": 2,
            }
        )
        assert formatted["parent_id"] == "t0"
        assert formatted["assignee_id"] == "u1"
        assert formatted["assigner_id"] == "u2"
        assert formatted["duration"] == "30 minute"
        assert formatted["comment_count"] == 2

    def test_zero_comments_are_not_reported(self) -> None:
        assert "comment_count" not in format_task({"id": "t1", "content": "x", "note_count": 0})


class TestListTasks:
    def test_tasks_are_enriched_with_project_and_section_names(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks")] = [
            {"id": "t1", "content": "Report", "project_id": "p1", "section_id": "s1"}
        ]
        api.responses[("GET", "/sections")] = [{"id": "s1", "name": "Doing"}]
        api.responses[("GET", "/projects")] = [{"id": "p1", "name": "Work"}]

        result = run(action="list_tasks")

        assert result["count"] == 1
        assert result["filter"] is None
        task = result["tasks"][0]
        assert (task["project_name"], task["section_name"]) == ("Work", "Doing")

    def test_tasks_without_projects_or_sections_skip_the_lookups(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks")] = [{"id": "t1", "content": "Loose"}]

        run(action="list_tasks")

        assert api.endpoints() == [("GET", "/tasks")]

    def test_a_failed_enrichment_lookup_still_returns_the_tasks(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks")] = [
            {"id": "t1", "content": "Report", "project_id": "p1", "section_id": "s1"}
        ]
        api.responses[("GET", "/sections")] = Exception("Todoist API error (500): boom")
        api.responses[("GET", "/projects")] = [{"id": "p1", "name": "Work"}]

        result = run(action="list_tasks")

        task = result["tasks"][0]
        assert task["project_name"] == "Work"
        assert task["section_id"] == "s1"
        assert "section_name" not in task

    def test_filter_and_project_both_go_to_the_filter_endpoint(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks/filter")] = []

        result = run(action="list_tasks", filter_string="today", project_id="p1")

        assert api.calls == [("GET", "/tasks/filter", None, {"query": "today", "project_id": "p1"})]
        assert result["filter"] == "today"

    def test_a_project_without_filter_lists_that_project_on_tasks(
        self, api: FakeTodoistApi
    ) -> None:
        api.responses[("GET", "/tasks")] = []

        run(action="list_tasks", project_id="p1")

        assert api.calls == [("GET", "/tasks", None, {"project_id": "p1"})]

    def test_a_non_list_response_is_treated_as_no_tasks(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks")] = None

        result = run(action="list_tasks")

        assert (result["count"], result["tasks"]) == (0, [])

    def test_results_over_the_cap_are_truncated_with_a_note(
        self, api: FakeTodoistApi, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "TODOIST_MAX_TASK_RESULTS", 2)
        api.responses[("GET", "/tasks")] = [
            {"id": f"t{i}", "content": f"Task {i}"} for i in range(5)
        ]

        result = run(action="list_tasks")

        assert [t["id"] for t in result["tasks"]] == ["t0", "t1"]
        assert result["count"] == 2
        assert result["truncated"].startswith("3 more tasks matched")

    def test_results_at_the_cap_carry_no_truncation_note(
        self, api: FakeTodoistApi, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "TODOIST_MAX_TASK_RESULTS", 2)
        api.responses[("GET", "/tasks")] = [
            {"id": "t0", "content": "a"},
            {"id": "t1", "content": "b"},
        ]

        assert "truncated" not in run(action="list_tasks")

    def test_an_invalid_filter_returns_retriable_guidance_not_a_raw_error(
        self, api: FakeTodoistApi
    ) -> None:
        api.responses[("GET", "/tasks/filter")] = INVALID_FILTER_ERROR

        result = run(action="list_tasks", filter_string="due this week")

        assert result["action"] == "list_tasks"
        assert result["failed_filter"] == "due this week"
        assert result.get("retriable", True) is True
        assert "'due this week'" in result["error"]
        assert "search query is incorrect" not in result["error"]
        assert "today" in result["valid_examples"]

    def test_other_filter_endpoint_failures_surface_as_tool_errors(
        self, api: FakeTodoistApi
    ) -> None:
        api.responses[("GET", "/tasks/filter")] = Exception("Todoist API error (500): down")

        result = run(action="list_tasks", filter_string="today")

        assert result == {"error": "Todoist API error (500): down", "action": "list_tasks"}

    def test_an_invalid_filter_marker_on_the_unfiltered_path_is_not_rewritten(
        self, api: FakeTodoistApi
    ) -> None:
        api.responses[("GET", "/tasks")] = INVALID_FILTER_ERROR

        result = run(action="list_tasks")

        assert "failed_filter" not in result
        assert result["action"] == "list_tasks"
        assert "INVALID_SEARCH" in result["error"]


class TestAddAndUpdateTask:
    def test_add_sends_only_the_provided_fields(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/tasks")] = {"id": "t1", "content": "Call mom"}

        result = run(action="add_task", content="Call mom", labels=["family"])

        assert api.calls == [
            ("POST", "/tasks", {"content": "Call mom", "labels": ["family"]}, None)
        ]
        assert result == {
            "action": "add_task",
            "success": True,
            "task": {"id": "t1", "content": "Call mom"},
        }

    def test_add_prefers_due_string_over_due_date(self, api: FakeTodoistApi) -> None:
        run(action="add_task", content="x", due_string="tomorrow 3pm", due_date="2026-10-30")

        data = api.calls[0][2]
        assert data is not None
        assert data["due_string"] == "tomorrow 3pm"
        assert "due_date" not in data

    @pytest.mark.parametrize(("given", "sent"), [(9, 4), (-3, 1), (3, 3)])
    def test_priority_is_clamped_to_the_todoist_range(
        self, api: FakeTodoistApi, given: int, sent: int
    ) -> None:
        run(action="add_task", content="x", priority=given)
        run(action="update_task", task_id="t1", priority=given)

        assert [data["priority"] for _, _, data, _ in api.calls if data] == [sent, sent]

    def test_update_can_clear_description_labels_and_assignee(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/tasks/t1")] = {"id": "t1"}

        result = run(action="update_task", task_id="t1", description="", labels=[], assignee_id="")

        assert api.calls == [
            ("POST", "/tasks/t1", {"description": "", "labels": [], "assignee_id": ""}, None)
        ]
        assert result["success"] is True

    def test_update_with_nothing_to_change_makes_no_request(self, api: FakeTodoistApi) -> None:
        result = run(action="update_task", task_id="t1")

        assert result == {"error": "No fields to update provided"}
        assert api.calls == []


class TestMoveTask:
    @pytest.mark.parametrize(
        ("destination", "value"),
        [("section_id", "s2"), ("project_id", "p2"), ("parent_id", "t0")],
    )
    def test_moves_to_exactly_the_given_destination(
        self, api: FakeTodoistApi, destination: str, value: str
    ) -> None:
        result = run(action="move_task", task_id="t1", **{destination: value})

        assert [c["type"] for c in api.sync_commands] == ["item_move"]
        assert api.sync_commands[0]["args"] == {"id": "t1", destination: value}
        assert result == {
            "action": "move_task",
            "success": True,
            "task_id": "t1",
            "message": "Task moved successfully",
        }

    def test_no_destination_is_rejected_without_a_request(self, api: FakeTodoistApi) -> None:
        result = run(action="move_task", task_id="t1")

        assert "Exactly one of" in result["error"]
        assert api.sync_commands == []

    def test_two_destinations_are_rejected_without_a_request(self, api: FakeTodoistApi) -> None:
        result = run(action="move_task", task_id="t1", section_id="s2", project_id="p2")

        assert "Exactly one of" in result["error"]
        assert api.sync_commands == []

    def test_an_empty_destination_is_rejected_without_a_request(self, api: FakeTodoistApi) -> None:
        result = todoist_move_task("tok", "t1", project_id="")

        assert "Exactly one of" in result.get("error", "")
        assert api.sync_commands == []

    def test_a_rejected_sync_command_reports_failure_with_its_error(
        self, api: FakeTodoistApi
    ) -> None:
        api.sync_status = {"error": "Item not found", "error_code": 22}

        result = run(action="move_task", task_id="t1", project_id="p2")

        assert result == {
            "action": "move_task",
            "success": False,
            "error": '{"error": "Item not found", "error_code": 22}',
        }


class TestSimpleTaskActions:
    def test_get_returns_the_raw_task(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks/t1")] = {"id": "t1", "content": "x"}

        assert run(action="get_task", task_id="t1") == {
            "action": "get_task",
            "task": {"id": "t1", "content": "x"},
        }

    @pytest.mark.parametrize(
        ("action", "method", "endpoint"),
        [
            ("complete_task", "POST", "/tasks/t1/close"),
            ("reopen_task", "POST", "/tasks/t1/reopen"),
            ("delete_task", "DELETE", "/tasks/t1"),
        ],
    )
    def test_lifecycle_actions_hit_their_endpoint_and_report_success(
        self, api: FakeTodoistApi, action: str, method: str, endpoint: str
    ) -> None:
        result = run(action=action, task_id="t1")

        assert api.endpoints() == [(method, endpoint)]
        assert (result["action"], result["success"], result["task_id"]) == (action, True, "t1")

    @pytest.mark.parametrize(
        ("action", "method", "endpoint"),
        [
            ("get_task", "GET", "/tasks/t1"),
            ("complete_task", "POST", "/tasks/t1/close"),
            ("delete_task", "DELETE", "/tasks/t1"),
        ],
    )
    def test_api_errors_surface_as_tool_errors_not_success(
        self, api: FakeTodoistApi, action: str, method: str, endpoint: str
    ) -> None:
        api.responses[(method, endpoint)] = Exception("Todoist API error (404): Task not found")

        result = run(action=action, task_id="t1")

        assert result == {"error": "Todoist API error (404): Task not found", "action": action}

    def test_a_rejected_token_reports_a_disconnected_integration(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/tasks")] = TodoistTokenRejectedError("401")

        result = run(action="add_task", content="x")

        assert result["error"] == "Todoist disconnected"
        assert result["retriable"] is False


class TestAddTasks:
    def test_adds_every_entry_in_one_call(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/tasks")] = {"id": "new", "content": "x"}
        result = run(
            action="add_tasks",
            project_id="p1",
            tasks=[{"content": "Milk"}, {"content": "Eggs", "project_id": "p2", "priority": 4}],
        )
        posted = [data for method, _, data, _ in api.calls if method == "POST"]
        assert posted == [
            {"content": "Milk", "project_id": "p1"},
            {"content": "Eggs", "project_id": "p2", "priority": 4},
        ]
        assert result["added_count"] == 2 and result["failed"] == []

    def test_add_tasks_partial_failure(self, api: FakeTodoistApi) -> None:
        def post(
            method: str, endpoint: str, token: str, data: Any = None, params: Any = None
        ) -> Any:
            if data["content"] == "Bad":
                raise Exception("Todoist API error (400): invalid due")
            return {"id": f"id-{data['content']}", "content": data["content"]}

        with patch("src.agent.tools.todoist_client.todoist_api_request", post):
            result = run(action="add_tasks", tasks=[{"content": "Good"}, {"content": "Bad"}])
        assert result["added"] == [{"id": "id-Good", "content": "Good"}]
        assert result["failed"][0]["content"] == "Bad"
        assert "invalid due" in result["failed"][0]["error"]

    def test_every_entry_failing_is_an_error(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/tasks")] = Exception("Todoist API error (500): down")
        result = run(action="add_tasks", tasks=[{"content": "A"}])
        assert "error" in result

    def test_add_tasks_over_the_cap(self, api: FakeTodoistApi) -> None:
        result = run(action="add_tasks", tasks=[{"content": f"t{i}"} for i in range(26)])
        assert "25" in result["error"]
        assert api.calls == []

    def test_add_tasks_needs_tasks(self, api: FakeTodoistApi) -> None:
        assert "tasks" in run(action="add_tasks")["error"]


class TestListCompleted:
    def test_defaults_to_the_last_seven_local_days(self, api: FakeTodoistApi) -> None:
        endpoint = "/tasks/completed/by_completion_date"
        api.responses[("GET", endpoint)] = [
            {
                "id": "t1",
                "content": "Pay trip",
                "project_id": "p1",
                "completed_at": "2026-11-18T09:30:00Z",
            }
        ]
        api.responses[("GET", "/projects")] = [{"id": "p1", "name": "Family"}]
        with patch("src.agent.tools.todoist_completed.utc_now") as now:
            from datetime import UTC, datetime

            now.return_value = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
            result = run(action="list_completed")
        params = next(p for m, e, _, p in api.calls if e == endpoint)
        # Nov 13 00:00 and Nov 20 00:00 Prague (UTC+1)
        assert params["since"] == "2026-11-12T23:00:00Z"
        assert params["until"] == "2026-11-19T23:00:00Z"
        assert result["tasks"] == [
            {
                "id": "t1",
                "content": "Pay trip",
                "project_name": "Family",
                "completed_at": "2026-11-18 10:30",
            }
        ]

    def test_explicit_range_and_project(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/tasks/completed/by_completion_date")] = []
        run(action="list_completed", since="2026-11-01", until="2026-11-02", project_id="p9")
        params = api.calls[0][3]
        assert (params["since"], params["until"], params["project_id"]) == (
            "2026-10-31T23:00:00Z",
            "2026-11-02T23:00:00Z",
            "p9",
        )

    def test_list_completed_bad_range(self, api: FakeTodoistApi) -> None:
        assert "error" in run(action="list_completed", since="2026-11-10", until="2026-11-01")
        assert (
            "3 months"
            in run(action="list_completed", since="2026-01-01", until="2026-11-01")["error"]
        )
        assert "YYYY-MM-DD" in run(action="list_completed", since="last week")["error"]
        assert api.calls == []


def test_add_tasks_hands_the_gate_plain_json(api: FakeTodoistApi) -> None:
    """The gate stores the call for its approval card: the tasks must serialize."""
    seen: dict[str, Any] = {}

    def gate(tool_name: str, tool_args: dict[str, Any]) -> str:
        seen.update(tool_args)
        return "held"

    with patch("src.agent.tools.todoist.check_autonomous_permission", gate):
        assert todoist.invoke({"action": "add_tasks", "tasks": [{"content": "Milk"}]}) == "held"
    assert json.loads(json.dumps(seen))["tasks"] == [{"content": "Milk"}]
