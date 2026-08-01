"""Unit tests for the garmin_workout tool.

Covers the pure projection/patch helpers (_slim_workout, _apply_edits) against
a fixture that mirrors the real Garmin strength structure — repeat groups
(supersets), interval/rest child steps, a lap.button carry, and a bodyweight
(null-weight) move — plus the tool's action dispatch and guards. The garth API
is never hit; the client and _safe_api_call are patched.
"""

import copy
import json
from unittest.mock import MagicMock, patch

from src.agent.tools.garmin_workout import (
    _apply_edits,
    _slim_workout,
    garmin_workout,
)


def _exec_step(step_id, order, kind, end_key, end_val, exercise=None, weight=None):
    step = {
        "type": "ExecutableStepDTO",
        "stepId": step_id,
        "stepOrder": order,
        "stepType": {"stepTypeKey": kind},
        "endCondition": {"conditionTypeKey": end_key},
        "endConditionValue": float(end_val),
        "category": exercise,
        "exerciseName": exercise,
        "weightValue": weight,
        "weightUnit": (
            {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0} if weight is not None else None
        ),
    }
    return step


def _fixture():
    """A 2-block strength workout resembling 'Man Cave - Monday'."""
    block_a = {
        "type": "RepeatGroupDTO",
        "stepId": 100,
        "stepType": {"stepTypeKey": "repeat"},
        "numberOfIterations": 4,
        "endConditionValue": 4.0,
        "workoutSteps": [
            _exec_step(101, 2, "interval", "reps", 4, "PULL_UP", None),
            _exec_step(102, 3, "rest", "time", 90),
            _exec_step(103, 4, "interval", "reps", 5, "KETTLEBELL_DEADLIFT", 24.0),
            _exec_step(104, 5, "rest", "time", 90),
        ],
    }
    block_b = {
        "type": "RepeatGroupDTO",
        "stepId": 200,
        "stepType": {"stepTypeKey": "repeat"},
        "numberOfIterations": 3,
        "endConditionValue": 3.0,
        "workoutSteps": [
            _exec_step(201, 12, "interval", "lap.button", 10, "FARMERS_CARRY", 24.0),
            _exec_step(202, 13, "rest", "time", 60),
        ],
    }
    return {
        "workoutId": 1647614440,
        "workoutName": "Man Cave - Monday",
        "sportType": {"sportTypeKey": "strength_training"},
        "workoutSegments": [{"segmentOrder": 1, "workoutSteps": [block_a, block_b]}],
    }


class TestSlimWorkout:
    def test_blocks_and_sets(self):
        slim = _slim_workout(_fixture())
        assert slim["workout_id"] == 1647614440
        assert slim["name"] == "Man Cave - Monday"
        assert slim["sport"] == "strength_training"
        assert len(slim["blocks"]) == 2
        assert slim["blocks"][0]["block_id"] == 100
        assert slim["blocks"][0]["sets"] == 4

    def test_exercise_step_projection(self):
        slim = _slim_workout(_fixture())
        deadlift = slim["blocks"][0]["steps"][2]
        assert deadlift == {
            "step_id": 103,
            "kind": "exercise",
            "exercise": "KETTLEBELL_DEADLIFT",
            "end_condition": "reps",
            "reps": 5,
            "weight_kg": 24.0,
        }

    def test_rest_step_projection(self):
        slim = _slim_workout(_fixture())
        rest = slim["blocks"][0]["steps"][1]
        assert rest == {"step_id": 102, "kind": "rest", "rest_s": 90}

    def test_bodyweight_move_has_null_weight(self):
        slim = _slim_workout(_fixture())
        pullup = slim["blocks"][0]["steps"][0]
        assert pullup["exercise"] == "PULL_UP"
        assert pullup["reps"] == 4
        assert pullup["weight_kg"] is None

    def test_lap_button_move_has_null_reps(self):
        slim = _slim_workout(_fixture())
        carry = slim["blocks"][1]["steps"][0]
        assert carry["exercise"] == "FARMERS_CARRY"
        assert carry["end_condition"] == "lap.button"
        assert carry["reps"] is None  # device-driven, not a rep count
        assert carry["weight_kg"] == 24.0


