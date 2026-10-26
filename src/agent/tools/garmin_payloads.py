"""Slimming Garmin API payloads before they reach the LLM.

Activity and health payloads run to 50-200KB, mostly per-minute series;
these drop the bulk and project sets, HR zones and laps to the fields
coaching needs (see garmin.py).
"""

from typing import Any

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


def strip_bulky_fields(obj: Any, max_list_items: int = 20) -> Any:
    """Recursively drop bulky arrays from Garmin API responses.

    Two mechanisms: known time-series keys are removed outright, and any
    remaining list longer than max_list_items is replaced with a count
    note. Summary scalars pass through untouched. Applied to EVERY
    action's payload before it reaches the LLM.
    """
    if isinstance(obj, dict):
        return {
            k: strip_bulky_fields(v, max_list_items) for k, v in obj.items() if k not in _BULKY_KEYS
        }
    if isinstance(obj, list):
        if len(obj) > max_list_items:
            return f"[{len(obj)} items omitted - ask for specific metrics if needed]"
        return [strip_bulky_fields(v, max_list_items) for v in obj]
    return obj


def slim_exercise_set(s: dict[str, Any]) -> dict[str, Any]:
    """Project one Garmin exercise set down to the coaching-relevant fields.

    The raw set carries startTime, wktStepIndex, messageIndex, per-exercise
    probability etc. - noise for an LLM. We keep set type, the exercise, reps,
    weight and duration, which is what answers "how many reps per set".

    Weight is reported in KILOGRAMS. Note the activity endpoint stores it in
    grams (e.g. 24000 for a 24 kg kettlebell), so we divide by 1000 here to
    match the kg convention used everywhere else the agent sees weight
    (including the garmin_workout editing tool).
    """
    exercises = s.get("exercises") or []
    category = None
    if exercises and isinstance(exercises[0], dict):
        category = exercises[0].get("category")
    duration = s.get("duration")
    weight_g = s.get("weight")
    return {
        "setType": s.get("setType"),
        "category": category,
        "reps": s.get("repetitionCount"),
        "weight_kg": round(weight_g / 1000.0, 1) if isinstance(weight_g, int | float) else None,
        "duration_s": round(duration, 1) if isinstance(duration, int | float) else None,
    }


def _num(value: Any, ndigits: int = 1) -> float | None:
    """Round a numeric value, or None if it isn't a number."""
    return round(value, ndigits) if isinstance(value, int | float) else None


def slim_hr_zones(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def slim_lap(lap: dict[str, Any], index: int) -> dict[str, Any]:
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
