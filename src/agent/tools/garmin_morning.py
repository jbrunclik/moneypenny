"""The Daily Briefing's compact view of the Garmin readiness snapshot.

The full snapshot (training readiness, sleep with its per-minute levels, HRV
readings, daily stats, training status and recent activities with their
splits) ran to ~39k characters, and every later round of the briefing re-sent
it: on Nov 11 2026 the briefing stopped at its cost limit. The morning needs a
dozen numbers, the same ones the planner dashboard reads
(src/services/planner/garmin.py). Sports coaching keeps calling
get_readiness_snapshot, which is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping

# Activities a morning view lists (newest first, as Garmin returns them)
MORNING_ACTIVITIES = 3
NOTE = (
    "Compact morning view. For every field (sleep levels, HRV readings, splits, "
    "training load details) call get_readiness_snapshot."
)


def _at(data: object, *path: str) -> object:
    """The value at `path` in nested dicts, or None."""
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _minutes(seconds: object) -> int | None:
    value = _num(seconds)
    return round(value / 60) if value is not None else None


def _present(fields: Mapping[str, object]) -> dict[str, object]:
    return {k: v for k, v in fields.items() if v is not None}


def _find(data: object, key: str) -> object:
    """The first value stored under `key` anywhere in nested dicts and lists."""
    if isinstance(data, Mapping):
        if key in data:
            return data[key]
        values: list[object] = list(data.values())
    elif isinstance(data, list):
        values = list(data)
    else:
        return None
    for value in values:
        found = _find(value, key)
        if found is not None:
            return found
    return None


def _wake(stats: object) -> dict[str, object]:
    return _present(
        {
            "body_battery_at_wake": _at(stats, "bodyBatteryAtWakeTime"),
            "resting_hr": _at(stats, "restingHeartRate"),
            "resting_hr_7d_avg": _at(stats, "lastSevenDaysAvgRestingHeartRate"),
        }
    )


def _sleep(sleep: object) -> dict[str, object]:
    daily = _at(sleep, "dailySleepDTO")
    seconds = _num(_at(daily, "sleepTimeSeconds"))
    return _present(
        {
            "duration_h": round(seconds / 3600, 1) if seconds else None,
            "score": _at(daily, "sleepScores", "overall", "value"),
            "quality": _at(daily, "sleepScores", "overall", "qualifierKey"),
            "deep_min": _minutes(_at(daily, "deepSleepSeconds")),
            "light_min": _minutes(_at(daily, "lightSleepSeconds")),
            "rem_min": _minutes(_at(daily, "remSleepSeconds")),
            "awake_min": _minutes(_at(daily, "awakeSleepSeconds")),
        }
    )


def _hrv(hrv: object) -> dict[str, object] | None:
    summary = _at(hrv, "hrvSummary")
    fields = _present(
        {
            "last_night_avg": _at(summary, "lastNightAvg"),
            "weekly_avg": _at(summary, "weeklyAvg"),
            "status": _at(summary, "status"),
        }
    )
    return fields or None


def _readiness(records: object, target_date: str) -> dict[str, object] | None:
    """Garmin returns a list of records (one per sync): the day's, else the first."""
    record: object = records
    if isinstance(records, list):
        today = [r for r in records if _at(r, "calendarDate") == target_date]
        record = today[0] if today else (records[0] if records else None)
    fields = _present(
        {
            "score": _at(record, "score"),
            "level": _at(record, "level"),
            "feedback": _at(record, "feedbackShort"),
        }
    )
    return fields or None


def _activity(activity: object) -> dict[str, object]:
    duration = _num(_at(activity, "duration"))
    distance = _num(_at(activity, "distance"))
    load = _num(_at(activity, "activityTrainingLoad"))
    return _present(
        {
            "name": _at(activity, "activityName"),
            "type": _at(activity, "activityType", "typeKey"),
            "start": _at(activity, "startTimeLocal"),
            "duration_min": round(duration / 60) if duration else None,
            "distance_km": round(distance / 1000, 1) if distance else None,
            "avg_hr": _at(activity, "averageHR"),
            "training_load": round(load) if load is not None else None,
        }
    )


def morning_summary(snapshot: Mapping[str, object], target_date: str) -> dict[str, object]:
    """The morning numbers from a readiness snapshot; failed sections are named."""
    errors = {
        key: str(error)
        for key, value in snapshot.items()
        if isinstance(value, Mapping) and isinstance(error := value.get("error"), str)
    }

    def section(key: str) -> object:
        return None if key in errors else snapshot.get(key)

    activities = section("recent_activities")
    return {
        "action": "get_morning_summary",
        "date": target_date,
        "wake": _wake(section("stats")),
        "sleep": _sleep(section("sleep")),
        "hrv": _hrv(section("hrv")),
        "training_readiness": _readiness(section("training_readiness"), target_date),
        "training_status": _find(section("training_status"), "trainingStatusFeedbackPhrase"),
        "recent_activities": [
            _activity(a) for a in (activities if isinstance(activities, list) else [])
        ][:MORNING_ACTIVITIES],
        **({"errors": errors} if errors else {}),
        "note": NOTE,
    }
