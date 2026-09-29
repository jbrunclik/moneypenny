"""Tests for the eval harness's fake integration backends (evals/fakes.py).

The fakes replace only the HTTP/client seams, so these tests drive the REAL
tools through them.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from evals.fakes import FakeTodoist, describe_actions, fake_integrations

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

TODOIST = {
    "projects": [{"id": "p1", "name": "Work"}, {"id": "p2", "name": "Personal"}],
    "sections": [{"id": "s1", "project_id": "p2", "name": "Errands"}],
    "tasks": [
        {
            "id": "t1",
            "content": "Send invoice",
            "project_id": "p1",
            "due": {"date": TODAY},
            "priority": 4,
        },
        {"id": "t2", "content": "Buy milk", "project_id": "p2", "section_id": "s1"},
        {"id": "t3", "content": "Call dentist", "project_id": "p2", "due": {"date": TOMORROW}},
    ],
}


class TestFakeTodoistFilters:
    def test_filters_like_todoist(self) -> None:
        fake = FakeTodoist(TODOIST)
        assert [t["id"] for t in fake._filter("today")] == ["t1"]
        assert [t["id"] for t in fake._filter("p1")] == ["t1"]
        assert [t["id"] for t in fake._filter("#Personal")] == ["t2", "t3"]
        assert [t["id"] for t in fake._filter("no date")] == ["t2"]
        assert [t["id"] for t in fake._filter("today | tomorrow")] == ["t1", "t3"]
        assert [t["id"] for t in fake._filter("search: dentist")] == ["t3"]

    def test_rejects_natural_language_like_the_real_api(self) -> None:
        with pytest.raises(Exception, match="search query is incorrect"):
            FakeTodoist(TODOIST)._filter("tasks due this week")


class TestThroughTheRealTools:
    def test_todoist_tool_lists_and_adds(self) -> None:
        from src.agent.tools.todoist import todoist

        with fake_integrations({"todoist": TODOIST}) as fakes:
            listed = json.loads(todoist.invoke({"action": "list_tasks", "filter_string": "today"}))
            added = json.loads(
                todoist.invoke(
                    {
                        "action": "add_task",
                        "content": "Call plumber",
                        "project_id": "p2",
                        "section_id": "s1",
                    }
                )
            )

        assert [t["content"] for t in listed["tasks"]] == ["Send invoice"]
        assert "error" not in added
        assert "Call plumber" in describe_actions(fakes)

    def test_bad_filter_reaches_the_tool_guidance(self) -> None:
        from src.agent.tools.todoist import todoist

        with fake_integrations({"todoist": TODOIST}):
            parsed = json.loads(
                todoist.invoke({"action": "list_tasks", "filter_string": "stuff for this week"})
            )
        assert parsed["failed_filter"] == "stuff for this week"

    def test_garmin_connected_serves_fixture(self) -> None:
        from src.agent.tools.garmin import garmin_connect

        spec = {"garmin": {"data": {"get_hrv_data": {"lastNightAvg": 58}}}}
        with fake_integrations(spec):
            parsed = json.loads(garmin_connect.invoke({"action": "get_hrv_data"}))
        assert "58" in json.dumps(parsed)

    @pytest.mark.parametrize(
        ("state", "error"),
        [("disconnected", "Garmin disconnected"), ("not_connected", "Garmin not connected")],
    )
    def test_garmin_connection_states(self, state: str, error: str) -> None:
        from src.agent.tools.garmin import garmin_connect

        with fake_integrations({"garmin": {"state": state}}):
            parsed = json.loads(garmin_connect.invoke({"action": "get_readiness_snapshot"}))
        assert parsed["error"] == error


def test_describe_actions_handles_read_only_fakes() -> None:
    """A Garmin fake must not answer `actions` with an API-method stub."""
    spec = {"garmin": {"data": {}}, "todoist": TODOIST}
    with fake_integrations(spec) as fakes:
        assert describe_actions(fakes) == "none"
