"""Unit tests for the Todoist tool (src/agent/tools/todoist*.py)."""

import json
from unittest.mock import MagicMock, patch

# ============================================================================
# Tests for Todoist Tool
# ============================================================================


class TestTodoistTool:
    """Tests for todoist tool."""

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    def test_returns_error_when_not_connected(self, mock_get_token: MagicMock) -> None:
        """Should return error when Todoist is not connected."""
        from src.agent.tools import todoist

        mock_get_token.return_value = None

        result = todoist.invoke({"action": "list_tasks"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not connected" in parsed["error"].lower()

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    def test_returns_error_for_unknown_action(self, mock_get_token: MagicMock) -> None:
        """Should return error for unknown action."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"

        result = todoist.invoke({"action": "unknown_action"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_list_tasks_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully list tasks."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = [
            {
                "id": "task-1",
                "content": "Test task",
                "project_id": "proj-1",
                "section_id": None,
                "priority": 1,
                "due": None,
            }
        ]

        result = todoist.invoke({"action": "list_tasks"})
        parsed = json.loads(result)

        assert "tasks" in parsed
        assert len(parsed["tasks"]) == 1
        assert parsed["tasks"][0]["id"] == "task-1"

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_list_tasks_with_filter_uses_filter_endpoint(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """A filter must hit /tasks/filter with query= - the `filter` param on
        /tasks is silently ignored by API v1 and returns ALL tasks."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = []  # empty -> no enrichment calls

        todoist.invoke({"action": "list_tasks", "filter_string": "overdue"})

        endpoint = mock_api.call_args_list[0][0][1]
        params = mock_api.call_args_list[0][1]["params"]
        assert endpoint == "/tasks/filter"
        assert params == {"query": "overdue"}

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_invalid_filter_returns_actionable_guidance(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """Invalid filter strings were the top Todoist failure (Sep 2026:
        22 in 30 days). The raw API error left the model guessing; the
        result must name the failed filter and show valid syntax."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.side_effect = Exception(
            'Todoist API error (400): {"error":"The search query is incorrect",'
            '"error_code":55,"error_tag":"INVALID_SEARCH_QUERY","http_code":400}'
        )

        parsed = json.loads(
            todoist.invoke({"action": "list_tasks", "filter_string": "tasks due this week"})
        )

        assert parsed["failed_filter"] == "tasks due this week"
        assert parsed["retriable"] is True
        assert "7 days" in parsed["valid_examples"]
        assert "filter" in parsed["error"].lower()

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_list_tasks_without_filter_uses_plain_endpoint(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """Unfiltered listing stays on /tasks and never sends a `filter` param."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = []

        todoist.invoke({"action": "list_tasks"})

        endpoint = mock_api.call_args_list[0][0][1]
        params = mock_api.call_args_list[0][1].get("params", {})
        assert endpoint == "/tasks"
        assert "filter" not in params

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_add_task_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully add a task."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {
            "id": "new-task-1",
            "content": "New task",
        }

        result = todoist.invoke(
            {
                "action": "add_task",
                "content": "New task",
                "due_string": "tomorrow",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "add_task"
        assert parsed["success"] is True

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_complete_task_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully complete a task."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {}  # Close endpoint returns empty

        result = todoist.invoke(
            {
                "action": "complete_task",
                "task_id": "task-123",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "complete_task"
        assert parsed["success"] is True

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_list_collaborators_success(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """Should successfully list project collaborators."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = [
            {
                "id": "user-1",
                "name": "Alice Smith",
                "email": "alice@example.com",
            },
            {
                "id": "user-2",
                "name": "Bob Jones",
                "email": "bob@example.com",
            },
        ]

        result = todoist.invoke(
            {
                "action": "list_collaborators",
                "project_id": "project-123",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "list_collaborators"
        assert parsed["count"] == 2
        assert len(parsed["collaborators"]) == 2
        assert parsed["collaborators"][0]["id"] == "user-1"
        assert parsed["collaborators"][0]["name"] == "Alice Smith"

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_add_task_with_assignee(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully add a task with assignee."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {
            "id": "new-task-1",
            "content": "New task",
            "assignee_id": "user-1",
        }

        result = todoist.invoke(
            {
                "action": "add_task",
                "content": "New task",
                "assignee_id": "user-1",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "add_task"
        assert parsed["success"] is True
        assert parsed["task"]["assignee_id"] == "user-1"
        # Verify the API was called with assignee_id
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][1] == "/tasks"
        assert call_args[1]["data"]["assignee_id"] == "user-1"

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_update_task_with_assignee(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """Should successfully update a task's assignee."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {
            "id": "task-1",
            "content": "Existing task",
            "assignee_id": "user-2",
        }

        result = todoist.invoke(
            {
                "action": "update_task",
                "task_id": "task-1",
                "assignee_id": "user-2",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "update_task"
        assert parsed["success"] is True
        assert parsed["task"]["assignee_id"] == "user-2"
        # Verify the API was called with assignee_id
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][1] == "/tasks/task-1"
        assert call_args[1]["data"]["assignee_id"] == "user-2"

    @patch("src.agent.tools.todoist_client.get_todoist_token")
    @patch("src.agent.tools.todoist_client.todoist_api_request")
    def test_list_tasks_includes_assignee_info(
        self, mock_api: MagicMock, mock_get_token: MagicMock
    ) -> None:
        """Should include assignee_id in task list when present."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = [
            {
                "id": "task-1",
                "content": "Assigned task",
                "project_id": "proj-1",
                "priority": 1,
                "responsible_uid": "user-1",
                "assigned_by_uid": "user-2",
            }
        ]

        result = todoist.invoke({"action": "list_tasks"})
        parsed = json.loads(result)

        assert "tasks" in parsed
        assert len(parsed["tasks"]) == 1
        assert parsed["tasks"][0]["assignee_id"] == "user-1"
        assert parsed["tasks"][0]["assigner_id"] == "user-2"
