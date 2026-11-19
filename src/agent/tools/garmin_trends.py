"""garmin_connect get_trend: a metric over a date range, one compact row per day.

Each metric is one call to the library's range endpoint (one Garmin round trip
for up to TREND_MAX_DAYS days), cut to the few numbers a coach compares day
to day. Shapes and units are those the endpoints returned when probed on Nov
19 2026: durations in seconds, distance in metres, weight in grams.
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from src.utils.clock import local_today

TREND_DEFAULT_DAYS = 7
TREND_MAX_DAYS = 31

# A Garmin JSON object as the library returns it
GarminJson = dict[str, Any]
TrendRow = dict[str, str | int | float | None]


def _num(value: object, scale: float = 1, digits: int = 1) -> float | None:
    return round(float(value) / scale, digits) if isinstance(value, int | float) else None


def _minutes(value: object) -> int | None:
    return round(value / 60) if isinstance(value, int | float) else None


def _sleep(item: GarminJson) -> TrendRow:
    v = item.get("values") or {}
    return {
        "date": item.get("calendarDate"),
        "sleep_h": _num(v.get("totalSleepTimeInSeconds"), 3600),
        "score": v.get("sleepScore"),
        "quality": v.get("sleepScoreQuality"),
        "deep_min": _minutes(v.get("deepTime")),
        "rem_min": _minutes(v.get("remTime")),
        "awake_min": _minutes(v.get("awakeTime")),
        "avg_hrv": v.get("avgOvernightHrv"),
        "resting_hr": v.get("restingHeartRate"),
    }


def _hrv(item: GarminJson) -> TrendRow:
    return {
        "date": item.get("calendarDate"),
        "last_night_avg": item.get("lastNightAvg"),
        "weekly_avg": item.get("weeklyAvg"),
        "status": item.get("status"),
    }


def _readiness(item: GarminJson) -> TrendRow:
    return {
        "date": item.get("calendarDate"),
        "score": item.get("score"),
        "level": item.get("level"),
        "sleep_score": item.get("sleepScore"),
        "recovery_time_h": _num(item.get("recoveryTime"), 60),
        "acute_load": item.get("acuteLoad"),
    }


def _stress(item: GarminJson) -> TrendRow:
    v = item.get("values") or {}
    return {
        "date": item.get("calendarDate"),
        "avg_stress": v.get("overallStressLevel"),
        "high_stress_min": _minutes(v.get("highStressDuration")),
        "rest_min": _minutes(v.get("restStressDuration")),
    }


def _steps(item: GarminJson) -> TrendRow:
    return {
        "date": item.get("calendarDate"),
        "steps": item.get("totalSteps"),
        "distance_km": _num(item.get("totalDistance"), 1000),
        "goal": item.get("stepGoal"),
    }


def _body_battery(item: GarminJson) -> TrendRow:
    v = item.get("values") or {}
    return {
        "date": item.get("calendarDate"),
        "high": v.get("highBodyBattery"),
        "low": v.get("lowBodyBattery"),
    }


def _resting_hr(item: GarminJson) -> TrendRow:
    return {"date": item.get("calendarDate"), "bpm": item.get("value")}


def _weight(item: GarminJson) -> TrendRow:
    latest = item.get("latestWeight") or {}
    return {
        "date": item.get("summaryDate") or latest.get("calendarDate"),
        "kg": _num(latest.get("weight"), 1000),
        "body_fat_pct": latest.get("bodyFat"),
    }


def _items(payload: object, key: str | None) -> list[GarminJson]:
    """The per-day entries: the list itself, or the list under `key`."""
    found = payload.get(key) if key and isinstance(payload, dict) else payload
    return (
        [item for item in found or [] if isinstance(item, dict)] if isinstance(found, list) else []
    )


def _morning_readiness(items: list[GarminJson]) -> list[GarminJson]:
    """One entry per day: the after-wake-up value (else the day's earliest).

    The range returns several per day - the morning reset, then updates after
    exercise and during the day; the morning one is what a plan is set from.
    """
    by_day: dict[str, list[GarminJson]] = {}
    for item in sorted(items, key=lambda i: str(i.get("timestampLocal") or "")):
        by_day.setdefault(str(item.get("calendarDate") or ""), []).append(item)
    return [
        next((e for e in entries if e.get("inputContext") == "AFTER_WAKEUP_RESET"), entries[0])
        for entries in by_day.values()
    ]


# metric -> (library method, key holding the per-day list, row builder)
TREND_METRICS: dict[str, tuple[str, str | None, Callable[[GarminJson], TrendRow]]] = {
    "sleep": ("get_sleep_daily", None, _sleep),
    "hrv": ("get_hrv_data_range", "hrvSummaries", _hrv),
    "resting_hr": ("get_rhr_daily", None, _resting_hr),
    "training_readiness": ("get_training_readiness_range", None, _readiness),
    "body_battery": ("get_daily_body_battery_stats", None, _body_battery),
    "stress": ("get_daily_stress_stats", None, _stress),
    "steps": ("get_daily_steps", None, _steps),
    "weight": ("get_weigh_ins", "dailyWeightSummaries", _weight),
}


def trend_range(start_date: str | None, end_date: str | None) -> tuple[date, date] | str:
    """The inclusive date range (default: the last TREND_DEFAULT_DAYS), or an error."""
    try:
        end = date.fromisoformat(end_date) if end_date else local_today()
        start = (
            date.fromisoformat(start_date)
            if start_date
            else end - timedelta(days=TREND_DEFAULT_DAYS - 1)
        )
    except ValueError:
        return "start_date and end_date must be dates as YYYY-MM-DD"
    if start > end:
        return f"start_date ({start}) is after end_date ({end})"
    if (end - start).days + 1 > TREND_MAX_DAYS:
        return f"get_trend covers at most {TREND_MAX_DAYS} days per call - narrow the range"
    return start, end


def trend_rows(metric: str, payload: object) -> list[TrendRow]:
    """The payload of `metric`'s range call as one row per day, oldest first."""
    _, key, build = TREND_METRICS[metric]
    items = _items(payload, key)
    if metric == "training_readiness":
        items = _morning_readiness(items)
    rows = [build(item) for item in items]
    return sorted(rows, key=lambda row: str(row.get("date") or ""))
