"""Garmin Connect health and fitness data tool.

Read-only tool for accessing the user's training, health, and activity data
from Garmin Connect. No write operations.
"""

import json
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _get_garmin_client() -> Any | None:
    """Get an authenticated Garmin client for the current user.

    Returns None if user is not connected to Garmin.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None

    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user or not user.garmin_token:
        return None

    try:
        from src.auth.garmin_auth import create_client_from_tokens

        return create_client_from_tokens(user.garmin_token)
    except Exception as e:
        logger.warning("Failed to create Garmin client", extra={"error": str(e)})
        return None


def _persist_refreshed_tokens(garmin: Any) -> None:
    """Re-serialize and save tokens after API calls in case garth refreshed them."""
    _, user_id = get_conversation_context()
    if not user_id:
        return

    try:
        from src.auth.garmin_auth import refresh_and_serialize
        from src.db.models import db

        updated_tokens = refresh_and_serialize(garmin)
        db.update_user_garmin_token(user_id, updated_tokens)
    except Exception as e:
        logger.debug("Failed to persist refreshed Garmin tokens", extra={"error": str(e)})


def _safe_api_call(garmin: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
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


# Known per-minute/per-epoch time-series keys in Garmin payloads. Pure
# bulk for an LLM: a single night's sleepMovement alone is hundreds of
# entries (one un-stripped get_sleep_data blew a Daily Briefing run to
# ~150k input tokens / ~$0.29). Summaries carry everything coaching needs.
_BULKY_KEYS = frozenset(
    {
        "sleepMovement",
        "sleepLevels",
        "sleepRestlessMoments",
        "sleepHeartRate",
        "sleepStress",
        "sleepBodyBattery",
        "wellnessEpochSPO2DataDTOList",
        "wellnessEpochRespirationDataDTOList",
        "hrvReadings",
        "stressValuesArray",
        "bodyBatteryValuesArray",
        "heartRateValues",
        "respirationValuesArray",
    }
)


def _strip_bulky_fields(obj: Any, max_list_items: int = 20) -> Any:
    """Recursively drop bulky arrays from Garmin API responses.

    Two mechanisms: known time-series keys are removed outright, and any
    remaining list longer than max_list_items is replaced with a count
    note. Summary scalars pass through untouched. Applied to EVERY
    action's payload before it reaches the LLM.
    """
    if isinstance(obj, dict):
        return {
            k: _strip_bulky_fields(v, max_list_items)
            for k, v in obj.items()
            if k not in _BULKY_KEYS
        }
    if isinstance(obj, list):
        if len(obj) > max_list_items:
            return f"[{len(obj)} items omitted - ask for specific metrics if needed]"
        return [_strip_bulky_fields(v, max_list_items) for v in obj]
    return obj


def _slim_exercise_set(s: dict[str, Any]) -> dict[str, Any]:
    """Project one Garmin exercise set down to the coaching-relevant fields.

    The raw set carries startTime, wktStepIndex, messageIndex, per-exercise
    probability etc. - noise for an LLM. We keep set type, the exercise, reps,
    weight and duration, which is what answers "how many reps per set".
    """
    exercises = s.get("exercises") or []
    category = None
    if exercises and isinstance(exercises[0], dict):
        category = exercises[0].get("category")
    duration = s.get("duration")
    return {
        "setType": s.get("setType"),
        "category": category,
        "reps": s.get("repetitionCount"),
        "weight": s.get("weight"),
        "duration_s": round(duration, 1) if isinstance(duration, int | float) else None,
    }


def _num(value: Any, ndigits: int = 1) -> float | None:
    """Round a numeric value, or None if it isn't a number."""
    return round(value, ndigits) if isinstance(value, int | float) else None


