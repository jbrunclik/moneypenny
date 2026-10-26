"""Garmin strength workouts as the agent sees and edits them.

`slim_workout` projects Garmin's deeply nested workout JSON (repeat groups of
interval/rest steps) to a compact view keyed by ``step_id``; `apply_edits`
maps step-id-keyed edit ops back onto the raw tree, building new steps with
the library's typed builders and validating exercise names against the
bundled Garmin catalog. Weights are kilograms throughout.
"""

import json
from typing import Any, NamedTuple

# Garmin expresses this account's strength weights in kilograms. When we set a
# weight on a step that had none (e.g. adding load to a bodyweight move) we
# stamp this unit so the device renders it correctly.
_KG_UNIT = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}


def _to_int(value: Any) -> int | None:
    """Coerce a Garmin numeric (often a float like 4.0) to int, else None."""
    return int(value) if isinstance(value, int | float) else None


def _slim_exec_step(step: dict[str, Any]) -> dict[str, Any]:
    """Project one ExecutableStepDTO to a compact, editable entry.

    Rest steps expose ``rest_s``; working steps expose the exercise, its rep
    scheme, and weight. ``end_condition`` tells the agent whether ``reps`` is a
    real editable rep count ("reps") or device-driven ("lap.button"/"time"),
    in which case reps cannot be set and only weight is meaningful.
    """
    step_kind = (step.get("stepType") or {}).get("stepTypeKey")
    end = step.get("endCondition") or {}
    end_key = end.get("conditionTypeKey")

    if step_kind == "rest":
        return {
            "step_id": step.get("stepId"),
            "kind": "rest",
            "rest_s": _to_int(step.get("endConditionValue")),
        }

    weight = step.get("weightValue")
    return {
        "step_id": step.get("stepId"),
        "kind": "exercise",
        "exercise": step.get("exerciseName") or step.get("category"),
        "end_condition": end_key,
        "reps": _to_int(step.get("endConditionValue")) if end_key == "reps" else None,
        "weight_kg": round(weight, 1) if isinstance(weight, int | float) else None,
    }


def _slim_block(repeat: dict[str, Any]) -> dict[str, Any]:
    """Project a RepeatGroupDTO to a block: sets + its child steps."""
    return {
        "block_id": repeat.get("stepId"),
        "sets": _to_int(repeat.get("numberOfIterations")),
        "steps": [
            _slim_exec_step(s) for s in (repeat.get("workoutSteps") or []) if isinstance(s, dict)
        ],
    }


