"""Garmin Connect strength-workout editing tool.

Read AND write access to the user's saved Garmin workouts (the custom workouts
they build in Garmin Connect / on the watch). Lets the agent adjust weight,
reps, rest, and sets, swap a movement, and add/remove exercises and set-blocks
before a session so the correct targets show on the device during the workout.

Unlike ``garmin_connect`` (read-only health data), this tool WRITES back to
Garmin. Edits are applied in place via ``update_workout`` (HTTP PUT), so the
workout keeps its id and any calendar schedule.

Garmin's raw workout JSON is deeply nested (repeat groups of interval/rest
steps). We never hand that raw shape to the LLM: ``slim_workout`` projects it
to a compact view keyed by ``step_id``, and ``apply_edits`` maps step-id-keyed
edit ops back onto the raw tree before PUTting it. New steps are built with the
library's typed builders; exercise names are validated against the bundled
Garmin catalog. This keeps token cost low and edits unambiguous.

Weight convention: the workout endpoint stores weightValue in KILOGRAMS
(24.0 == 24 kg), which differs from the activity endpoint (grams). We keep the
whole agent-facing surface in kg.
"""

import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.errors import tool_error
from src.agent.tools.garmin import (
    get_garmin_client,
    safe_api_call,
)

# Reuse the client/token plumbing that already backs the read-only tool.
from src.agent.tools.garmin_workout_edits import (
    apply_edits,
    parse_edits,
    slim_workout,
)
from src.agent.tools.integration_status import not_connected_result
from src.agent.tools.permission_check import call_arguments, check_autonomous_permission
from src.utils.logging import get_logger

logger = get_logger(__name__)


_MAX_SEARCH_RESULTS = 15

# The edit-ops manual: on the get result (which always precedes an update) and
# on an invalid-edits error, not in the declaration re-sent on every model call
EDIT_GUIDE = """edits = a JSON-encoded array string of ops, applied in order against the step_ids of THIS get (they change on every save - get again before the next update). Each op has an "op" (default "set"):
- set numbers on a step: {"step_id": 12, "reps": 6, "weight_kg": 26}; rest: {"step_id": 13, "rest_s": 120}; sets: {"step_id": 10, "sets": 5} (a block_id)
- {"op": "swap", "step_id": 12, "exercise": "Goblet Squat"} (may also set reps/weight_kg)
- {"op": "remove", "step_id": 12} (an exercise also drops its rest; a block_id removes the whole block)
- {"op": "add_exercise", "block_id": 10, "exercise": "Bulgarian Split Squat", "reps": 10, "weight_kg": 12, "rest_s": 75}
- {"op": "add_block", "exercise": "Plank", "sets": 3, "reps": 12, "weight_kg": 0, "rest_s": 60}
Weights are in KILOGRAMS (0 or omit for bodyweight). reps only work on steps whose end_condition is "reps" (carries and lap-button moves: weight only). Swap/add an exercise Garmin knows (search_exercises; unknown names are rejected with a warning). Garmin has no RPE field: keep RPE in the sports kv_store and turn it into a concrete weight/rep target. Base changes on evidence (last session's sets via garmin_connect get_activity_details, in kg too, plus kv_store progress) and tell the user what changed from "applied"."""


def _search_exercises(query: str | None) -> str:
    """Fuzzy-search the bundled Garmin exercise catalog; return capped matches."""
    if not query or not query.strip():
        return tool_error("query is required for search_exercises")
    from garminconnect.exercises import find  # noqa: PLC0415 - optional dependency (see is_garmin_available)

    hits = find(query)
    return json.dumps(
        {
            "action": "search_exercises",
            "query": query,
            "count": len(hits),
            "results": hits[:_MAX_SEARCH_RESULTS],
            "truncated": len(hits) > _MAX_SEARCH_RESULTS,
        }
    )


def _list_workouts(garmin: Any) -> str:
    """The user's saved workouts (id, name, sport)."""
    result = safe_api_call(garmin, "get_workouts", 0, 100)
    workouts = [
        {
            "workout_id": w.get("workoutId"),
            "name": w.get("workoutName"),
            "sport": (w.get("sportType") or {}).get("sportTypeKey"),
        }
        for w in (result or [])
        if isinstance(w, dict)
    ]
    return json.dumps({"action": "list", "count": len(workouts), "workouts": workouts})


def _update_workout(garmin: Any, workout_id: str | None, edits: str | None) -> str:
    """Apply the edits to a workout, save it and return Garmin's saved view."""
    if not workout_id:
        return tool_error("workout_id is required for update")
    if edits is None:
        return tool_error("edits is required for update")
    try:
        parsed = parse_edits(edits)
    except (ValueError, json.JSONDecodeError) as e:
        return tool_error(f"invalid edits: {e}", how_to_edit=EDIT_GUIDE)
    if not parsed:
        return tool_error("edits must contain at least one edit")

    raw = safe_api_call(garmin, "get_workout_by_id", workout_id)
    raw, applied, warnings = apply_edits(raw, parsed)
    safe_api_call(garmin, "update_workout", workout_id, raw)
    # Re-fetch so the returned view is Garmin's persisted ground truth.
    refreshed = safe_api_call(garmin, "get_workout_by_id", workout_id)
    return json.dumps(
        {
            "action": "update",
            "applied": applied,
            "warnings": warnings,
            "workout": slim_workout(refreshed),
        }
    )


@tool
def garmin_workout(
    action: str,
    workout_id: str | None = None,
    edits: str | None = None,
    query: str | None = None,
) -> str:
    """Read and edit the user's saved Garmin strength workouts.

    Keeps the targets shown ON THE WATCH accurate before a session: weight, reps,
    rest, sets, swapping a movement, adding/removing exercises and set-blocks.
    Writes go straight to the user's Garmin account, in place (same id and schedule).

    Actions:
    - list: saved workouts as {workout_id, name, sport}, to find one by name.
    - get (workout_id): the workout as {name, blocks: [{block_id, sets, steps}]}, each
      step keyed by step_id, plus how to write edits. ALWAYS get right before an
      update: step_ids are reassigned on every save.
    - search_exercises (query): valid Garmin exercise names for swap/add.
    - update (workout_id, edits): apply edits; returns what was applied and the
      refreshed workout. Weights are in kilograms.

    Args:
        action: "list", "get", "search_exercises", or "update".
        workout_id: Target workout id (get/update).
        edits: JSON array string of edit ops, as the get result describes (update).
        query: Search term (search_exercises).
    """
    logger.info("garmin_workout called", extra={"action": action, "workout_id": workout_id})
    # An unattended run: its grants decide (a change without the write level
    # is a draft the user approves); raises before anything is touched
    check_autonomous_permission("garmin_workout", call_arguments(garmin_workout, locals()))

    if action == "search_exercises":
        return _search_exercises(query)

    garmin = get_garmin_client()
    if not garmin:
        return not_connected_result("garmin")

    try:
        if action == "list":
            return _list_workouts(garmin)

        if action == "get":
            if not workout_id:
                return tool_error("workout_id is required for get")
            raw = safe_api_call(garmin, "get_workout_by_id", workout_id)
            return json.dumps(
                {"action": "get", "workout": slim_workout(raw), "how_to_edit": EDIT_GUIDE}
            )

        if action == "update":
            return _update_workout(garmin, workout_id, edits)

        return tool_error(
            f"Unknown action: {action}",
            available_actions=["list", "get", "search_exercises", "update"],
        )

    except Exception as e:
        logger.exception("garmin_workout error", extra={"action": action, "error": str(e)})
        return tool_error(str(e), action=action)
