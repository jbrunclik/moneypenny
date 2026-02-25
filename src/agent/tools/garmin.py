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
    - "get_stats": Daily summary (steps, distance, calories, floors, active minutes).
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
    - "get_activity_details": Detailed data for one activity.
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
                "message": "Please ask the user to connect their Garmin account in settings first.",
            }
        )

    target_date = date_str or date.today().isoformat()

    try:
        if action == "get_stats":
            result = _safe_api_call(garmin, "get_stats", target_date)
            return json.dumps({"action": "get_stats", "date": target_date, "stats": result})

        elif action == "get_heart_rates":
            result = _safe_api_call(garmin, "get_heart_rates", target_date)
            return json.dumps(
                {"action": "get_heart_rates", "date": target_date, "heart_rates": result}
            )

        elif action == "get_sleep_data":
            result = _safe_api_call(garmin, "get_sleep_data", target_date)
            return json.dumps({"action": "get_sleep_data", "date": target_date, "sleep": result})

        elif action == "get_stress_data":
            result = _safe_api_call(garmin, "get_stress_data", target_date)
            return json.dumps({"action": "get_stress_data", "date": target_date, "stress": result})

        elif action == "get_hrv_data":
            result = _safe_api_call(garmin, "get_hrv_data", target_date)
            return json.dumps({"action": "get_hrv_data", "date": target_date, "hrv": result})

        elif action == "get_spo2_data":
            result = _safe_api_call(garmin, "get_spo2_data", target_date)
            return json.dumps({"action": "get_spo2_data", "date": target_date, "spo2": result})

        elif action == "get_body_composition":
            result = _safe_api_call(garmin, "get_body_composition", target_date)
            return json.dumps(
                {
                    "action": "get_body_composition",
                    "date": target_date,
                    "body_composition": result,
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
                    "activities": result,
                }
            )

        elif action == "get_activity_details":
            if not activity_id:
                return json.dumps({"error": "activity_id is required for get_activity_details"})
            result = _safe_api_call(garmin, "get_activity", activity_id)
            return json.dumps(
                {
                    "action": "get_activity_details",
                    "activity_id": activity_id,
                    "activity": result,
                }
            )

        elif action == "get_training_readiness":
            result = _safe_api_call(garmin, "get_training_readiness", target_date)
            return json.dumps(
                {
                    "action": "get_training_readiness",
                    "date": target_date,
                    "training_readiness": result,
                }
            )

        elif action == "get_training_status":
            result = _safe_api_call(garmin, "get_training_status", target_date)
            return json.dumps(
                {
                    "action": "get_training_status",
                    "date": target_date,
                    "training_status": result,
                }
            )

        elif action == "get_steps":
            result = _safe_api_call(garmin, "get_steps_data", target_date)
            return json.dumps({"action": "get_steps", "date": target_date, "steps": result})

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
