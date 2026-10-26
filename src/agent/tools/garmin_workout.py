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
from src.utils.logging import get_logger

logger = get_logger(__name__)


_MAX_SEARCH_RESULTS = 15


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
        return tool_error(f"invalid edits: {e}")
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

    Use this to keep the targets shown ON THE WATCH accurate before a session —
    adjust weight/reps/rest/sets, swap a movement, or add/remove exercises and
    set-blocks. Writes go straight to the user's Garmin account (in place; the
    workout keeps its id and schedule).

    Actions:
    - "list": List all saved workouts as {workout_id, name, sport}. Use to find a
      workout by name (e.g. "Man Cave - Monday").
    - "get": Return one workout in a compact editable view. Required: workout_id.
      Shape: {name, blocks: [{block_id, sets, steps: [...]}]}. Each step has a
      "step_id" — the KEY you edit by. Exercise steps show "exercise",
      "end_condition", "reps", "weight_kg"; rest steps show "rest_s".
      ALWAYS "get" immediately before an "update": step_ids are reassigned on
      every save, so ids from an earlier read (or a prior update) are stale.
    - "search_exercises": Look up valid Garmin exercises by name (Garmin knows
      ~1500). Required: query (e.g. "split squat"). Returns [{name, category,
      exercise}]. Use the returned "exercise" (or "name") when swapping/adding.
    - "update": Apply edits, then return {applied: [...], warnings, workout:
      <refreshed view>}. Required: workout_id, edits. Use "applied" to tell the
      user exactly what changed.

    Edit ops (edits = a JSON-encoded array string; each op has an "op", default "set"):
    - Edit numbers (existing step): {"step_id": 12, "reps": 6, "weight_kg": 26}
      rest: {"step_id": 13, "rest_s": 120}; sets: {"step_id": 10, "sets": 5} (block id)
    - Swap movement: {"op": "swap", "step_id": 12, "exercise": "Goblet Squat"}
      (optionally also set reps/weight_kg in the same op)
    - Remove: {"op": "remove", "step_id": 12}  (an exercise also drops its rest;
      a block id removes the whole block)
    - Add exercise to a block: {"op": "add_exercise", "block_id": 10,
      "exercise": "Bulgarian Split Squat", "reps": 10, "weight_kg": 12, "rest_s": 75}
    - Add a new set-block: {"op": "add_block", "exercise": "Plank", "sets": 3,
      "reps": 12, "weight_kg": 0, "rest_s": 60}
    Ops in one update apply in order against the ids from your latest "get".

    IMPORTANT constraints:
    - Weights are in KILOGRAMS (0 or omit weight_kg for bodyweight moves).
    - For swap/add, prefer an exercise Garmin knows — verify with
      "search_exercises" if unsure; an unknown name is rejected with a warning.
    - "reps" only works when a step's end_condition is "reps". For carries/
      lap-button moves reps is device-driven — you can only change weight.
    - Garmin has no RPE field. RPE can't be pushed to the watch; track it in the
      sports kv_store and translate it into a concrete weight/rep target here.
    - Base changes on evidence (last session's logged sets via garmin_connect
      get_activity_details, plus kv_store progress), and tell the user what
      changed. get_activity_details reports weight in kg too, so numbers line up.

    Args:
        action: "list", "get", "search_exercises", or "update".
        workout_id: Target workout id (required for get/update).
        edits: A JSON string encoding an array of edit ops (required for update),
            e.g. '[{"step_id": 12, "reps": 6, "weight_kg": 26}]'.
        query: Search term (required for search_exercises).

    Returns:
        JSON string with the result (or an "error"/"warnings" field).
    """
    logger.info("garmin_workout called", extra={"action": action, "workout_id": workout_id})

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
            return json.dumps({"action": "get", "workout": slim_workout(raw)})

        if action == "update":
            return _update_workout(garmin, workout_id, edits)

        return tool_error(
            f"Unknown action: {action}",
            available_actions=["list", "get", "search_exercises", "update"],
        )

    except Exception as e:
        logger.exception("garmin_workout error", extra={"action": action, "error": str(e)})
        return tool_error(str(e), action=action)
