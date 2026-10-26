"""Characterization tests for build_planner_dashboard.

Pins the full dashboard output for a fixed set of Todoist, Google Calendar,
Garmin and weather responses, plus each source's error handling. Only the
outer seams are faked: ``httpx.get``, the Garmin client factory, the weather
lookup and the database.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.services.planner_data import build_planner_dashboard
from src.utils.weather import WeatherForecast, WeatherPeriod

GARMIN_SEAM = "src.services.planner_data.create_client_from_tokens"
WEATHER_SEAM = "src.services.planner_data.get_weather_for_location"

TODAY = date.today()
D = [(TODAY + timedelta(days=i)).isoformat() for i in range(11)]
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()

PRIMARY_EVENTS_URL = "/calendars/primary/events"
WORK_EVENTS_URL = "/calendars/work%40example.com/events"
GONE_EVENTS_URL = "/calendars/gone%40example.com/events"


def _response(status: int = 200, body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = "error body"
    return response


class FakeHttp:
    """Answers GETs by the first registered URL suffix that matches."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> Any:
        self.urls.append(url)
        for suffix, answer in self.routes.items():
            if url.endswith(suffix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected GET {url}")


class FakeGarmin:
    """A Garmin client whose metric calls return canned data or raise."""

    def __init__(self, **answers: Any) -> None:
        self.answers = answers

    def _answer(self, name: str) -> Any:
        answer = self.answers.get(name)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get_stats(self, _day: str) -> Any:
        return self._answer("stats")

    def get_sleep_data(self, _day: str) -> Any:
        return self._answer("sleep")

    def get_heart_rates(self, _day: str) -> Any:
        return self._answer("hr")

    def get_training_readiness(self, _day: str) -> Any:
        return self._answer("readiness")

    def get_hrv_data(self, _day: str) -> Any:
        return self._answer("hrv")

    def get_activities_by_date(self, _start: str, _end: str) -> Any:
        return self._answer("activities")


class FakeDb:
    """The database surface the dashboard uses: cache, user lookup, pool."""

    def __init__(self, selected_ids: list[str] | None = None) -> None:
        self.cached: dict[str, Any] | None = None
        self.cache_calls: list[tuple[str, dict[str, Any], int]] = []
        self.user = MagicMock(google_calendar_selected_ids=selected_ids)
        self.user_error: Exception | None = None
        self._pool = MagicMock()

    def get_cached_dashboard(self, _user_id: str) -> dict[str, Any] | None:
        return self.cached

    def cache_dashboard(self, user_id: str, data: dict[str, Any], ttl_seconds: int) -> None:
        self.cache_calls.append((user_id, data, ttl_seconds))

    def get_user_by_id(self, _user_id: str) -> Any:
        if self.user_error:
            raise self.user_error
        return self.user


def _todoist_routes() -> dict[str, Any]:
    tasks = [
        {
            "id": "t-over",
            "content": "Pay bill",
            "due": {"date": YESTERDAY, "string": "yesterday", "is_recurring": False},
            "priority": 2,
            "project_id": "p1",
        },
        {
            "id": "t-low",
            "content": "Water plants",
            "due": {"date": D[0], "string": "every day", "is_recurring": True},
            "priority": 1,
            "labels": ["home"],
        },
        {
            "id": "t-high",
            "content": "Ship release",
            "description": "v2",
            "due": {"date": D[0]},
            "priority": 4,
            "project_id": "p1",
            "section_id": "s1",
            "url": "https://todoist.example/t-high",
        },
        {"id": "t-tomorrow", "content": "Call mom", "due": {"date": D[1]}, "priority": 3},
        {"id": "t-nodue", "content": "Someday", "priority": 2},
        {"id": "t-later", "content": "Far away", "due": {"date": D[10]}},
    ]
    return {
        "/tasks": _response(body={"results": tasks}),
        "/sections": _response(body={"results": [{"id": "s1", "name": "Work"}]}),
        "/projects": _response(body=[{"id": "p1", "name": "Inbox"}]),
    }


def _calendar_routes() -> dict[str, Any]:
    calendar_list = {
        "items": [
            {"id": "me@example.com", "summary": "Me", "primary": True},
            {"id": "work@example.com", "summary": "Work"},
            {"id": "gone@example.com", "summary": "Gone"},
        ]
    }
    primary_events = [
        {
            "id": "e-standup",
            "summary": "Standup",
            "start": {"dateTime": f"{D[0]}T09:00:00+02:00"},
            "end": {"dateTime": f"{D[0]}T09:15:00+02:00"},
            "location": "Office",
            "htmlLink": "https://calendar.example/e-standup",
            "attendees": [
                {"email": "a@example.com", "responseStatus": "accepted"},
                {"email": "me@example.com", "responseStatus": "needsAction", "self": True},
            ],
            "organizer": {"email": "boss@example.com", "displayName": "Boss"},
        },
        {"id": "e-trip", "summary": "Trip", "start": {"date": D[1]}, "end": {"date": D[4]}},
        {"id": "e-cancelled", "status": "cancelled", "start": {"date": D[0]}},
        {"summary": "Ghost without id", "start": {"date": D[0]}},
        {
            "id": "e-utc",
            "description": "Remote",
            "start": {"dateTime": f"{D[2]}T07:30:00Z"},
            "end": {"dateTime": f"{D[2]}T08:00:00Z"},
        },
    ]
    work_events = [
        {
            "id": "e-review",
            "summary": "Review",
            "start": {"dateTime": f"{D[0]}T08:00:00+02:00"},
            "end": {"dateTime": f"{D[0]}T08:30:00+02:00"},
        },
        {"id": "e-holiday", "summary": "Holiday", "start": {"date": D[5]}, "end": {"date": D[6]}},
    ]
    return {
        "/users/me/calendarList": _response(body=calendar_list),
        PRIMARY_EVENTS_URL: _response(body={"items": primary_events}),
        WORK_EVENTS_URL: _response(body={"items": work_events}),
        GONE_EVENTS_URL: _response(404),
    }


def _garmin_client() -> FakeGarmin:
    return FakeGarmin(
        stats={
            "totalSteps": 4200,
            "restingHeartRate": None,
            "bodyBatteryMostRecentValue": 63,
            "averageStressLevel": 28,
        },
        sleep={
            "dailySleepDTO": {
                "sleepTimeSeconds": 27000,
                "sleepScores": {"overall": {"qualifierKey": "GOOD"}},
            }
        },
        hr={"restingHeartRate": 52},
        readiness=[
            {"calendarDate": "2000-01-01", "score": 10, "level": "LOW"},
            {"calendarDate": D[0], "overallScore": 71, "overallReadiness": "HIGH"},
        ],
        hrv={"hrvSummary": {"status": "BALANCED"}},
        activities=[
            {
                "activityName": "Run",
                "startTimeLocal": f"{D[0]} 07:00:00",
                "distance": 10234.0,
                "duration": 3125.0,
            },
            {"startTimeLocal": None},
            {"activityName": "Ride", "startTimeLocal": f"{YESTERDAY} 17:00:00", "distance": 0},
            {"activityName": "Dropped", "startTimeLocal": f"{YESTERDAY} 06:00:00"},
        ],
    )


def _period(time: str, temperature: float, precipitation: float, symbol: str | None) -> Any:
    return WeatherPeriod(
        time=time,
        temperature=temperature,
        precipitation=precipitation,
        wind_speed=1.0,
        wind_direction=None,
        cloud_coverage=None,
        symbol_code=symbol,
        summary="",
    )


def _forecast() -> WeatherForecast:
    return WeatherForecast(
        location="Prague",
        latitude=50.0,
        longitude=14.4,
        periods=[
            _period(f"{D[0]}T06:00:00Z", 8.0, 0.0, "cloudy"),
            _period(f"{D[0]}T12:00:00Z", 14.5, 1.2, "rain"),
            _period(f"{D[0]}T18:00:00Z", 11.0, 0.3, None),
            _period(f"{D[1]}T12:00:00Z", 0.0, 0.0, "fog"),
            _period(f"{D[9]}T12:00:00Z", 20.0, 0.0, "clearsky_day"),
        ],
    )


@pytest.fixture(autouse=True)
def _no_weather_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weather stays off unless a test configures it (the local .env may set it)."""
    monkeypatch.setattr(Config, "WEATHER_LOCATION", "")


@pytest.fixture
def http() -> Generator[FakeHttp]:
    fake = FakeHttp()
    with patch("httpx.get", fake.get):
        yield fake


@pytest.fixture
def weather(monkeypatch: pytest.MonkeyPatch) -> Generator[MagicMock]:
    monkeypatch.setattr(Config, "WEATHER_LOCATION", "Prague")
    with patch(WEATHER_SEAM, return_value=_forecast()) as fake:
        yield fake


def _task(task_id: str, content: str, **fields: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "content": content,
        "description": "",
        "due_date": None,
        "due_string": None,
        "priority": 1,
        "project_name": None,
        "section_name": None,
        "labels": [],
        "is_recurring": False,
        "url": None,
    }
    return {**task, **fields}


def _event(event_id: str, summary: str, **fields: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": event_id,
        "summary": summary,
        "description": None,
        "start": None,
        "end": None,
        "start_date": None,
        "end_date": None,
        "location": None,
        "html_link": None,
        "is_all_day": False,
        "attendees": [],
        "organizer": None,
        "calendar_id": "primary",
        "calendar_summary": "Me",
    }
    return {**event, **fields}


def _day_name(index: int) -> str:
    if index == 0:
        return "Today"
    if index == 1:
        return "Tomorrow"
    return (TODAY + timedelta(days=index)).strftime("%A")


def _expected_dashboard() -> dict[str, Any]:
    standup = _event(
        "e-standup",
        "Standup",
        start=f"{D[0]}T09:00:00+02:00",
        end=f"{D[0]}T09:15:00+02:00",
        location="Office",
        html_link="https://calendar.example/e-standup",
        attendees=[
            {"email": "a@example.com", "response_status": "accepted", "self": False},
            {"email": "me@example.com", "response_status": "needsAction", "self": True},
        ],
        organizer={"email": "boss@example.com", "display_name": "Boss", "self": False},
    )
    review = _event(
        "e-review",
        "Review",
        start=f"{D[0]}T08:00:00+02:00",
        end=f"{D[0]}T08:30:00+02:00",
        calendar_id="work@example.com",
        calendar_summary="Work",
    )
    trip = _event("e-trip", "Trip", start_date=D[1], end_date=D[4], is_all_day=True)
    utc = _event(
        "e-utc",
        "(No title)",
        description="Remote",
        start=f"{D[2]}T07:30:00Z",
        end=f"{D[2]}T08:00:00Z",
    )
    holiday = _event(
        "e-holiday",
        "Holiday",
        start_date=D[5],
        end_date=D[6],
        is_all_day=True,
        calendar_id="work@example.com",
        calendar_summary="Work",
    )
    events_by_day: list[list[dict[str, Any]]] = [
        [review, standup],
        [trip],
        [trip, utc],
        [trip],
        [],
        [holiday],
        [],
    ]
    tasks_by_day: list[list[dict[str, Any]]] = [
        [
            _task(
                "t-high",
                "Ship release",
                description="v2",
                due_date=D[0],
                priority=4,
                project_name="Inbox",
                section_name="Work",
                url="https://todoist.example/t-high",
            ),
            _task("t-nodue", "Someday", priority=2),
            _task(
                "t-low",
                "Water plants",
                due_date=D[0],
                due_string="every day",
                labels=["home"],
                is_recurring=True,
            ),
        ],
        [_task("t-tomorrow", "Call mom", due_date=D[1], priority=3)],
        [],
        [],
        [],
        [],
        [],
    ]
    weather_by_day: list[dict[str, Any] | None] = [
        {
            "temperature_high": 14.5,
            "temperature_low": 8.0,
            "precipitation": 1.5,
            "symbol_code": "rain",
            "summary": "8.0-14.5°C, 1.5mm rain",
        },
        {
            "temperature_high": 0.0,
            "temperature_low": 0.0,
            "precipitation": 0.0,
            "symbol_code": "fog",
            "summary": "No data",
        },
        None,
        None,
        None,
        None,
        None,
    ]
    return {
        "days": [
            {
                "date": D[i],
                "day_name": _day_name(i),
                "events": events_by_day[i],
                "tasks": tasks_by_day[i],
                "weather": weather_by_day[i],
            }
            for i in range(7)
        ],
        "overdue_tasks": [
            _task(
                "t-over",
                "Pay bill",
                due_date=YESTERDAY,
                due_string="yesterday",
                priority=2,
                project_name="Inbox",
            )
        ],
        "todoist_connected": True,
        "calendar_connected": True,
        "garmin_connected": True,
        "weather_connected": True,
        "todoist_error": None,
        "calendar_error": "Some calendars failed to load: Gone",
        "garmin_error": None,
        "weather_error": None,
        "weather_location": "Prague",
        "health_summary": {
            "training_readiness": {"score": 71, "level": "HIGH"},
            "training_status": None,
            "sleep": {"duration_hours": 7.5, "quality": "GOOD"},
            "stress_avg": 28,
            "resting_hr": 52,
            "hrv_status": "BALANCED",
            "body_battery": 63,
            "steps_today": 4200,
            "recent_activities": [
                {"name": "Run", "date": D[0], "distance_km": 10.2, "duration_min": 52.0},
                {"name": "Activity", "date": "", "distance_km": None, "duration_min": None},
                {"name": "Ride", "date": YESTERDAY, "distance_km": None, "duration_min": None},
            ],
        },
    }


def _build(db: FakeDb | None = None, **tokens: Any) -> Any:
    return build_planner_dashboard(
        todoist_token=tokens.get("todoist"),
        calendar_token=tokens.get("calendar"),
        garmin_token=tokens.get("garmin"),
        user_id="user-1" if db else None,
        force_refresh=tokens.get("force_refresh", False),
        db=db,
    )


class TestFullDashboard:
    def test_all_sources_combine_into_the_pinned_dashboard(
        self, http: FakeHttp, weather: MagicMock
    ) -> None:
        http.routes = {**_todoist_routes(), **_calendar_routes()}
        db = FakeDb(selected_ids=["primary", "work@example.com", "gone@example.com"])

        with patch(GARMIN_SEAM, return_value=_garmin_client()):
            dashboard = _build(db, todoist="td", calendar="gc", garmin="gm")

        output = asdict(dashboard)
        server_time = output.pop("server_time")
        assert datetime.fromisoformat(server_time).date() == TODAY
        assert output == _expected_dashboard()

        weather.assert_called_once_with("Prague", db=db, force_refresh=False)
        assert db.cache_calls == [("user-1", asdict(dashboard), Config.DASHBOARD_CACHE_TTL_SECONDS)]
        assert db._pool.close_thread_connection.call_count == 2

    def test_a_cached_dashboard_round_trips_without_fetching(
        self, http: FakeHttp, weather: MagicMock
    ) -> None:
        http.routes = {**_todoist_routes(), **_calendar_routes()}
        db = FakeDb(selected_ids=["primary", "work@example.com", "gone@example.com"])
        with patch(GARMIN_SEAM, return_value=_garmin_client()):
            fresh = _build(db, todoist="td", calendar="gc", garmin="gm")
        db.cached = asdict(fresh)
        http.urls.clear()

        cached = _build(db, todoist="td", calendar="gc", garmin="gm")

        assert cached == fresh
        assert http.urls == []
        assert len(db.cache_calls) == 1

    def test_force_refresh_bypasses_the_cache(self, http: FakeHttp, weather: MagicMock) -> None:
        http.routes = _todoist_routes()
        db = FakeDb()
        db.cached = {"days": []}

        dashboard = _build(db, todoist="td", force_refresh=True)

        assert len(dashboard.days) == 7
        weather.assert_called_once_with("Prague", db=db, force_refresh=True)

    def test_nothing_connected_gives_seven_empty_days(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "WEATHER_LOCATION", "")

        output = asdict(_build())

        assert [d["date"] for d in output["days"]] == D[:7]
        assert all(not d["events"] and not d["tasks"] for d in output["days"])
        assert not output["todoist_connected"]
        assert not output["weather_connected"]
        assert output["health_summary"] is None
        assert output["weather_error"] is None


class TestCalendarSection:
    def test_without_a_db_only_the_primary_calendar_is_fetched(self, http: FakeHttp) -> None:
        http.routes = _calendar_routes()

        dashboard = _build(calendar="gc")

        event_urls = [u for u in http.urls if u.endswith("/events")]
        assert [u.rsplit("/calendars", 1)[1] for u in event_urls] == ["/primary/events"]
        assert dashboard.calendar_error is None

    def test_a_failed_user_lookup_falls_back_to_primary(self, http: FakeHttp) -> None:
        http.routes = _calendar_routes()
        db = FakeDb(selected_ids=["work@example.com"])
        db.user_error = RuntimeError("db down")

        _build(db, calendar="gc")

        event_urls = [u for u in http.urls if u.endswith("/events")]
        assert len(event_urls) == 1
        assert event_urls[0].endswith(PRIMARY_EVENTS_URL)

    def test_duplicate_event_ids_are_kept_once(self, http: FakeHttp) -> None:
        event = {"id": "e-1", "summary": "Once", "start": {"date": D[0]}, "end": {"date": D[1]}}
        http.routes = {
            "/users/me/calendarList": _response(500),
            PRIMARY_EVENTS_URL: _response(body={"items": [event, dict(event)]}),
        }

        dashboard = _build(calendar="gc")

        assert [e.summary for e in dashboard.days[0].events] == ["Once"]
        assert dashboard.days[0].events[0].calendar_summary == "primary"

    def test_all_calendars_expired_asks_to_reconnect(self, http: FakeHttp) -> None:
        http.routes = {"/users/me/calendarList": _response(401), PRIMARY_EVENTS_URL: _response(401)}

        dashboard = _build(calendar="gc")

        assert dashboard.calendar_error == (
            "Google Calendar access has expired. Please reconnect in Settings."
        )

    @pytest.mark.parametrize("status", [403, 404, 500])
    def test_all_calendars_failing_otherwise_reports_a_connection_problem(
        self, http: FakeHttp, status: int
    ) -> None:
        http.routes = {
            "/users/me/calendarList": RuntimeError("names down"),
            PRIMARY_EVENTS_URL: _response(status),
        }

        dashboard = _build(calendar="gc")

        assert dashboard.calendar_error == (
            "Failed to fetch any calendars. Please check your connection."
        )

    def test_more_than_three_failures_are_summarized(self, http: FakeHttp) -> None:
        ids = ["primary", "c1", "c2", "c3", "c4"]
        http.routes = {
            "/users/me/calendarList": _response(body={"items": []}),
            PRIMARY_EVENTS_URL: _response(body={"items": []}),
            "/calendars/c1/events": _response(404),
            "/calendars/c2/events": _response(404),
            "/calendars/c3/events": _response(404),
            "/calendars/c4/events": _response(404),
        }

        dashboard = _build(FakeDb(selected_ids=ids), calendar="gc")

        error = dashboard.calendar_error or ""
        assert error.startswith("Some calendars failed to load: ")
        assert error.endswith(", and 1 more")
        assert len(error.split(": ", 1)[1].split(", and")[0].split(", ")) == 3


class TestGarminSection:
    def test_a_failing_metric_leaves_only_that_metric_empty(self, http: FakeHttp) -> None:
        client = _garmin_client()
        client.answers["sleep"] = RuntimeError("sleep down")
        client.answers["readiness"] = {"score": 40, "level": "LOW"}
        client.answers["hrv"] = {"status": "UNBALANCED"}

        with patch(GARMIN_SEAM, return_value=client):
            summary = _build(garmin="gm").health_summary

        assert summary is not None
        assert summary.sleep is None
        assert summary.steps_today == 4200
        assert summary.training_readiness == {"score": 40, "level": "LOW"}
        assert summary.hrv_status == "UNBALANCED"

    @pytest.mark.parametrize("message", ["Token expired", "401 Unauthorized"])
    def test_an_expired_session_asks_to_reconnect(self, http: FakeHttp, message: str) -> None:
        with patch(GARMIN_SEAM, side_effect=RuntimeError(message)):
            dashboard = _build(garmin="gm")

        assert dashboard.health_summary is None
        assert dashboard.garmin_error == "Garmin session expired. Please reconnect in Settings."

    def test_other_client_failures_are_reported(self, http: FakeHttp) -> None:
        with patch(GARMIN_SEAM, side_effect=RuntimeError("boom")):
            dashboard = _build(garmin="gm")

        assert dashboard.garmin_error == "Garmin error: boom"


class TestWeatherSection:
    def test_a_lookup_failure_is_reported(
        self, http: FakeHttp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "WEATHER_LOCATION", "Prague")
        with patch(WEATHER_SEAM, side_effect=RuntimeError("met down")):
            dashboard = _build()

        assert dashboard.weather_error == "Weather error: met down"
        assert dashboard.weather_location is None

    def test_no_forecast_is_reported_as_unavailable(
        self, http: FakeHttp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "WEATHER_LOCATION", "Prague")
        with patch(WEATHER_SEAM, return_value=None):
            dashboard = _build()

        assert dashboard.weather_error == "Unable to fetch weather data"
        assert all(day.weather is None for day in dashboard.days)
