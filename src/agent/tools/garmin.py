"""Garmin Connect health and fitness data tool.

Read-only tool for accessing the user's training, health, and activity data
from Garmin Connect. No write operations.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.garmin_courses import slim_course_detail, slim_course_summary
from src.agent.tools.garmin_payloads import (
    slim_exercise_set,
    slim_hr_zones,
    slim_lap,
    strip_bulky_fields,
)
from src.agent.tools.garmin_session import get_client, persist_tokens_if_changed
from src.agent.tools.integration_status import not_connected_result
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_garmin_client() -> Any | None:
    """Get an authenticated Garmin client for the current user.

    Sessions are cached per user (see garmin_session) so a turn that reads
    several endpoints pays the login round trips once, not once per call.
    Returns None if user is not connected to Garmin.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None
    return get_client(user_id)


def _persist_refreshed_tokens(garmin: Any) -> None:
    """Save tokens after API calls, but only when garth actually rotated them."""
    _, user_id = get_conversation_context()
    if not user_id:
        return
    persist_tokens_if_changed(user_id, garmin)


def safe_api_call(garmin: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Safely call a Garmin API method with error handling and token refresh."""
    try:
        method = getattr(garmin, method_name)
        result = method(*args, **kwargs)
        _persist_refreshed_tokens(garmin)
        return result
    except Exception as e:
        error_str = str(e).lower()
        if "expired" in error_str or "unauthorized" in error_str or "401" in error_str:
            raise Exception(
                "Garmin session has expired. Please reconnect your Garmin account in Settings."
            ) from e
        if "rate limit" in error_str or "too many" in error_str or "429" in error_str:
            raise Exception("Garmin rate limited. Please try again in a few minutes.") from e
        if "403" in error_str or "forbidden" in error_str:
            raise Exception(
                "Garmin API access denied. This data may not be available for your device."
            ) from e
        raise


# Max laps to expose per activity - covers interval sessions without letting a
# long auto-lapped ride (one lap per km) flood the context.
_MAX_LAPS = 40


def _gather(tasks: dict[str, Any]) -> None:
    """Run best-effort Garmin sub-fetches concurrently, swallowing failures.

    Each task runs in a copy of the calling context: the Garmin helpers read
    the conversation/user contextvars, and a bare thread pool would not carry
    them across, silently losing the user id.
    """
    if not tasks:
        return

    def _run(label: str, fn: Any) -> None:
        try:
            copy_context().run(fn)
        except Exception as e:  # best-effort sub-fetch; the others still run
            logger.debug(
                "Garmin sub-fetch failed", extra={"fetch": label, "error": str(e)}, exc_info=True
            )

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        list(pool.map(lambda item: _run(item[0], item[1]), tasks.items()))


def _attach_activity_breakdowns(garmin: Any, activity_id: str, payload: dict[str, Any]) -> None:
    """Best-effort attach per-set / HR-zone / per-lap breakdowns to an activity.

    Each lives in a dedicated Garmin endpoint that get_activity does not
    include, so they are fetched concurrently - run serially they tripled the
    wall-clock of every get_activity_details call. Any endpoint that errors or
    has no data is simply skipped: these enrich the activity but must never
    fail the details call.
    """

    def _sets() -> None:
        sets_result = safe_api_call(garmin, "get_activity_exercise_sets", activity_id)
        raw_sets = sets_result.get("exerciseSets") if isinstance(sets_result, dict) else sets_result
        if isinstance(raw_sets, list) and raw_sets:
            payload["exercise_sets"] = [
                slim_exercise_set(s) for s in raw_sets if isinstance(s, dict)
            ]

    def _zones() -> None:
        zones = safe_api_call(garmin, "get_activity_hr_in_timezones", activity_id)
        if isinstance(zones, list) and zones:
            payload["hr_zones"] = slim_hr_zones(zones)

    def _laps() -> None:
        # A single lap == the whole activity, already covered by the summary,
        # so only expose 2+ laps.
        splits = safe_api_call(garmin, "get_activity_splits", activity_id)
        laps = splits.get("lapDTOs") if isinstance(splits, dict) else None
        if isinstance(laps, list) and len(laps) >= 2:
            payload["laps"] = [slim_lap(lap, i) for i, lap in enumerate(laps[:_MAX_LAPS], start=1)]
            if len(laps) > _MAX_LAPS:
                payload["laps_note"] = f"showing first {_MAX_LAPS} of {len(laps)} laps"

    _gather({"exercise sets": _sets, "HR zones": _zones, "lap splits": _laps})


# Garmin's course-service (saved routes/courses) - not wrapped by the
# garminconnect library, so we hit the raw endpoints via connectapi.
_COURSE_LIST_URL = "/course-service/course"
_COURSE_DETAIL_URL = "/course-service/course/{}"


def _readiness_snapshot(garmin: Any, target_date: str, limit: int | None) -> dict[str, Any]:
    """Every "how recovered am I" metric in one concurrent fetch.

    Assessing readiness needs training readiness, sleep, HRV, daily stats (for
    Body Battery and resting HR), training status and recent activities. Asked
    one action at a time that is five or six tool calls, and each extra round
    re-sends the whole conversation to the model. Fetched together they cost
    roughly one Garmin round trip.

    Every section is independent and best-effort: a device that reports no HRV
    yields {"error": ...} under `hrv` while the rest of the snapshot stands.
    """
    payload: dict[str, Any] = {"action": "get_readiness_snapshot", "date": target_date}

    def _section(key: str, method: str, *args: Any) -> Any:
        def run() -> None:
            try:
                payload[key] = strip_bulky_fields(safe_api_call(garmin, method, *args))
            except Exception as e:  # best-effort section; the error goes to the model
                logger.debug(
                    "Garmin readiness section failed", extra={"section": key}, exc_info=True
                )
                payload[key] = {"error": str(e)}

        return run

    start = (date.today() - timedelta(days=90)).isoformat()
    end = date.today().isoformat()

    def _activities() -> None:
        try:
            result = safe_api_call(garmin, "get_activities_by_date", start, end, None)
            if isinstance(result, list):
                result = result[: limit or 5]
            payload["recent_activities"] = strip_bulky_fields(result, max_list_items=50)
        except Exception as e:  # best-effort section; the error goes to the model
            logger.debug(
                "Garmin readiness section failed",
                extra={"section": "recent_activities"},
                exc_info=True,
            )
            payload["recent_activities"] = {"error": str(e)}

    _gather(
        {
            "training readiness": _section(
                "training_readiness", "get_training_readiness", target_date
            ),
            "sleep": _section("sleep", "get_sleep_data", target_date),
            "HRV": _section("hrv", "get_hrv_data", target_date),
            "daily stats": _section("stats", "get_stats", target_date),
            "training status": _section("training_status", "get_training_status", target_date),
            "recent activities": _activities,
        }
    )
    return payload


_GARMIN_ACTIONS = {
    "get_readiness_snapshot",
    "get_stats",
    "get_heart_rates",
    "get_sleep_data",
    "get_stress_data",
    "get_hrv_data",
    "get_spo2_data",
    "get_body_composition",
    "get_activities",
    "get_activity_details",
    "get_training_readiness",
    "get_training_status",
    "get_steps",
    "get_courses",
    "get_course_details",
}


@tool
def garmin_connect(
    action: str,
    date_str: str | None = None,
    activity_id: str | None = None,
    limit: int | None = None,
    activity_type: str | None = None,
    course_id: str | None = None,
) -> str:
    """Access health, fitness, and training data from the user's Garmin Connect account.

    IMPORTANT: This tool only works if the user has connected their Garmin account
    in settings. A "Garmin disconnected" / "Garmin not connected" result says
    which case applies - follow its message (warn the user and point them to
    Settings); never act as if you cannot use Garmin at all.

    This is a READ-ONLY tool — no data is modified on Garmin.

    Actions available:
    - "get_readiness_snapshot": PREFERRED for any "how am I / how recovered am I /
      what should I train today" question. Returns training readiness, sleep,
      HRV, daily stats (Body Battery, resting HR), training status AND recent
      activities together in ONE call. Use this instead of calling get_training_
      readiness + get_sleep_data + get_hrv_data + get_stats + get_activities
      separately - it is one round instead of five. Optional: date_str, limit
      (recent activities to include, default 5). Sections that a device does
      not report come back as {"error": ...}; the rest of the snapshot is still
      valid.
    - "get_stats": Daily summary (steps, distance, calories, floors, active minutes)
      plus recovery metrics: Body Battery (use `bodyBatteryAtWakeTime` for the
      stable morning value, not `bodyBatteryMostRecentValue`) and resting heart
      rate (`restingHeartRate`, `lastSevenDaysAvgRestingHeartRate`).
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_heart_rates": Resting HR, HR zones, min/max for a day.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_sleep_data": Sleep quality, stages (deep/light/REM/awake), duration.
      Optional: date_str (YYYY-MM-DD, defaults to last night).
    - "get_stress_data": Stress levels throughout the day.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_hrv_data": Heart rate variability data.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_spo2_data": Blood oxygen (SpO2) readings.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_body_composition": Weight, body fat %, BMI, muscle mass.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_activities": List recent activities.
      Optional: limit (default 10), activity_type (e.g., "running", "cycling").
    - "get_activity_details": Detailed data for one activity, including
      breakdowns beyond the summary: `exercise_sets` (strength: per-set type,
      exercise, reps, weight_kg, duration - e.g. 28/23/16 reps across three sets),
      `hr_zones` (minutes spent in each heart-rate zone), and `laps` (per-lap
      distance/HR/power/cadence/speed for interval sessions).
      Required: activity_id.
    - "get_training_readiness": Training readiness score and contributing factors.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_training_status": Training status and load metrics.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_steps": Step count and daily goal.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_courses": List the user's saved courses/routes (custom cycling &
      running routes) with length and total climb: {course_id, name,
      activity_type, distance_km, elevation_gain_m, elevation_loss_m}.
      Optional: activity_type to filter (substring match, e.g. "cycling").
    - "get_course_details": Full profile for one course. Required: course_id.
      Returns distance, exact elevation gain/loss, min/max elevation, an altitude
      `profile` (~32 distance/elevation samples), and derived `climbs` (each with
      start_km, length_km, gain_m, avg_grade_pct, max_grade_pct). Climbs are
      approximated from the profile; the totals are Garmin's exact values.

    Args:
        action: The action to perform
        date_str: Date in YYYY-MM-DD format (defaults to today for most actions)
        activity_id: Activity ID for get_activity_details
        limit: Number of activities to return for get_activities (default 10)
        activity_type: Filter by activity type for get_activities / get_courses
        course_id: Course ID for get_course_details

    Returns:
        JSON string with the result
    """
    logger.info("garmin_connect called", extra={"action": action})

    garmin = get_garmin_client()
    if not garmin:
        return not_connected_result("garmin")

    target_date = date_str or date.today().isoformat()

    try:
        if action == "get_readiness_snapshot":
            return json.dumps(_readiness_snapshot(garmin, target_date, limit))

        if action in _DAILY_ACTIONS:
            api_method, result_key = _DAILY_ACTIONS[action]
            result = safe_api_call(garmin, api_method, target_date)
            return json.dumps(
                {"action": action, "date": target_date, result_key: strip_bulky_fields(result)}
            )

        if action == "get_activities":
            return _activities_result(garmin, limit, activity_type)

        if action == "get_activity_details":
            return _activity_details_result(garmin, activity_id)

        if action == "get_courses":
            return _courses_result(garmin, activity_type)

        if action == "get_course_details":
            return _course_details_result(garmin, course_id)

        return tool_error(f"Unknown action: {action}", available_actions=sorted(_GARMIN_ACTIONS))

    except Exception as e:
        logger.exception("Garmin tool error", extra={"action": action, "error": str(e)})
        return tool_error(str(e), action=action)


# One-day reads: action -> (Garmin API method, result key)
_DAILY_ACTIONS = {
    "get_stats": ("get_stats", "stats"),
    "get_heart_rates": ("get_heart_rates", "heart_rates"),
    "get_sleep_data": ("get_sleep_data", "sleep"),
    "get_stress_data": ("get_stress_data", "stress"),
    "get_hrv_data": ("get_hrv_data", "hrv"),
    "get_spo2_data": ("get_spo2_data", "spo2"),
    "get_body_composition": ("get_body_composition", "body_composition"),
    "get_training_readiness": ("get_training_readiness", "training_readiness"),
    "get_training_status": ("get_training_status", "training_status"),
    "get_steps": ("get_steps_data", "steps"),
}


def _activities_result(garmin: Any, limit: int | None, activity_type: str | None) -> str:
    """The last 90 days of activities, newest `limit` (default 10)."""
    start = (date.today() - timedelta(days=90)).isoformat()
    end = date.today().isoformat()
    result = safe_api_call(garmin, "get_activities_by_date", start, end, activity_type)
    if isinstance(result, list):
        result = result[:limit] if limit else result[:10]
    return json.dumps(
        {
            "action": "get_activities",
            "count": len(result) if isinstance(result, list) else 0,
            "activities": strip_bulky_fields(result, max_list_items=50),
        }
    )


def _activity_details_result(garmin: Any, activity_id: str | None) -> str:
    if not activity_id:
        return tool_error("activity_id is required for get_activity_details")
    result = safe_api_call(garmin, "get_activity", activity_id)
    payload: dict[str, Any] = {
        "action": "get_activity_details",
        "activity_id": activity_id,
        "activity": strip_bulky_fields(result),
    }
    # get_activity returns only summaryDTO. The granular breakdowns
    # (strength sets, HR time-in-zone, per-lap splits) each live in a
    # separate endpoint - attach them best-effort.
    _attach_activity_breakdowns(garmin, activity_id, payload)
    return json.dumps(payload)


def _courses_result(garmin: Any, activity_type: str | None) -> str:
    result = safe_api_call(garmin, "connectapi", _COURSE_LIST_URL)
    courses = (
        [slim_course_summary(c) for c in result if isinstance(c, dict)]
        if isinstance(result, list)
        else []
    )
    if activity_type:
        courses = [c for c in courses if activity_type in (c.get("activity_type") or "")]
    return json.dumps({"action": "get_courses", "count": len(courses), "courses": courses})


def _course_details_result(garmin: Any, course_id: str | None) -> str:
    if not course_id:
        return tool_error("course_id is required for get_course_details")
    result = safe_api_call(garmin, "connectapi", _COURSE_DETAIL_URL.format(course_id))
    return json.dumps({"action": "get_course_details", "course": slim_course_detail(result)})


def is_garmin_available() -> bool:
    """Check if garminconnect package is installed."""
    try:
        import garminconnect  # noqa: F401, PLC0415 - the import is the availability probe

        return True
    except ImportError:
        return False
