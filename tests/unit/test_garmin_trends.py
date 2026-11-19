"""get_trend: one Garmin range call per metric, one compact row per day.

The payload shapes are those of the real range endpoints (probed Nov 19 2026)
with made-up numbers.
"""

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.garmin import garmin_connect

_SLEEP = [
    {
        "calendarDate": "2026-11-18",
        "values": {
            "totalSleepTimeInSeconds": 26100,
            "sleepScore": 81,
            "sleepScoreQuality": "GOOD",
            "deepTime": 5400,
            "remTime": 6000,
            "awakeTime": 900,
            "avgOvernightHrv": 48.0,
            "restingHeartRate": 52,
            "localSleepStartTimeInMillis": 1,
        },
    }
]
_HRV = {
    "hrvSummaries": [
        {
            "calendarDate": "2026-11-18",
            "lastNightAvg": 47,
            "weeklyAvg": 50,
            "status": "BALANCED",
            "baseline": {"balancedLow": 44},
        }
    ]
}
_READINESS = [
    {
        "calendarDate": "2026-11-18",
        "timestampLocal": "2026-11-18T09:02:00.0",
        "inputContext": "UPDATE_REALTIME_VARIABLES",
        "score": 40,
        "level": "LOW",
    },
    {
        "calendarDate": "2026-11-18",
        "timestampLocal": "2026-11-18T07:00:00.0",
        "inputContext": "AFTER_WAKEUP_RESET",
        "score": 71,
        "level": "MODERATE",
        "sleepScore": 81,
        "recoveryTime": 600,
        "acuteLoad": 420,
    },
]
_STRESS = [
    {
        "calendarDate": "2026-11-18",
        "values": {
            "overallStressLevel": 31,
            "highStressDuration": 1800,
            "restStressDuration": 30000,
        },
    }
]
_WEIGHT = {
    "dailyWeightSummaries": [
        {"summaryDate": "2026-11-18", "latestWeight": {"weight": 78450.0, "bodyFat": 18.2}}
    ]
}


def _client(**methods: Any) -> MagicMock:
    client = MagicMock()
    for name, value in methods.items():
        getattr(client, name).return_value = value
    return client


def _trend(client: MagicMock, **args: Any) -> dict[str, Any]:
    with (
        patch("src.agent.tools.garmin.get_garmin_client", return_value=client),
        patch("src.agent.tools.garmin._persist_refreshed_tokens"),
        patch("src.agent.tools.garmin_trends.local_today", return_value=date(2026, 11, 19)),
    ):
        return json.loads(garmin_connect.invoke({"action": "get_trend", **args}))


def test_sleep_rows() -> None:
    client = _client(get_sleep_daily=_SLEEP)
    result = _trend(client, metric="sleep")
    client.get_sleep_daily.assert_called_once_with("2026-11-13", "2026-11-19")
    assert result["days"] == [
        {
            "date": "2026-11-18",
            "sleep_h": 7.2,
            "score": 81,
            "quality": "GOOD",
            "deep_min": 90,
            "rem_min": 100,
            "awake_min": 15,
            "avg_hrv": 48.0,
            "resting_hr": 52,
        }
    ]


def test_hrv_rows() -> None:
    result = _trend(_client(get_hrv_data_range=_HRV), metric="hrv")
    assert result["days"] == [
        {"date": "2026-11-18", "last_night_avg": 47, "weekly_avg": 50, "status": "BALANCED"}
    ]


def test_readiness_keeps_the_morning_value() -> None:
    result = _trend(_client(get_training_readiness_range=_READINESS), metric="training_readiness")
    assert result["days"] == [
        {
            "date": "2026-11-18",
            "score": 71,
            "level": "MODERATE",
            "sleep_score": 81,
            "recovery_time_h": 10.0,
            "acute_load": 420,
        }
    ]


def test_stress_steps_battery_and_rhr_rows() -> None:
    assert _trend(_client(get_daily_stress_stats=_STRESS), metric="stress")["days"] == [
        {"date": "2026-11-18", "avg_stress": 31, "high_stress_min": 30, "rest_min": 500}
    ]
    steps = [
        {"calendarDate": "2026-11-18", "totalSteps": 9100, "totalDistance": 7300, "stepGoal": 8000}
    ]
    assert _trend(_client(get_daily_steps=steps), metric="steps")["days"] == [
        {"date": "2026-11-18", "steps": 9100, "distance_km": 7.3, "goal": 8000}
    ]
    battery = [
        {"calendarDate": "2026-11-18", "values": {"highBodyBattery": 88, "lowBodyBattery": 12}}
    ]
    assert _trend(_client(get_daily_body_battery_stats=battery), metric="body_battery")["days"] == [
        {"date": "2026-11-18", "high": 88, "low": 12}
    ]
    rhr = [{"calendarDate": "2026-11-18", "value": 52.0}]
    assert _trend(_client(get_rhr_daily=rhr), metric="resting_hr")["days"] == [
        {"date": "2026-11-18", "bpm": 52.0}
    ]


def test_weight_in_kilograms() -> None:
    result = _trend(_client(get_weigh_ins=_WEIGHT), metric="weight")
    assert result["days"] == [{"date": "2026-11-18", "kg": 78.5, "body_fat_pct": 18.2}]


def test_explicit_range() -> None:
    client = _client(get_rhr_daily=[])
    result = _trend(client, metric="resting_hr", start_date="2026-11-01", end_date="2026-11-10")
    client.get_rhr_daily.assert_called_once_with("2026-11-01", "2026-11-10")
    assert (result["start"], result["end"], result["days"]) == ("2026-11-01", "2026-11-10", [])


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        ({"metric": "mood"}, "metric"),
        ({"metric": "sleep", "start_date": "2026-10-01", "end_date": "2026-11-19"}, "31"),
        ({"metric": "sleep", "start_date": "2026-11-19", "end_date": "2026-11-01"}, "after"),
        ({"metric": "sleep", "start_date": "last week"}, "YYYY-MM-DD"),
    ],
)
def test_bad_arguments(args: dict[str, Any], needle: str) -> None:
    client = _client()
    result = _trend(client, **args)
    assert needle in result["error"]
    assert not client.method_calls


def test_activities_take_a_date_range() -> None:
    client = _client(get_activities_by_date=[{"activityId": 1, "startTimeLocal": "2026-09-03"}])
    with (
        patch("src.agent.tools.garmin.get_garmin_client", return_value=client),
        patch("src.agent.tools.garmin._persist_refreshed_tokens"),
    ):
        result = json.loads(
            garmin_connect.invoke(
                {"action": "get_activities", "start_date": "2026-09-01", "end_date": "2026-09-30"}
            )
        )
    client.get_activities_by_date.assert_called_once_with("2026-09-01", "2026-09-30", None)
    assert result["count"] == 1


class TestToolSchema:
    def test_every_param_has_a_concrete_type(self) -> None:
        for name, schema in garmin_connect.args.items():
            assert "type" in schema or "anyOf" in schema, name
