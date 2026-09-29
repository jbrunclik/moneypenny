"""Tests for the planner dashboard's Todoist fetch (fetch_todoist_dashboard_data).

Only the HTTP seam (``requests.get``) is faked.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.utils.planner_data import fetch_todoist_dashboard_data

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()


def _response(status: int = 200, body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = "error body"
    return response


class FakeRequests:
    """Answers GETs by endpoint suffix; an Exception value is raised."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.urls: list[str] = []
        self.params: list[Any] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        self.urls.append(url)
        self.params.append(kwargs.get("params"))
        endpoint = "/" + url.rsplit("/", 1)[-1]
        answer = self.routes[endpoint]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def http() -> Generator[FakeRequests]:
    fake = FakeRequests()
    with patch("requests.get", fake.get):
        yield fake


def _task(task_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": task_id, "content": f"Task {task_id}", **extra}


class TestFetchTodoistDashboardData:
    def test_splits_overdue_from_upcoming_and_enriches_names(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(
            body={
                "results": [
                    _task("late", due={"date": YESTERDAY}, project_id="p1"),
                    _task(
                        "soon",
                        due={"date": TOMORROW, "string": "tomorrow", "is_recurring": True},
                        project_id="p1",
                        section_id="s1",
                        priority=4,
                        labels=["focus"],
                    ),
                    _task("undated"),
                ]
            }
        )
        http.routes["/sections"] = _response(body={"results": [{"id": "s1", "name": "Doing"}]})
        http.routes["/projects"] = _response(body=[{"id": "p1", "name": "Work"}])

        upcoming, overdue, error = fetch_todoist_dashboard_data("tok")

        assert error is None
        assert [t.id for t in overdue] == ["late"]
        assert [t.id for t in upcoming] == ["soon", "undated"]
        soon = upcoming[0]
        assert soon.project_name == "Work"
        assert soon.section_name == "Doing"
        assert soon.due_string == "tomorrow"
        assert soon.is_recurring is True
        assert soon.priority == 4
        assert soon.labels == ["focus"]
        assert overdue[0].project_name == "Work"
        assert http.params[0] == {"filter": "7 days | overdue"}

    def test_plain_list_response_without_enrichment_requests(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(body=[_task("a", due={"date": TOMORROW})])

        upcoming, overdue, error = fetch_todoist_dashboard_data("tok")

        assert (len(upcoming), overdue, error) == (1, [], None)
        assert upcoming[0].project_name is None
        # No project/section ids -> no enrichment lookups
        assert len(http.urls) == 1

    def test_unexpected_payload_means_no_tasks(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(body={"unexpected": True})

        assert fetch_todoist_dashboard_data("tok") == ([], [], None)

    def test_failed_enrichment_still_returns_tasks(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(body=[_task("a", project_id="p1", section_id="s1")])
        http.routes["/sections"] = requests.ConnectionError("sections down")
        http.routes["/projects"] = _response(status=500)

        upcoming, _, error = fetch_todoist_dashboard_data("tok")

        assert error is None
        assert upcoming[0].project_name is None
        assert upcoming[0].section_name is None

    @pytest.mark.parametrize("status", [401, 403, 410])
    def test_revoked_access_asks_to_reconnect(self, http: FakeRequests, status: int) -> None:
        http.routes["/tasks"] = _response(status=status)

        assert fetch_todoist_dashboard_data("tok") == (
            [],
            [],
            "Todoist access has expired. Please reconnect in Settings.",
        )

    def test_other_api_errors_report_the_status(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(status=503)

        assert fetch_todoist_dashboard_data("tok") == ([], [], "Todoist API error (503)")

    def test_connection_failure_is_reported(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = requests.ConnectionError("no route")

        tasks, overdue, error = fetch_todoist_dashboard_data("tok")

        assert (tasks, overdue) == ([], [])
        assert error == "Failed to connect to Todoist: no route"

    def test_malformed_task_is_reported_not_raised(self, http: FakeRequests) -> None:
        http.routes["/tasks"] = _response(body=[{"id": "no-content"}])

        tasks, _, error = fetch_todoist_dashboard_data("tok")

        assert tasks == []
        assert error is not None and error.startswith("Error fetching Todoist data:")
