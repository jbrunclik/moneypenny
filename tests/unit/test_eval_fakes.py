"""Tests for the eval harness's fake integration backends (evals/fakes.py).

The fakes replace only the HTTP/client seams, so these tests drive the REAL
tools through them.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from evals.fakes import FakeTodoist, describe_recorded, fake_integrations, recorded_actions
from src.utils.clock import local_today


def _todoist() -> dict:
    """Fixture dated from the moment the test runs, not from import time
    (a suite that ran across midnight saw yesterday's "today")."""
    today = local_today()
    return {
        "projects": [{"id": "p1", "name": "Work"}, {"id": "p2", "name": "Personal"}],
        "sections": [{"id": "s1", "project_id": "p2", "name": "Errands"}],
        "tasks": [
            {
                "id": "t1",
                "content": "Send invoice",
                "project_id": "p1",
                "due": {"date": today.isoformat()},
                "priority": 4,
            },
            {"id": "t2", "content": "Buy milk", "project_id": "p2", "section_id": "s1"},
            {
                "id": "t3",
                "content": "Call dentist",
                "project_id": "p2",
                "due": {"date": (today + timedelta(days=1)).isoformat()},
            },
        ],
    }


class TestFakeTodoistFilters:
    def test_filters_like_todoist(self) -> None:
        fake = FakeTodoist(_todoist())
        assert [t["id"] for t in fake._filter("today")] == ["t1"]
        assert [t["id"] for t in fake._filter("p1")] == ["t1"]
        assert [t["id"] for t in fake._filter("#Personal")] == ["t2", "t3"]
        assert [t["id"] for t in fake._filter("no date")] == ["t2"]
        assert [t["id"] for t in fake._filter("today | tomorrow")] == ["t1", "t3"]
        assert [t["id"] for t in fake._filter("search: dentist")] == ["t3"]

    def test_rejects_natural_language_like_the_real_api(self) -> None:
        with pytest.raises(Exception, match="search query is incorrect"):
            FakeTodoist(_todoist())._filter("tasks due this week")


class TestThroughTheRealTools:
    def test_todoist_tool_lists_and_adds(self) -> None:
        from src.agent.tools.todoist import todoist

        with fake_integrations({"todoist": _todoist()}) as fakes:
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
        assert "Call plumber" in describe_recorded(recorded_actions(fakes))

    def test_bad_filter_reaches_the_tool_guidance(self) -> None:
        from src.agent.tools.todoist import todoist

        with fake_integrations({"todoist": _todoist()}):
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
    spec = {"garmin": {"data": {}}, "todoist": _todoist()}
    with fake_integrations(spec) as fakes:
        assert describe_recorded(recorded_actions(fakes)) == "none"


def _workout() -> dict:
    """A one-block raw Garmin strength workout (what get_workout_by_id returns)."""

    def step(step_id: int, order: int, kind: str, end: str, value: float, **extra: object) -> dict:
        return {
            "type": "ExecutableStepDTO",
            "stepId": step_id,
            "stepOrder": order,
            "stepType": {"stepTypeKey": kind},
            "endCondition": {"conditionTypeKey": end},
            "endConditionValue": value,
            **extra,
        }

    bench = step(11, 2, "interval", "reps", 8.0, category="BENCH_PRESS", exerciseName="BENCH_PRESS")
    bench["weightValue"] = 60.0
    bench["weightUnit"] = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
    block = {
        "type": "RepeatGroupDTO",
        "stepId": 10,
        "stepOrder": 1,
        "stepType": {"stepTypeKey": "repeat"},
        "numberOfIterations": 3,
        "endConditionValue": 3.0,
        "workoutSteps": [bench, step(12, 3, "rest", "time", 90.0)],
    }
    return {
        "workoutId": 501,
        "workoutName": "Push A",
        "sportType": {"sportTypeKey": "strength_training"},
        "workoutSegments": [{"segmentOrder": 1, "workoutSteps": [block]}],
    }


def test_garmin_workouts_list_and_get_through_the_real_tool() -> None:
    from src.agent.tools.garmin_workout import garmin_workout

    spec = {"garmin": {"state": "connected", "workouts": [_workout()]}}
    with fake_integrations(spec):
        listed = json.loads(garmin_workout.invoke({"action": "list"}))
        got = json.loads(garmin_workout.invoke({"action": "get", "workout_id": "501"}))
    assert listed["workouts"] == [
        {"workout_id": 501, "name": "Push A", "sport": "strength_training"}
    ]
    assert got["workout"]["blocks"][0]["steps"][0]["weight_kg"] == 60.0


def test_garmin_workout_update_is_saved_and_recorded() -> None:
    from src.agent.tools.garmin_workout import garmin_workout

    spec = {"garmin": {"state": "connected", "workouts": [_workout()]}}
    with fake_integrations(spec) as fakes:
        edits = json.dumps([{"step_id": 11, "weight_kg": 62.5}])
        result = json.loads(
            garmin_workout.invoke({"action": "update", "workout_id": "501", "edits": edits})
        )
        again = json.loads(garmin_workout.invoke({"action": "get", "workout_id": "501"}))
    # The refreshed view is the saved workout
    assert result["workout"]["blocks"][0]["steps"][0]["weight_kg"] == 62.5
    assert again["workout"]["blocks"][0]["steps"][0]["weight_kg"] == 62.5
    [action] = fakes["garmin"].actions
    assert action.startswith("updated workout 'Push A'")
    assert "60" in action and "62.5" in action


def test_garmin_unknown_workout_fails_loudly() -> None:
    from src.agent.tools.garmin_workout import garmin_workout

    with fake_integrations({"garmin": {"state": "connected", "workouts": []}}):
        result = garmin_workout.invoke({"action": "get", "workout_id": "999"})
    assert "error" in json.loads(result)


def test_garmin_rest_change_is_recorded() -> None:
    from src.agent.tools.garmin_workout import garmin_workout

    spec = {"garmin": {"state": "connected", "workouts": [_workout()]}}
    with fake_integrations(spec) as fakes:
        edits = json.dumps([{"step_id": 12, "rest_s": 150}])
        garmin_workout.invoke({"action": "update", "workout_id": "501", "edits": edits})
    [action] = fakes["garmin"].actions
    assert "rest" in action and "90" in action and "150" in action


def test_garmin_save_renumbers_steps_like_garmin() -> None:
    """Real Garmin reassigns every stepId on save: an update that reuses the
    ids of an earlier get must not quietly succeed against the fake."""
    from src.agent.tools.garmin_workout import garmin_workout

    spec = {"garmin": {"state": "connected", "workouts": [_workout()]}}
    with fake_integrations(spec) as fakes:
        first = json.dumps([{"step_id": 11, "weight_kg": 62.5}])
        garmin_workout.invoke({"action": "update", "workout_id": "501", "edits": first})
        got = json.loads(garmin_workout.invoke({"action": "get", "workout_id": "501"}))
        stale = json.dumps([{"step_id": 11, "weight_kg": 65}])
        result = garmin_workout.invoke({"action": "update", "workout_id": "501", "edits": stale})
    new_id = got["workout"]["blocks"][0]["steps"][0]["step_id"]
    assert new_id != 11
    assert "65" not in fakes["garmin"].actions[-1] or "no change" in fakes["garmin"].actions[-1]
    assert "62.5" in json.dumps(json.loads(result).get("workout", {}))


class TestFakeTodoistCompleted:
    def test_returns_checked_tasks_completed_in_range(self) -> None:
        fixture = _todoist()
        fixture["tasks"][1]["checked"] = True
        fixture["tasks"][1]["completed_at"] = "2026-11-18T09:00:00Z"
        fixture["tasks"][2]["checked"] = True
        fixture["tasks"][2]["completed_at"] = "2026-10-01T09:00:00Z"
        fake = FakeTodoist(fixture)
        done = fake.api_request(
            "GET",
            "/tasks/completed/by_completion_date",
            "tok",
            params={"since": "2026-11-12T23:00:00Z", "until": "2026-11-19T23:00:00Z"},
        )
        assert [t["content"] for t in done] == ["Buy milk"]


def test_the_cases_integrations_decide_which_tools_are_bound() -> None:
    """Per-user tool sets: the eval user holds no tokens, so the case's
    integrations block says what is connected (disconnected stays bound)."""
    from src.agent.tools import integration_status

    spec = {"todoist": {}, "garmin": {"state": "disconnected"}}
    with fake_integrations(spec):
        assert integration_status.unconnected_integrations("any") == {
            "google_calendar",
            "rouvy",
        }
    with fake_integrations({"calendar": {"state": "not_connected"}}):
        assert "google_calendar" in integration_status.unconnected_integrations("any")
