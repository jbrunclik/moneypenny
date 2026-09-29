"""Tests for the Todoist project, section and collaborator actions.

Drives the real ``todoist`` tool; only the HTTP seam
(``todoist_client.todoist_api_request``) and the token lookup are faked, the
same seam evals/fakes.py replaces.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.tools.todoist import todoist
from src.agent.tools.todoist_client import TodoistTokenRejectedError

Call = tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]


class FakeTodoistApi:
    """Records requests; answers from canned (method, endpoint) responses."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.responses: dict[tuple[str, str], Any] = {}

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


@pytest.fixture
def api() -> Generator[FakeTodoistApi]:
    fake = FakeTodoistApi()
    with (
        patch("src.agent.tools.todoist_client.get_todoist_token", return_value="tok"),
        patch("src.agent.tools.todoist_client.todoist_api_request", fake),
    ):
        yield fake


def run(**args: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(todoist.invoke(args))
    return result


class TestListProjects:
    def test_formats_projects_with_optional_metadata(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects")] = [
            {"id": "p0", "name": "Inbox", "inbox_project": True, "color": "grey"},
            {
                "id": "p1",
                "name": "Work",
                "color": "blue",
                "is_favorite": True,
                "view_style": "board",
                "is_shared": True,
            },
            {"id": "p2", "name": "Clients", "parent_id": "p1"},
        ]

        result = run(action="list_projects")

        assert result["action"] == "list_projects"
        assert result["count"] == 3
        inbox, work, clients = result["projects"]
        assert inbox == {
            "id": "p0",
            "name": "Inbox",
            "color": "grey",
            "is_favorite": False,
            "is_inbox_project": True,
        }
        assert work == {
            "id": "p1",
            "name": "Work",
            "color": "blue",
            "is_favorite": True,
            "view_style": "board",
            "is_shared": True,
        }
        assert clients["parent_id"] == "p1"
        assert "is_inbox_project" not in clients

    def test_non_list_response_yields_empty_listing(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects")] = None

        assert run(action="list_projects") == {
            "action": "list_projects",
            "count": 0,
            "projects": [],
        }


class TestProjectLifecycle:
    def test_get_project(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects/p1")] = {"id": "p1", "name": "Work"}

        assert run(action="get_project", project_id="p1") == {
            "action": "get_project",
            "project": {"id": "p1", "name": "Work"},
        }

    def test_get_project_bad_response_is_an_error_envelope(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects/p1")] = None

        assert run(action="get_project", project_id="p1") == {
            "error": "Failed to fetch project",
            "action": "get_project",
        }

    def test_add_project_sends_only_given_fields(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/projects")] = {"id": "p9", "name": "Garden"}

        result = run(action="add_project", project_name="Garden")

        assert result == {
            "action": "add_project",
            "success": True,
            "project": {"id": "p9", "name": "Garden"},
        }
        assert api.calls == [("POST", "/projects", {"name": "Garden"}, None)]

    def test_add_project_maps_all_options(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/projects")] = {"id": "p9"}

        run(
            action="add_project",
            project_name="Garden",
            color="green",
            parent_project_id="p1",
            is_favorite=False,
            view_style="board",
        )

        assert api.calls[0][2] == {
            "name": "Garden",
            "color": "green",
            "parent_id": "p1",
            "is_favorite": False,
            "view_style": "board",
        }

    def test_add_project_requires_a_name(self, api: FakeTodoistApi) -> None:
        assert run(action="add_project") == {
            "error": "project_name is required for add_project action"
        }
        assert api.calls == []

    def test_add_project_bad_response_is_an_error_envelope(self, api: FakeTodoistApi) -> None:
        assert run(action="add_project", project_name="Garden")["error"] == (
            "Failed to create project"
        )

    def test_update_project_renames(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/projects/p1")] = {"id": "p1", "name": "Job"}

        result = run(action="update_project", project_id="p1", project_name="Job", color="red")

        assert result["success"] is True
        assert result["project"] == {"id": "p1", "name": "Job"}
        assert api.calls == [("POST", "/projects/p1", {"name": "Job", "color": "red"}, None)]

    def test_update_project_can_move_to_top_level(self, api: FakeTodoistApi) -> None:
        # An empty parent id is a real update ("move to top level"), unlike
        # add_project where it is simply omitted
        api.responses[("POST", "/projects/p2")] = {"id": "p2"}

        run(action="update_project", project_id="p2", parent_project_id="", is_favorite=True)

        assert api.calls[0][2] == {"parent_id": "", "is_favorite": True}

    def test_update_project_without_fields_is_refused_without_a_request(
        self, api: FakeTodoistApi
    ) -> None:
        assert run(action="update_project", project_id="p1") == {
            "error": "No project fields provided for update"
        }
        assert api.calls == []

    def test_update_project_bad_response_is_an_error_envelope(self, api: FakeTodoistApi) -> None:
        result = run(action="update_project", project_id="p1", view_style="list")

        assert result == {"error": "Failed to update project", "action": "update_project"}

    @pytest.mark.parametrize(
        ("action", "method", "endpoint", "message"),
        [
            ("delete_project", "DELETE", "/projects/p1", "Project deleted"),
            ("archive_project", "POST", "/projects/p1/archive", "Project archived"),
            ("unarchive_project", "POST", "/projects/p1/unarchive", "Project unarchived"),
        ],
    )
    def test_state_changes_confirm_the_project(
        self, api: FakeTodoistApi, action: str, method: str, endpoint: str, message: str
    ) -> None:
        result = run(action=action, project_id="p1")

        assert result == {
            "action": action,
            "success": True,
            "project_id": "p1",
            "message": message,
        }
        assert api.calls == [(method, endpoint, None, None)]

    @pytest.mark.parametrize("action", ["get_project", "delete_project", "archive_project"])
    def test_project_actions_require_project_id(self, api: FakeTodoistApi, action: str) -> None:
        assert run(action=action) == {"error": f"project_id is required for {action} action"}
        assert api.calls == []


class TestSections:
    def test_list_sections_sorted_by_order(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/sections")] = [
            {"id": "s2", "name": "Done", "section_order": 3},
            {"id": "s1", "name": "To Do", "section_order": 1},
            {"id": "s3", "name": "Unordered"},
        ]

        result = run(action="list_sections", project_id="p1")

        assert result["project_id"] == "p1"
        assert result["count"] == 3
        assert [s["id"] for s in result["sections"]] == ["s3", "s1", "s2"]
        assert result["sections"][1] == {"id": "s1", "name": "To Do", "order": 1}
        assert api.calls == [("GET", "/sections", None, {"project_id": "p1"})]

    def test_list_sections_non_list_response_is_empty(self, api: FakeTodoistApi) -> None:
        result = run(action="list_sections", project_id="p1")

        assert result["count"] == 0
        assert result["sections"] == []

    def test_get_section(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/sections/s1")] = {"id": "s1", "name": "To Do"}

        assert run(action="get_section", section_id="s1")["section"] == {
            "id": "s1",
            "name": "To Do",
        }

    def test_get_section_bad_response(self, api: FakeTodoistApi) -> None:
        assert run(action="get_section", section_id="s1")["error"] == "Failed to fetch section"

    def test_add_section(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/sections")] = {"id": "s5", "name": "Later"}

        result = run(action="add_section", project_id="p1", section_name="Later")

        assert result == {
            "action": "add_section",
            "success": True,
            "section": {"id": "s5", "name": "Later"},
        }
        assert api.calls[0][2] == {"project_id": "p1", "name": "Later"}

    def test_add_section_requires_project_and_name(self, api: FakeTodoistApi) -> None:
        assert run(action="add_section", project_id="p1") == {
            "error": "project_id and section_name are required for add_section action"
        }
        assert api.calls == []

    def test_add_section_bad_response(self, api: FakeTodoistApi) -> None:
        result = run(action="add_section", project_id="p1", section_name="Later")

        assert result["error"] == "Failed to create section"

    def test_update_section(self, api: FakeTodoistApi) -> None:
        api.responses[("POST", "/sections/s1")] = {"id": "s1", "name": "Doing"}

        result = run(action="update_section", section_id="s1", section_name="Doing")

        assert result["success"] is True
        assert api.calls == [("POST", "/sections/s1", {"name": "Doing"}, None)]

    def test_update_section_bad_response(self, api: FakeTodoistApi) -> None:
        result = run(action="update_section", section_id="s1", section_name="Doing")

        assert result["error"] == "Failed to update section"

    def test_delete_section(self, api: FakeTodoistApi) -> None:
        assert run(action="delete_section", section_id="s1") == {
            "action": "delete_section",
            "success": True,
            "section_id": "s1",
            "message": "Section deleted",
        }
        assert api.calls == [("DELETE", "/sections/s1", None, None)]


class TestCollaborators:
    def test_lists_assignable_people(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects/p1/collaborators")] = [
            {"id": "u1", "name": "Jane", "email": "jane@example.com", "image_id": "x"},
        ]

        assert run(action="list_collaborators", project_id="p1") == {
            "action": "list_collaborators",
            "project_id": "p1",
            "count": 1,
            "collaborators": [{"id": "u1", "name": "Jane", "email": "jane@example.com"}],
        }

    def test_non_list_response_is_empty(self, api: FakeTodoistApi) -> None:
        assert run(action="list_collaborators", project_id="p1")["collaborators"] == []


class TestErrorEnvelopes:
    def test_api_error_is_reported_with_the_action(self, api: FakeTodoistApi) -> None:
        api.responses[("DELETE", "/projects/p1")] = Exception(
            'Todoist API error (404): {"error":"Project not found"}'
        )

        assert run(action="delete_project", project_id="p1") == {
            "error": 'Todoist API error (404): {"error":"Project not found"}',
            "action": "delete_project",
        }

    def test_rejected_token_reports_a_disconnected_integration(self, api: FakeTodoistApi) -> None:
        api.responses[("GET", "/projects")] = TodoistTokenRejectedError("401")

        result = run(action="list_projects")

        assert result["error"] == "Todoist disconnected"
        assert result["retriable"] is False