def _slim_hr_zones(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact the per-activity HR time-in-zone breakdown (minutes per zone)."""
    out = []
    for z in zones:
        if not isinstance(z, dict):
            continue
        secs = z.get("secsInZone")
        out.append(
            {
                "zone": z.get("zoneNumber"),
                "minutes": _num((secs / 60.0) if isinstance(secs, int | float) else None),
                "low_bpm": z.get("zoneLowBoundary"),
            }
        )
    return out


# Max laps to expose per activity - covers interval sessions without letting a
# long auto-lapped ride (one lap per km) flood the context.
_MAX_LAPS = 40


def _slim_lap(lap: dict[str, Any], index: int) -> dict[str, Any]:
    """Project one lap/split to coaching-relevant fields, dropping empty ones."""
    dist = lap.get("distance")
    dur = lap.get("duration")
    speed = lap.get("averageSpeed")
    slim = {
        "lap": index,
        "distance_km": _num((dist / 1000.0) if isinstance(dist, int | float) else None, 2),
        "duration_min": _num((dur / 60.0) if isinstance(dur, int | float) else None),
        "avg_hr": lap.get("averageHR"),
        "max_hr": lap.get("maxHR"),
        "avg_power": lap.get("averagePower"),
        "norm_power": lap.get("normalizedPower"),
        "avg_cadence": lap.get("averageBikeCadence") or lap.get("averageRunCadence"),
        "avg_speed_kmh": _num((speed * 3.6) if isinstance(speed, int | float) else None),
    }
    return {k: v for k, v in slim.items() if v is not None}


def _attach_activity_breakdowns(garmin: Any, activity_id: str, payload: dict[str, Any]) -> None:
    """Best-effort attach per-set / HR-zone / per-lap breakdowns to an activity.

    Each lives in a dedicated Garmin endpoint that get_activity does not
    include. Any endpoint that errors or has no data is simply skipped - these
    enrich the activity but must never fail the details call.
    """
    # Strength: per-set reps/weight (e.g. 28/23/16 across three sets)
    try:
        sets_result = _safe_api_call(garmin, "get_activity_exercise_sets", activity_id)
        raw_sets = sets_result.get("exerciseSets") if isinstance(sets_result, dict) else sets_result
        if isinstance(raw_sets, list) and raw_sets:
            payload["exercise_sets"] = [
                _slim_exercise_set(s) for s in raw_sets if isinstance(s, dict)
            ]
    except Exception as e:
        logger.debug("No exercise sets", extra={"activity_id": activity_id, "error": str(e)})

    # Cardio: time spent in each heart-rate zone
    try:
        zones = _safe_api_call(garmin, "get_activity_hr_in_timezones", activity_id)
        if isinstance(zones, list) and zones:
            payload["hr_zones"] = _slim_hr_zones(zones)
    except Exception as e:
        logger.debug("No HR zones", extra={"activity_id": activity_id, "error": str(e)})

    # Per-lap splits (intervals). A single lap == the whole activity, already
    # covered by the summary, so only expose 2+ laps.
    try:
        splits = _safe_api_call(garmin, "get_activity_splits", activity_id)
        laps = splits.get("lapDTOs") if isinstance(splits, dict) else None
        if isinstance(laps, list) and len(laps) >= 2:
            payload["laps"] = [_slim_lap(lap, i) for i, lap in enumerate(laps[:_MAX_LAPS], start=1)]
            if len(laps) > _MAX_LAPS:
                payload["laps_note"] = f"showing first {_MAX_LAPS} of {len(laps)} laps"
    except Exception as e:
        logger.debug("No lap splits", extra={"activity_id": activity_id, "error": str(e)})


_GARMIN_ACTIONS = {
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
}


@tool
def garmin_connect(
    action: str,
    date_str: str | None = None,
    activity_id: str | None = None,
    limit: int | None = None,
    activity_type: str | None = None,
) -> str:
    """Access health, fitness, and training data from the user's Garmin Connect account.

    IMPORTANT: This tool only works if the user has connected their Garmin account
    in settings. If you get "Garmin not connected", ask the user to connect
    their Garmin account in settings first.

    This is a READ-ONLY tool — no data is modified on Garmin.

    Actions available:
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
      exercise, reps, weight, duration - e.g. 28/23/16 reps across three sets),
      `hr_zones` (minutes spent in each heart-rate zone), and `laps` (per-lap
      distance/HR/power/cadence/speed for interval sessions).
      Required: activity_id.
    - "get_training_readiness": Training readiness score and contributing factors.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_training_status": Training status and load metrics.
      Optional: date_str (YYYY-MM-DD, defaults to today).
    - "get_steps": Step count and daily goal.
      Optional: date_str (YYYY-MM-DD, defaults to today).

    Args:
        action: The action to perform
        date_str: Date in YYYY-MM-DD format (defaults to today for most actions)
        activity_id: Activity ID for get_activity_details
        limit: Number of activities to return for get_activities (default 10)
        activity_type: Filter by activity type for get_activities

    Returns:
        JSON string with the result
    """
    logger.info("garmin_connect called", extra={"action": action})

    garmin = _get_garmin_client()
    if not garmin:
        return json.dumps(
            {
                "error": "Garmin not connected",
                "retriable": False,
                "message": "Please ask the user to connect their Garmin account in settings first.",
            }
        )

    target_date = date_str or date.today().isoformat()

    try:
        if action == "get_stats":
            result = _safe_api_call(garmin, "get_stats", target_date)
            return json.dumps(
                {"action": "get_stats", "date": target_date, "stats": _strip_bulky_fields(result)}
            )

        elif action == "get_heart_rates":
            result = _safe_api_call(garmin, "get_heart_rates", target_date)
            return json.dumps(
                {
                    "action": "get_heart_rates",
                    "date": target_date,
                    "heart_rates": _strip_bulky_fields(result),
                }
            )

        elif action == "get_sleep_data":
            result = _safe_api_call(garmin, "get_sleep_data", target_date)
            return json.dumps(
                {
                    "action": "get_sleep_data",
                    "date": target_date,
                    "sleep": _strip_bulky_fields(result),
                }
            )

        elif action == "get_stress_data":
            result = _safe_api_call(garmin, "get_stress_data", target_date)
            return json.dumps(
                {
                    "action": "get_stress_data",
                    "date": target_date,
                    "stress": _strip_bulky_fields(result),
                }
            )

        elif action == "get_hrv_data":
            result = _safe_api_call(garmin, "get_hrv_data", target_date)
            return json.dumps(
                {"action": "get_hrv_data", "date": target_date, "hrv": _strip_bulky_fields(result)}
            )

        elif action == "get_spo2_data":
            result = _safe_api_call(garmin, "get_spo2_data", target_date)
            return json.dumps(
                {
                    "action": "get_spo2_data",
                    "date": target_date,
                    "spo2": _strip_bulky_fields(result),
                }
            )

        elif action == "get_body_composition":
            result = _safe_api_call(garmin, "get_body_composition", target_date)
            return json.dumps(
                {
                    "action": "get_body_composition",
                    "date": target_date,
                    "body_composition": _strip_bulky_fields(result),
                }
            )

        elif action == "get_activities":
            start = (date.today() - timedelta(days=90)).isoformat()
            end = date.today().isoformat()
            result = _safe_api_call(garmin, "get_activities_by_date", start, end, activity_type)
            if isinstance(result, list):
                if limit:
                    result = result[:limit]
                else:
                    result = result[:10]
            return json.dumps(
                {
                    "action": "get_activities",
                    "count": len(result) if isinstance(result, list) else 0,
                    "activities": _strip_bulky_fields(result, max_list_items=50),
                }
            )

        elif action == "get_activity_details":
            if not activity_id:
                return json.dumps({"error": "activity_id is required for get_activity_details"})
            result = _safe_api_call(garmin, "get_activity", activity_id)
            payload: dict[str, Any] = {
                "action": "get_activity_details",
                "activity_id": activity_id,
                "activity": _strip_bulky_fields(result),
            }
            # get_activity returns only summaryDTO. The granular breakdowns
            # (strength sets, HR time-in-zone, per-lap splits) each live in a
            # separate endpoint - attach them best-effort.
            _attach_activity_breakdowns(garmin, activity_id, payload)
            return json.dumps(payload)

        elif action == "get_training_readiness":
            result = _safe_api_call(garmin, "get_training_readiness", target_date)
            return json.dumps(
                {
                    "action": "get_training_readiness",
                    "date": target_date,
                    "training_readiness": _strip_bulky_fields(result),
                }
            )

        elif action == "get_training_status":
            result = _safe_api_call(garmin, "get_training_status", target_date)
            return json.dumps(
                {
                    "action": "get_training_status",
                    "date": target_date,
                    "training_status": _strip_bulky_fields(result),
                }
            )

        elif action == "get_steps":
            result = _safe_api_call(garmin, "get_steps_data", target_date)
            return json.dumps(
                {"action": "get_steps", "date": target_date, "steps": _strip_bulky_fields(result)}
            )

        else:
            return json.dumps(
                {
                    "error": f"Unknown action: {action}",
                    "available_actions": sorted(_GARMIN_ACTIONS),
                }
            )

    except Exception as e:
        logger.error("Garmin tool error", extra={"action": action, "error": str(e)}, exc_info=True)
        return json.dumps({"error": str(e), "action": action})


def is_garmin_available() -> bool:
    """Check if garminconnect package is installed."""
    try:
        import garminconnect  # noqa: F401

        return True
    except ImportError:
        return False