def slim_workout(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a full Garmin workout to the compact editable view.

    Every top-level step is either a RepeatGroupDTO (a set-block, possibly a
    superset of several exercises) or a standalone ExecutableStepDTO, which we
    present as a one-set block for a uniform editing model.
    """
    blocks: list[dict[str, Any]] = []
    for seg in raw.get("workoutSegments") or []:
        for step in seg.get("workoutSteps") or []:
            if not isinstance(step, dict):
                continue
            if step.get("type") == "RepeatGroupDTO":
                blocks.append(_slim_block(step))
            elif step.get("type") == "ExecutableStepDTO":
                blocks.append({"block_id": None, "sets": 1, "steps": [_slim_exec_step(step)]})
    return {
        "workout_id": raw.get("workoutId"),
        "name": raw.get("workoutName"),
        "sport": (raw.get("sportType") or {}).get("sportTypeKey"),
        "blocks": blocks,
    }


def _coerce_id(val: Any) -> int | None:
    """Coerce a step_id/block_id (possibly a string) to int, else None."""
    try:
        return int(val) if val is not None else None
    except TypeError, ValueError:
        return None


def _index_with_parents(raw: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Map every stepId to {node, parent} where parent is the list holding it.

    The parent list is what add/remove operations mutate. Both repeat groups
    and executable steps are indexed.
    """
    index: dict[int, dict[str, Any]] = {}

    def visit(step: dict[str, Any], parent: list[Any]) -> None:
        sid = step.get("stepId")
        if isinstance(sid, int):
            index[sid] = {"node": step, "parent": parent}
        kids = step.get("workoutSteps")
        if isinstance(kids, list):
            for child in kids:
                if isinstance(child, dict):
                    visit(child, kids)

    for seg in raw.get("workoutSegments") or []:
        top = seg.get("workoutSteps") or []
        for step in top:
            if isinstance(step, dict):
                visit(step, top)
    return index


def _step_label(step: dict[str, Any]) -> str:
    """A human-readable name for a raw step, for the change record."""
    if step.get("type") == "RepeatGroupDTO":
        return "set-block"
    if (step.get("stepType") or {}).get("stepTypeKey") == "rest":
        return "rest"
    return step.get("exerciseName") or step.get("category") or "exercise"


def _resolve_exercise(term: Any) -> dict[str, str] | None:
    """Resolve a display name / fuzzy term / code to a catalog {name, category, exercise}."""
    if not isinstance(term, str) or not term.strip():
        return None
    from garminconnect.exercises import EXERCISES, find, resolve  # noqa: PLC0415 - optional dependency (see is_garmin_available)

    found: dict[str, str] | None = resolve(term)
    if found:
        return dict(found)
    hits = find(term)
    if hits:
        return dict(hits[0])
    code = term.strip().upper().replace(" ", "_").replace("-", "_")
    for entry in EXERCISES:
        if entry["exercise"] == code:
            return dict(entry)
    return None


def _new_block(
    entry: dict[str, str], sets: int, reps: int, rest_s: float, weight_kg: float | None
) -> dict[str, Any]:
    """Build a new RepeatGroupDTO (one exercise + rest) via the library builder.

    The builder stores weight as grams (kg*1000); the workout endpoint wants kg
    (24.0 == 24 kg, per the user's own workouts), so we overwrite weightValue in
    kg to match every other step.
    """
    from garminconnect import workout as gw  # noqa: PLC0415 - optional dependency (see is_garmin_available)

    grp: dict[str, Any] = gw.create_strength_set(
        category=entry["category"],
        step_order=0,
        sets=int(sets),
        reps=int(reps),
        rest_seconds=float(rest_s),
        exercise_name=entry["exercise"],
        weight_kg=None,
    ).model_dump()
    if weight_kg is not None:
        for child in grp.get("workoutSteps") or []:
            if (child.get("stepType") or {}).get("stepTypeKey") == "interval":
                child["weightValue"] = float(weight_kg)
                child["weightUnit"] = dict(_KG_UNIT)
    return grp


def _new_exercise_and_rest(
    entry: dict[str, str], reps: int, rest_s: float, weight_kg: float | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (exercise_step, rest_step) dicts to splice into an existing block."""
    grp = _new_block(entry, 1, reps, rest_s, weight_kg)
    steps = grp["workoutSteps"]
    return steps[0], steps[1]


def _prune_empty_blocks(raw: dict[str, Any]) -> None:
    """Drop any set-block left with no exercise (interval) step after removals."""
    for seg in raw.get("workoutSegments") or []:
        steps = seg.get("workoutSteps")
        if not isinstance(steps, list):
            continue
        seg["workoutSteps"] = [
            s
            for s in steps
            if s.get("type") != "RepeatGroupDTO"
            or any(
                (c.get("stepType") or {}).get("stepTypeKey") == "interval"
                for c in s.get("workoutSteps") or []
            )
        ]


def _renumber(raw: dict[str, Any]) -> None:
    """Reassign stepOrder as a clean 1..N pre-order sequence across the segment."""
    counter = [0]

    def visit(step: dict[str, Any]) -> None:
        counter[0] += 1
        step["stepOrder"] = counter[0]
        for child in step.get("workoutSteps") or []:
            visit(child)

    for seg in raw.get("workoutSegments") or []:
        for step in seg.get("workoutSteps") or []:
            visit(step)


class _StepShape(NamedTuple):
    """What decides which edits fit a raw step."""

    sid: Any
    is_repeat: bool
    end_key: str | None
    kind: str | None


# (change, warning) for one requested field - exactly one is set
_FieldEdit = tuple[dict[str, Any] | None, str | None]


def _edit_exercise(step: dict[str, Any], value: Any, shape: _StepShape) -> _FieldEdit:
    if shape.is_repeat or shape.kind != "interval":
        return None, f"step {shape.sid}: exercise swap only applies to an exercise step"
    entry = _resolve_exercise(value)
    if not entry:
        return None, f"step {shape.sid}: unknown exercise {value!r}"
    old = step.get("exerciseName") or step.get("category")
    step["category"] = entry["category"]
    step["exerciseName"] = entry["exercise"]
    return {"field": "exercise", "old": old, "new": entry["exercise"]}, None


def _edit_sets(step: dict[str, Any], value: Any, shape: _StepShape) -> _FieldEdit:
    if not shape.is_repeat:
        return None, f"step {shape.sid}: 'sets' only applies to a set-block"
    old = _to_int(step.get("numberOfIterations"))
    step["numberOfIterations"] = int(value)
    step["endConditionValue"] = float(value)
    return {"field": "sets", "old": old, "new": int(value)}, None


def _edit_reps(step: dict[str, Any], value: Any, shape: _StepShape) -> _FieldEdit:
    if shape.is_repeat or shape.end_key != "reps":
        return None, f"step {shape.sid}: reps not editable (end_condition={shape.end_key or 'n/a'})"
    old = _to_int(step.get("endConditionValue"))
    step["endConditionValue"] = float(value)
    return {"field": "reps", "old": old, "new": int(value)}, None


def _edit_weight(step: dict[str, Any], value: Any, shape: _StepShape) -> _FieldEdit:
    if shape.is_repeat or shape.kind == "rest":
        return None, f"step {shape.sid}: weight not applicable"
    old = step.get("weightValue")
    old = round(old, 1) if isinstance(old, int | float) else None
    step["weightValue"] = float(value)
    step["weightUnit"] = dict(_KG_UNIT)
    return {"field": "weight_kg", "old": old, "new": float(value)}, None


def _edit_rest(step: dict[str, Any], value: Any, shape: _StepShape) -> _FieldEdit:
    if shape.kind != "rest" or shape.end_key != "time":
        return None, f"step {shape.sid}: rest_s only applies to a rest step"
    old = _to_int(step.get("endConditionValue"))
    step["endConditionValue"] = float(value)
    return {"field": "rest_s", "old": old, "new": int(value)}, None


# Editable fields in the order they are applied
_FIELD_EDITORS = (
    ("exercise", _edit_exercise),
    ("sets", _edit_sets),
    ("reps", _edit_reps),
    ("weight_kg", _edit_weight),
    ("rest_s", _edit_rest),
)


def _apply_one_edit(
    step: dict[str, Any], edit: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Apply an in-place edit (numbers and/or exercise swap) to one raw node.

    Returns (changes, warnings) where each change is {field, old, new} captured
    around the mutation. A requested field is either applied (recorded as a
    change) or rejected with a warning explaining why it doesn't fit this step.
    """
    changes: list[dict[str, Any]] = []
    warnings: list[str] = []
    shape = _StepShape(
        sid=step.get("stepId"),
        is_repeat=step.get("type") == "RepeatGroupDTO",
        end_key=(step.get("endCondition") or {}).get("conditionTypeKey"),
        kind=(step.get("stepType") or {}).get("stepTypeKey"),
    )
    for field, editor in _FIELD_EDITORS:
        if edit.get(field) is None:
            continue
        change, warning = editor(step, edit[field], shape)
        if change:
            changes.append(change)
        if warning:
            warnings.append(warning)
    return changes, warnings


def _op_set(index: dict[int, dict[str, Any]], op: dict[str, Any]) -> tuple[Any, list[str]]:
    """In-place edit (numbers and/or exercise swap) of an existing step."""
    sid = _coerce_id(op.get("step_id"))
    entry = index.get(sid) if sid is not None else None
    if not entry:
        return None, [f"unknown step_id: {op.get('step_id')}"]
    node = entry["node"]
    label = _step_label(node)
    changes, warnings = _apply_one_edit(node, op)
    if changes:
        return {"op": "set", "step_id": sid, "exercise": label, "changes": changes}, warnings
    return None, warnings


def _op_remove(index: dict[int, dict[str, Any]], op: dict[str, Any]) -> tuple[Any, list[str]]:
    """Remove a step (an exercise drops its trailing rest) or a whole set-block."""
    sid = _coerce_id(op.get("step_id"))
    entry = index.get(sid) if sid is not None else None
    if not entry:
        return None, [f"unknown step_id: {op.get('step_id')}"]
    node, parent = entry["node"], entry["parent"]
    label = _step_label(node)
    if node not in parent:
        return None, [f"step {sid}: already removed"]
    pos = parent.index(node)
    parent.pop(pos)
    removed = [label]
    is_interval = (node.get("stepType") or {}).get("stepTypeKey") == "interval"
    if is_interval and pos < len(parent):
        nxt = parent[pos]
        if (nxt.get("stepType") or {}).get("stepTypeKey") == "rest":
            parent.pop(pos)
            removed.append("rest")
    return {"op": "remove", "step_id": sid, "exercise": label, "removed": removed}, []


def _op_add(
    index: dict[int, dict[str, Any]],
    seg_steps: list[Any],
    op: dict[str, Any],
    kind: str,
) -> tuple[Any, list[str]]:
    """Add an exercise into an existing block, or a new set-block to the workout."""
    entry = _resolve_exercise(op.get("exercise"))
    if not entry:
        return None, [f"{kind}: unknown exercise {op.get('exercise')!r}"]
    reps = op.get("reps")
    if reps is None:
        return None, [f"{kind}: reps is required"]
    rest_s = op.get("rest_s", 90)
    weight_kg = op.get("weight_kg")

    if kind == "add_exercise":
        block_id = _coerce_id(op.get("block_id"))
        target = index.get(block_id) if block_id is not None else None
        if not target or target["node"].get("type") != "RepeatGroupDTO":
            return None, [f"add_exercise: unknown block_id {op.get('block_id')}"]
        ex_step, rest_step = _new_exercise_and_rest(entry, reps, rest_s, weight_kg)
        target["node"].setdefault("workoutSteps", []).extend([ex_step, rest_step])
        return {
            "op": "add_exercise",
            "exercise": entry["exercise"],
            "into_block": block_id,
            "reps": int(reps),
            "weight_kg": weight_kg,
            "rest_s": int(rest_s),
        }, []

    sets = op.get("sets")
    if sets is None:
        return None, ["add_block: sets is required"]
    seg_steps.append(_new_block(entry, sets, reps, rest_s, weight_kg))
    return {
        "op": "add_block",
        "exercise": entry["exercise"],
        "sets": int(sets),
        "reps": int(reps),
        "weight_kg": weight_kg,
        "rest_s": int(rest_s),
    }, []


def apply_edits(
    raw: dict[str, Any], edits: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Apply a list of edit ops onto the raw workout tree (mutates ``raw``).

    Each op has an ``op`` key (defaulting to "set"):
    - "set"/"swap": edit an existing step by step_id (reps/weight_kg/rest_s/sets
      and/or exercise swap).
    - "remove": delete a step (an exercise drops its trailing rest) or a block.
    - "add_exercise": add an exercise (+rest) into an existing block_id.
    - "add_block": append a new set-block (one exercise) to the workout.

    Returns (raw, applied, warnings). ``applied`` is a self-contained record of
    what changed, for confirming to the user. Bad ids / mismatches become
    warnings rather than raising, so valid ops still land. After all ops, empty
    blocks are pruned and stepOrder is renumbered.

    Note: Garmin reassigns every stepId on save, so ids the caller edited by are
    stale once the workout is PUT — re-``get`` before another edit.
    """
    index = _index_with_parents(raw)
    segments = raw.get("workoutSegments") or []
    seg_steps = segments[0]["workoutSteps"] if segments else []
    applied: list[dict[str, Any]] = []
    warnings: list[str] = []

    for op in edits:
        kind = str(op.get("op") or "set").lower()
        if kind in ("set", "swap"):
            record, op_warnings = _op_set(index, op)
        elif kind == "remove":
            record, op_warnings = _op_remove(index, op)
        elif kind in ("add_exercise", "add_block"):
            record, op_warnings = _op_add(index, seg_steps, op, kind)
        else:
            record, op_warnings = None, [f"unknown op: {kind}"]
        warnings.extend(op_warnings)
        if record:
            applied.append(record)

    _prune_empty_blocks(raw)
    _renumber(raw)
    return raw, applied, warnings


def parse_edits(edits: Any) -> list[dict[str, Any]]:
    """Accept edits as a JSON string or a list; normalize to a list of dicts."""
    if isinstance(edits, str):
        edits = json.loads(edits)
    if isinstance(edits, dict):
        edits = [edits]
    if not isinstance(edits, list):
        raise ValueError("edits must be a JSON array of edit objects")
    return [e for e in edits if isinstance(e, dict)]
