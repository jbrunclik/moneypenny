"""Garmin health summary for the planner dashboard.

Each metric is best-effort: one failing call leaves only that metric empty.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from src.auth.garmin_auth import create_client_from_tokens
from src.services.planner.models import PlannerHealthSummary
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _apply_stats(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    stats = garmin.get_stats(today_str)
    if isinstance(stats, dict):
        summary.steps_today = stats.get("totalSteps")
        summary.resting_hr = stats.get("restingHeartRate")
        summary.body_battery = stats.get("bodyBatteryMostRecentValue")
        summary.stress_avg = stats.get("averageStressLevel")


def _apply_sleep(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    sleep_data = garmin.get_sleep_data(today_str)
    if not isinstance(sleep_data, dict):
        return
    daily_sleep = sleep_data.get("dailySleepDTO", {})
    # API field is 'sleepTimeSeconds', not 'sleepTimeInSeconds'
    duration_secs = daily_sleep.get("sleepTimeSeconds", 0)
    # Sleep quality is nested inside 'sleepScores.overall.qualifierKey'
    sleep_scores = daily_sleep.get("sleepScores", {})
    overall = sleep_scores.get("overall", {}) if isinstance(sleep_scores, dict) else {}
    quality = overall.get("qualifierKey") if isinstance(overall, dict) else None
    summary.sleep = {
        "duration_hours": round(duration_secs / 3600, 1) if duration_secs else None,
        "quality": quality,
    }


def _apply_heart_rate(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    hr_data = garmin.get_heart_rates(today_str)
    if isinstance(hr_data, dict):
        summary.resting_hr = summary.resting_hr or hr_data.get("restingHeartRate")


def _apply_training_readiness(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    # get_training_readiness() returns a list of records (one per sync), not a
    # dict. Take today's record if there is one, else the most recent overall.
    tr = garmin.get_training_readiness(today_str)
    tr_record: dict[str, Any] | None = None
    if isinstance(tr, list) and tr:
        today_records = [r for r in tr if r.get("calendarDate") == today_str]
        tr_record = today_records[0] if today_records else tr[0]
    elif isinstance(tr, dict):
        tr_record = tr
    if tr_record:
        summary.training_readiness = {
            "score": tr_record.get("score") or tr_record.get("overallScore"),
            "level": tr_record.get("level") or tr_record.get("overallReadiness"),
        }


def _apply_hrv(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    hrv = garmin.get_hrv_data(today_str)
    if isinstance(hrv, dict):
        summary.hrv_status = hrv.get("hrvSummary", {}).get("status") or hrv.get("status")


def _activity_summary(activity: dict[str, Any]) -> dict[str, Any]:
    start_time = activity.get("startTimeLocal")
    distance = activity.get("distance")
    duration = activity.get("duration")
    return {
        "name": activity.get("activityName", "Activity"),
        "date": start_time[:10] if start_time else "",
        "distance_km": round(distance / 1000, 1) if distance else None,
        "duration_min": round(duration / 60, 0) if duration else None,
    }


def _apply_recent_activities(garmin: Any, today_str: str, summary: PlannerHealthSummary) -> None:
    start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    activities = garmin.get_activities_by_date(start, today_str)
    if isinstance(activities, list):
        summary.recent_activities = [_activity_summary(a) for a in activities[:3]]


_MetricFetch = Callable[[Any, str, PlannerHealthSummary], None]

# (fetch, debug message when it fails), in call order
_METRICS: tuple[tuple[_MetricFetch, str], ...] = (
    (_apply_stats, "Garmin stats fetch failed"),
    (_apply_sleep, "Garmin sleep fetch failed"),
    (_apply_heart_rate, "Garmin HR fetch failed"),
    (_apply_training_readiness, "Garmin training readiness fetch failed"),
    (_apply_hrv, "Garmin HRV fetch failed"),
    (_apply_recent_activities, "Garmin activities fetch failed"),
)


def fetch_health_summary(
    garmin_token: str | None,
) -> tuple[PlannerHealthSummary | None, str | None]:
    """Fetch today's Garmin health summary; (None, None) when Garmin isn't connected."""
    if not garmin_token:
        return None, None
    try:
        garmin = create_client_from_tokens(garmin_token)
        today_str = datetime.now().strftime("%Y-%m-%d")
        summary = PlannerHealthSummary()
        for fetch, failure in _METRICS:
            try:
                fetch(garmin, today_str, summary)
            except Exception as e:  # best-effort metric; the dashboard shows the rest
                logger.debug(failure, extra={"error": str(e)}, exc_info=True)
        return summary, None

    except Exception as e:
        error_str = str(e).lower()
        if "expired" in error_str or "unauthorized" in error_str:
            return None, "Garmin session expired. Please reconnect in Settings."
        logger.exception("Garmin dashboard fetch failed", extra={"error": str(e)})
        return None, f"Garmin error: {e}"