class TestApplyEdits:
    def test_change_reps(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"step_id": 103, "reps": 6}])
        assert not warnings
        assert applied == [
            {
                "op": "set",
                "step_id": 103,
                "exercise": "KETTLEBELL_DEADLIFT",
                "changes": [{"field": "reps", "old": 5, "new": 6}],
            }
        ]
        assert _slim_workout(raw)["blocks"][0]["steps"][2]["reps"] == 6

    def test_change_weight_and_reps_together(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"step_id": 103, "reps": 6, "weight_kg": 26}])
        assert not warnings
        fields = [c["field"] for c in applied[0]["changes"]]
        assert fields == ["reps", "weight_kg"]
        weight_change = applied[0]["changes"][1]
        assert weight_change == {"field": "weight_kg", "old": 24.0, "new": 26.0}
        step = _slim_workout(raw)["blocks"][0]["steps"][2]
        assert step["reps"] == 6
        assert step["weight_kg"] == 26.0

    def test_add_weight_to_bodyweight_move_stamps_unit(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"step_id": 101, "weight_kg": 5}])
        assert not warnings
        pullup = raw["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][0]
        assert pullup["weightValue"] == 5.0
        assert pullup["weightUnit"]["unitKey"] == "kilogram"

    def test_change_rest(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"step_id": 102, "rest_s": 120}])
        assert not warnings
        assert _slim_workout(raw)["blocks"][0]["steps"][1]["rest_s"] == 120

    def test_change_sets_updates_iterations_and_mirror(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"step_id": 100, "sets": 5}])
        assert not warnings
        assert applied[0]["exercise"] == "set-block"
        assert applied[0]["changes"] == [{"field": "sets", "old": 4, "new": 5}]
        block = raw["workoutSegments"][0]["workoutSteps"][0]
        assert block["numberOfIterations"] == 5
        assert block["endConditionValue"] == 5.0
        assert _slim_workout(raw)["blocks"][0]["sets"] == 5

    def test_reps_on_lap_button_rejected(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": 201, "reps": 15}])
        assert applied == []
        assert any("reps not editable" in w for w in warnings)

    def test_reps_on_lap_button_still_allows_weight(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": 201, "reps": 15, "weight_kg": 28}])
        assert applied == [
            {
                "op": "set",
                "step_id": 201,
                "exercise": "FARMERS_CARRY",
                "changes": [{"field": "weight_kg", "old": 24.0, "new": 28.0}],
            }
        ]
        assert any("reps not editable" in w for w in warnings)

    def test_sets_on_exercise_step_rejected(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": 103, "sets": 5}])
        assert applied == []
        assert any("only applies to a set-block" in w for w in warnings)

    def test_rest_on_exercise_step_rejected(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": 103, "rest_s": 30}])
        assert applied == []
        assert any("only applies to a rest step" in w for w in warnings)

    def test_unknown_step_id_warns(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": 999, "reps": 6}])
        assert applied == []
        assert any("unknown step_id: 999" in w for w in warnings)

    def test_string_step_id_coerced(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"step_id": "103", "reps": 7}])
        assert applied[0]["step_id"] == 103
        assert applied[0]["changes"] == [{"field": "reps", "old": 5, "new": 7}]
        assert not warnings


def _flat_orders(raw):
    """Collect stepOrder pre-order across the first segment."""
    orders = []

    def visit(s):
        orders.append(s["stepOrder"])
        for c in s.get("workoutSteps") or []:
            visit(c)

    for s in raw["workoutSegments"][0]["workoutSteps"]:
        visit(s)
    return orders


class TestStructuralOps:
    """Ops that use the real bundled catalog + typed builders (no network)."""

    def test_swap_exercise(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(
            raw, [{"op": "swap", "step_id": 103, "exercise": "Goblet Squat"}]
        )
        assert not warnings
        assert {
            "field": "exercise",
            "old": "KETTLEBELL_DEADLIFT",
            "new": "GOBLET_SQUAT",
        } in applied[0]["changes"]
        assert _slim_workout(raw)["blocks"][0]["steps"][2]["exercise"] == "GOBLET_SQUAT"

    def test_swap_can_also_set_numbers(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(
            raw, [{"op": "swap", "step_id": 103, "exercise": "Goblet Squat", "weight_kg": 20}]
        )
        fields = [c["field"] for c in applied[0]["changes"]]
        assert "exercise" in fields and "weight_kg" in fields

    def test_swap_unknown_exercise_warns(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(
            raw, [{"op": "swap", "step_id": 103, "exercise": "zzzz not a real move"}]
        )
        assert applied == []
        assert any("unknown exercise" in w for w in warnings)

    def test_swap_on_rest_rejected(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(
            raw, [{"op": "swap", "step_id": 102, "exercise": "Goblet Squat"}]
        )
        assert applied == []
        assert any("exercise swap only applies" in w for w in warnings)

    def test_remove_exercise_drops_trailing_rest(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"op": "remove", "step_id": 103}])
        assert applied[0]["removed"] == ["KETTLEBELL_DEADLIFT", "rest"]
        # block 100 now has only PULL_UP + its rest
        steps = _slim_workout(raw)["blocks"][0]["steps"]
        assert [s.get("exercise") for s in steps if s["kind"] == "exercise"] == ["PULL_UP"]

    def test_remove_block_by_id(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(raw, [{"op": "remove", "step_id": 200}])
        blocks = _slim_workout(raw)["blocks"]
        assert len(blocks) == 1
        assert blocks[0]["block_id"] == 100

    def test_removing_only_exercise_prunes_block(self):
        raw = _fixture()
        # block 200 holds only FARMERS_CARRY (201); removing it empties the block
        raw, applied, warnings = _apply_edits(raw, [{"op": "remove", "step_id": 201}])
        blocks = _slim_workout(raw)["blocks"]
        assert len(blocks) == 1  # block 200 pruned

    def test_add_exercise_into_block(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(
            raw,
            [
                {
                    "op": "add_exercise",
                    "block_id": 100,
                    "exercise": "Goblet Squat",
                    "reps": 10,
                    "weight_kg": 20,
                    "rest_s": 60,
                }
            ],
        )
        assert not warnings
        assert applied[0]["op"] == "add_exercise"
        block = _slim_workout(raw)["blocks"][0]
        exs = [s for s in block["steps"] if s["kind"] == "exercise"]
        assert exs[-1]["exercise"] == "GOBLET_SQUAT"
        assert exs[-1]["reps"] == 10
        assert exs[-1]["weight_kg"] == 20.0

    def test_add_exercise_unknown_block_warns(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(
            raw, [{"op": "add_exercise", "block_id": 999, "exercise": "Goblet Squat", "reps": 10}]
        )
        assert applied == []
        assert any("unknown block_id" in w for w in warnings)

    def test_add_block(self):
        raw = _fixture()
        raw, applied, warnings = _apply_edits(
            raw,
            [{"op": "add_block", "exercise": "Plank", "sets": 3, "reps": 30, "rest_s": 45}],
        )
        assert not warnings
        blocks = _slim_workout(raw)["blocks"]
        assert len(blocks) == 3
        assert blocks[-1]["sets"] == 3
        assert blocks[-1]["steps"][0]["exercise"] == "PLANK"

    def test_add_block_requires_reps_and_sets(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(
            raw, [{"op": "add_block", "exercise": "Plank", "sets": 3}]
        )
        assert applied == []
        assert any("reps is required" in w for w in warnings)

    def test_unknown_op_warns(self):
        raw = _fixture()
        _, applied, warnings = _apply_edits(raw, [{"op": "explode", "step_id": 103}])
        assert applied == []
        assert any("unknown op: explode" in w for w in warnings)

    def test_steporder_renumbered_after_add(self):
        raw = _fixture()
        raw, _, _ = _apply_edits(
            raw, [{"op": "add_block", "exercise": "Plank", "sets": 2, "reps": 30}]
        )
        orders = _flat_orders(raw)
        assert orders == list(range(1, len(orders) + 1))


class TestSearchExercises:
    def test_search_returns_matches(self):
        result = json.loads(
            garmin_workout.invoke({"action": "search_exercises", "query": "goblet squat"})
        )
        assert result["count"] >= 1
        codes = [r["exercise"] for r in result["results"]]
        assert "GOBLET_SQUAT" in codes

    def test_search_requires_query(self):
        result = json.loads(garmin_workout.invoke({"action": "search_exercises"}))
        assert "query is required" in result["error"]

    def test_search_caps_results(self):
        result = json.loads(garmin_workout.invoke({"action": "search_exercises", "query": "squat"}))
        assert len(result["results"]) <= 15


def _mock_client_calls(fixture):
    """Return a _safe_api_call side_effect over a mutable stored workout."""
    store = {"raw": copy.deepcopy(fixture)}

    def side_effect(garmin, method_name, *args, **kwargs):
        if method_name == "get_workouts":
            return [fixture]
        if method_name == "get_workout_by_id":
            return copy.deepcopy(store["raw"])
        if method_name == "update_workout":
            store["raw"] = args[1]
            return {"workoutId": args[0]}
        raise AssertionError(f"unexpected method {method_name}")

    return side_effect, store


class TestToolDispatch:
    def test_not_connected(self):
        with patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=None):
            result = json.loads(garmin_workout.invoke({"action": "list"}))
        assert result["error"] == "Garmin not connected"

    def test_unknown_action(self):
        with patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()):
            result = json.loads(garmin_workout.invoke({"action": "fly"}))
        assert "Unknown action" in result["error"]

    def test_list(self):
        side_effect, _ = _mock_client_calls(_fixture())
        with (
            patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin_workout._safe_api_call", side_effect=side_effect),
        ):
            result = json.loads(garmin_workout.invoke({"action": "list"}))
        assert result["count"] == 1
        assert result["workouts"][0]["name"] == "Man Cave - Monday"

    def test_get_requires_workout_id(self):
        with patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()):
            result = json.loads(garmin_workout.invoke({"action": "get"}))
        assert "workout_id is required" in result["error"]

    def test_get_returns_slim_view(self):
        side_effect, _ = _mock_client_calls(_fixture())
        with (
            patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin_workout._safe_api_call", side_effect=side_effect),
        ):
            result = json.loads(
                garmin_workout.invoke({"action": "get", "workout_id": "1647614440"})
            )
        assert result["workout"]["name"] == "Man Cave - Monday"
        assert len(result["workout"]["blocks"]) == 2

    def test_update_persists_and_returns_refreshed(self):
        side_effect, store = _mock_client_calls(_fixture())
        with (
            patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin_workout._safe_api_call", side_effect=side_effect),
        ):
            result = json.loads(
                garmin_workout.invoke(
                    {
                        "action": "update",
                        "workout_id": "1647614440",
                        "edits": '[{"step_id": 103, "weight_kg": 26}]',
                    }
                )
            )
        assert result["applied"] == [
            {
                "op": "set",
                "step_id": 103,
                "exercise": "KETTLEBELL_DEADLIFT",
                "changes": [{"field": "weight_kg", "old": 24.0, "new": 26.0}],
            }
        ]
        # Persisted store reflects the change, and the returned view echoes it.
        assert result["workout"]["blocks"][0]["steps"][2]["weight_kg"] == 26.0

    def test_update_accepts_json_string_edits(self):
        side_effect, _ = _mock_client_calls(_fixture())
        with (
            patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin_workout._safe_api_call", side_effect=side_effect),
        ):
            result = json.loads(
                garmin_workout.invoke(
                    {
                        "action": "update",
                        "workout_id": "1647614440",
                        "edits": '[{"step_id": 102, "rest_s": 120}]',
                    }
                )
            )
        assert result["applied"] == [
            {
                "op": "set",
                "step_id": 102,
                "exercise": "rest",
                "changes": [{"field": "rest_s", "old": 90, "new": 120}],
            }
        ]

    def test_update_requires_edits(self):
        with patch("src.agent.tools.garmin_workout._get_garmin_client", return_value=MagicMock()):
            result = json.loads(
                garmin_workout.invoke({"action": "update", "workout_id": "1647614440"})
            )
        assert "edits is required" in result["error"]


class TestToolSchema:
    """Guards the tool's parameter schema stays convertible to a Gemini function.

    A parameter typed ``Any`` yields a schema with no ``type``/``anyOf``, which
    some langchain_google_genai versions reject at bind time — breaking EVERY
    chat that binds this tool, not just sports. This regression test catches
    that class of bug (which .invoke()-based tests miss, since they never run
    the genai schema conversion).
    """

    def test_every_param_has_a_concrete_type(self):
        for name, schema in garmin_workout.args.items():
            assert "type" in schema or "anyOf" in schema, (
                f"param {name!r} has no concrete type (schema={schema}); "
                "an Any-typed param breaks Gemini schema conversion"
            )

    def test_converts_to_genai_declaration(self):
        # Best-effort: on versions where the conversion is available, it must
        # not raise for this tool's schema.
        try:
            from langchain_google_genai._function_utils import (
                convert_to_genai_function_declarations,
            )
        except Exception:
            return
        convert_to_genai_function_declarations([garmin_workout])
