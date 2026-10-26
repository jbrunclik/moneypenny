"""Saved Garmin courses for the LLM: a compact altitude profile and the
climbs detected in it (Garmin gives no climb breakdown), see garmin.py.
"""

from typing import Any

# How many (distance, elevation) samples to expose for a course's altitude
# profile. Raw geoPoints run to thousands per course - far too many for an LLM;
# ~32 evenly-distance-spaced samples convey the shape at negligible token cost.
_PROFILE_SAMPLES = 32

# Climb detection tuning (derived from the profile - Garmin gives no climb
# breakdown). A "climb" is a sustained ascent; small dips inside it are
# tolerated up to _CLIMB_MAX_DROP_M before it's considered over.
_CLIMB_RESAMPLE_M = 50.0
_CLIMB_MIN_GAIN_M = 25.0
_CLIMB_MIN_GRADE = 0.03
_CLIMB_MAX_DROP_M = 12.0


def _course_points(detail: dict[str, Any]) -> list[tuple[float, float]]:
    """Extract sorted (cumulative_distance_m, elevation_m) points from a course."""
    pts = []
    for p in detail.get("geoPoints") or []:
        if not isinstance(p, dict):
            continue
        d, e = p.get("distance"), p.get("elevation")
        if isinstance(d, int | float) and isinstance(e, int | float):
            pts.append((float(d), float(e)))
    pts.sort(key=lambda x: x[0])
    return pts


def _resample_fixed(points: list[tuple[float, float]], step_m: float) -> list[tuple[float, float]]:
    """Resample the profile at fixed distance intervals (smooths GPS elevation noise)."""
    if len(points) < 2:
        return points
    total = points[-1][0]
    out: list[tuple[float, float]] = []
    j = 0
    d = points[0][0]
    while d <= total:
        while j < len(points) - 1 and points[j][0] < d:
            j += 1
        out.append((d, points[j][1]))
        d += step_m
    if out[-1][0] < total:
        out.append(points[-1])
    return out


def profile_samples(points: list[tuple[float, float]], n: int) -> list[dict[str, float]]:
    """Downsample the elevation profile to ~n evenly-distance-spaced points."""
    if not points:
        return []
    if len(points) <= n:
        return [{"km": round(d / 1000, 2), "elev_m": round(e)} for d, e in points]
    total = points[-1][0]
    out: list[dict[str, float]] = []
    j = 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(points) - 1 and points[j][0] < target:
            j += 1
        out.append({"km": round(points[j][0] / 1000, 2), "elev_m": round(points[j][1])})
    return out


def _climb_record(prof: list[tuple[float, float]], a: int, b: int) -> dict[str, float]:
    """Build one climb summary from resampled profile indices a..b."""
    gain = prof[b][1] - prof[a][1]
    length = prof[b][0] - prof[a][0]
    max_grade = 0.0
    for k in range(a, b):
        seg, dl = prof[k + 1][1] - prof[k][1], prof[k + 1][0] - prof[k][0]
        if dl > 0:
            max_grade = max(max_grade, seg / dl)
    return {
        "start_km": round(prof[a][0] / 1000, 1),
        "length_km": round(length / 1000, 2),
        "gain_m": round(gain),
        "avg_grade_pct": round(gain / length * 100, 1) if length else 0.0,
        "max_grade_pct": round(max_grade * 100, 1),
    }


def _qualifying_climb(
    prof: list[tuple[float, float]], base_i: int, peak_i: int
) -> list[dict[str, float]]:
    """The climb from base to peak as a one-item list, or [] below the thresholds."""
    gain = prof[peak_i][1] - prof[base_i][1]
    length = prof[peak_i][0] - prof[base_i][0]
    if gain >= _CLIMB_MIN_GAIN_M and length > 0 and gain / length >= _CLIMB_MIN_GRADE:
        return [_climb_record(prof, base_i, peak_i)]
    return []


def detect_climbs(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    """Derive sustained climbs from an elevation profile (Garmin gives none).

    Walks a fixed-step resample tracking the current valley (base) and running
    peak; a climb is recorded when the rise from the base clears the gain and
    average-grade thresholds and is then followed by a drop past the tolerance.
    """
    prof = _resample_fixed(points, _CLIMB_RESAMPLE_M)
    if len(prof) < 2:
        return []
    climbs: list[dict[str, float]] = []
    base_i = peak_i = 0
    in_climb = False

    for i in range(1, len(prof)):
        elev = prof[i][1]
        if elev > prof[peak_i][1]:
            peak_i = i
        if not in_climb:
            if elev < prof[base_i][1]:
                base_i = peak_i = i
            elif prof[peak_i][1] - prof[base_i][1] >= _CLIMB_MIN_GAIN_M:
                in_climb = True
        elif prof[peak_i][1] - elev > _CLIMB_MAX_DROP_M:
            climbs.extend(_qualifying_climb(prof, base_i, peak_i))
            base_i = peak_i = i
            in_climb = False
    if in_climb:
        climbs.extend(_qualifying_climb(prof, base_i, peak_i))
    return climbs


def slim_course_summary(c: dict[str, Any]) -> dict[str, Any]:
    """Project a course list item to length + total climb + type."""
    dist = c.get("distanceInMeters")
    gain = c.get("elevationGainInMeters")
    loss = c.get("elevationLossInMeters")
    return {
        "course_id": c.get("courseId"),
        "name": c.get("courseName"),
        "activity_type": (c.get("activityType") or {}).get("typeKey"),
        "distance_km": round(dist / 1000, 2) if isinstance(dist, int | float) else None,
        "elevation_gain_m": round(gain) if isinstance(gain, int | float) else None,
        "elevation_loss_m": round(loss) if isinstance(loss, int | float) else None,
        "favorite": c.get("favorite"),
    }


def slim_course_detail(d: dict[str, Any]) -> dict[str, Any]:
    """Project a full course to summary + derived climbs + a compact profile."""
    points = _course_points(d)
    elevs = [e for _, e in points]
    dist = d.get("distanceMeter")
    gain = d.get("elevationGainMeter")
    loss = d.get("elevationLossMeter")
    climbs = detect_climbs(points)
    return {
        "course_id": d.get("courseId"),
        "name": d.get("courseName"),
        "distance_km": round(dist / 1000, 2) if isinstance(dist, int | float) else None,
        "elevation_gain_m": round(gain) if isinstance(gain, int | float) else None,
        "elevation_loss_m": round(loss) if isinstance(loss, int | float) else None,
        "min_elevation_m": round(min(elevs)) if elevs else None,
        "max_elevation_m": round(max(elevs)) if elevs else None,
        # Climbs are DERIVED from the profile (Garmin exposes no climb API), so
        # they approximate Garmin's own climb list; the totals above are exact.
        "climb_count": len(climbs),
        "climbs": climbs,
        "profile": profile_samples(points, _PROFILE_SAMPLES),
        "description": d.get("description") or None,
    }
