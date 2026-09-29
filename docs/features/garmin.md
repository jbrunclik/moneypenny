# Garmin Connect Integration

The assistant can query the user's health, fitness, and training data from Garmin Connect, and edit the user's saved strength workouts. Two LangGraph tools back this: `garmin_connect` (read-only health/activity data) and `garmin_workout` (read/write access to saved workouts).

## Overview

1. **Auth Method**: Email/password login via `garminconnect`/`garth` library (not OAuth)
2. **Password Never Stored**: Only serialized garth session tokens (OAuth1 + OAuth2) are persisted; tokens are valid ~1 year
3. **MFA Support**: If the account has MFA enabled, a two-step flow is used (connect → mfa)
4. **Tool Availability**: Both `garmin_connect` and `garmin_workout` are bound whenever the `garminconnect` package is installed (`is_garmin_available()`); for a user without a working connection they return the shared not-connected / disconnected result (see [Integrations](integrations.md#not-connected-results))
5. **Session Cache**: Building a client costs two extra Garmin round trips, so [garmin_session.py](../../src/agent/tools/garmin_session.py) caches it per user for `GARMIN_SESSION_TTL_SECONDS` (default 900), keyed by a fingerprint of the stored token so a reconnect invalidates every worker's copy
6. **Token Refresh**: Tokens are automatically re-serialized after API calls in case garth refreshed them

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/garmin/connect` | POST | Authenticate with email/password; returns `mfa_required=True` if MFA is needed |
| `/auth/garmin/mfa` | POST | Complete MFA login with verification code (OTP from email or authenticator) |
| `/auth/garmin/disconnect` | POST | Remove stored tokens |
| `/auth/garmin/status` | GET | Report connection status (connected, connected_at, needs_reconnect) |

## Garmin Connect Tool Actions

The `garmin_connect` tool is read-only and exposes the following actions:

| Action | Parameters | Description |
|--------|------------|-------------|
| `get_readiness_snapshot` | `date_str`, `limit` (optional) | **Preferred** composite: training readiness, sleep, HRV, daily stats, training status and recent activities in one call (sections a device lacks come back as `{"error": ...}`) |
| `get_stats` | `date_str` (optional) | Daily summary: steps, distance, calories, floors, active minutes |
| `get_heart_rates` | `date_str` (optional) | Resting HR, HR zones, min/max for a day |
| `get_sleep_data` | `date_str` (optional) | Sleep quality, stages (deep/light/REM/awake), duration |
| `get_stress_data` | `date_str` (optional) | Stress levels throughout the day |
| `get_hrv_data` | `date_str` (optional) | Heart rate variability data |
| `get_spo2_data` | `date_str` (optional) | Blood oxygen (SpO2) readings |
| `get_body_composition` | `date_str` (optional) | Weight, body fat %, BMI, muscle mass |
| `get_activities` | `limit` (optional), `activity_type` (optional) | List recent activities (last 90 days, default 10) |
| `get_activity_details` | `activity_id` (required) | Detailed data for one activity, incl. `exercise_sets` (per-set reps/`weight_kg`), `hr_zones`, `laps` |
| `get_training_readiness` | `date_str` (optional) | Training readiness score and contributing factors |
| `get_training_status` | `date_str` (optional) | Training status and load metrics |
| `get_steps` | `date_str` (optional) | Step count and daily goal |
| `get_courses` | `activity_type` (optional) | List saved courses/routes: `{course_id, name, activity_type, distance_km, elevation_gain_m, elevation_loss_m}`. `activity_type` is a substring filter (e.g. `"cycling"`). |
| `get_course_details` | `course_id` (required) | One course's profile: distance, exact elevation gain/loss, min/max elevation, a compact altitude `profile` (~32 samples), and derived `climbs` (start_km / length_km / gain_m / avg & max grade). |

All date parameters default to today. `date_str` format: `YYYY-MM-DD`.

> **Courses (routes).** Saved courses live in Garmin's `course-service`, which
> the `garminconnect` library does not wrap, so the tool calls the raw endpoints
> via `connectapi` (`/course-service/course` and `/course-service/course/{id}`).
> A course's raw `geoPoints` run to thousands of points — `get_course_details`
> downsamples the altitude profile to ~32 samples and never returns the raw
> track. Garmin exposes no climb API (its own "N Climbs" list is computed
> client-side), so `climbs` are **derived** from the profile (sustained-ascent
> detection); the distance and elevation gain/loss totals are Garmin's exact
> values.

> **Weight units:** `get_activity_details` → `exercise_sets` reports weight in **kilograms** (`weight_kg`). The raw Garmin activity endpoint stores weight in grams (e.g. `24000` for 24 kg); `_slim_exercise_set` divides by 1000 so the whole agent surface is consistent with `garmin_workout` (see the gotchas below).

## Garmin Workout Editing (`garmin_workout` tool)

Unlike `garmin_connect`, this tool **writes** back to Garmin. It lets the agent keep the targets shown on the watch accurate before a session and evolve the program over time. Edits are applied in place via `update_workout` (HTTP PUT), so a workout keeps its id and any calendar schedule.

The raw Garmin workout JSON is deeply nested (repeat groups of interval/rest steps). The tool never hands that to the LLM: `_slim_workout` projects it to a compact view keyed by `step_id`, and `_apply_edits` maps step-id-keyed edit ops back onto the raw tree before PUTting it.

| Action | Parameters | Description |
|--------|------------|-------------|
| `list` | – | List all saved workouts as `{workout_id, name, sport}` |
| `get` | `workout_id` (required) | Compact editable view: `{name, blocks: [{block_id, sets, steps: [...]}]}`. Each step has a `step_id`. |
| `search_exercises` | `query` (required) | Fuzzy lookup over Garmin's bundled exercise catalog (~1500 exercises); returns `{name, category, exercise}` |
| `update` | `workout_id`, `edits` (required) | Apply edit ops, then return `{applied, warnings, workout: <refreshed view>}` |

`edits` is a **JSON-encoded array string** of ops (each has an `op`, default `"set"`):

```jsonc
[
  {"step_id": 12, "reps": 6, "weight_kg": 26},                 // set numbers on a step
  {"step_id": 13, "rest_s": 120},                              // set rest (rest step id)
  {"step_id": 10, "sets": 5},                                  // set sets (set-block id)
  {"op": "swap", "step_id": 12, "exercise": "Goblet Squat"},   // change the movement
  {"op": "add_exercise", "block_id": 10, "exercise": "Bulgarian Split Squat", "reps": 10, "weight_kg": 12, "rest_s": 75},
  {"op": "add_block", "exercise": "Plank", "sets": 3, "reps": 45, "rest_s": 30},
  {"op": "remove", "step_id": 12}                              // step (drops its rest) or a block id
]
```

### Workout JSON structure

`workoutSegments[0].workoutSteps[]` is a list of `RepeatGroupDTO` set-blocks (a block may hold several exercises — a superset). Each block:
- `numberOfIterations` = number of **sets** (mirror it into the block's `endConditionValue`).
- Child `ExecutableStepDTO`s alternate `stepType=interval` (an exercise: `endCondition=reps`→`endConditionValue`, `weightValue`+`weightUnit`) and `stepType=rest` (`endCondition=time`→`endConditionValue` seconds).
- Carries use `endCondition=lap.button`, not `reps` — reps aren't editable there, only weight.

### Implementation gotchas

- **Weight is in kilograms on the workout endpoint** (`weightValue: 24.0` == 24 kg) — *different* from the activity endpoint, which uses grams. `garmin_workout` writes `weightValue` in kg directly. The `garminconnect.workout` typed builders multiply kg×1000 (grams), which is wrong here, so new steps are built with `weight_kg=None` and their `weightValue` is set in kg afterward.
- **Garmin reassigns every `stepId` on save** (PUT/POST). Ids from a `get` are stale after any `update`. The tool re-fetches inside `update` (ids still valid there), but callers must re-`get` before a *second* edit. The `update` response describes changes as `{op, exercise, changes:[{field, old, new}]}` rather than by stale id.
- **New steps use the typed builders** (`garminconnect.workout.create_strength_set` etc.); after structural ops the tool prunes empty blocks and renumbers `stepOrder` as a clean 1..N pre-order.
- **Exercise names are validated against the bundled catalog** (`garminconnect.exercises`: `find()` fuzzy, `resolve()` exact). A workout step needs `category` = catalog category and `exerciseName` = catalog exercise. Unknown names are rejected with a warning.
- **Garmin has no RPE field** — RPE can't be pushed to the watch. The sports agent keeps RPE in its `kv_store` and translates it into a concrete weight/rep target here.
- **Tool-parameter typing:** the `edits` param is typed `str | None` (a JSON string), *not* `Any`. An `Any`-typed tool param produces a schema with no `type`, which some `langchain_google_genai` versions reject when converting to a Gemini function declaration — and because the tool is bound on every request, that breaks *all* chat. `tests/unit/test_garmin_workout_tool.py::TestToolSchema` guards against this.

## Configuration

```bash
# .env
GARMIN_API_TIMEOUT=15            # API request timeout in seconds (default: 15)
GARMIN_SESSION_TTL_SECONDS=900   # How long a cached client session lives (default: 900)
```

No client ID or secret is required — the user authenticates with their own Garmin credentials.

## Key Files

**Backend:**
- [config.py](../../src/config.py) - `GARMIN_API_TIMEOUT`, `GARMIN_SESSION_TTL_SECONDS`
- [garmin_auth.py](../../src/auth/garmin_auth.py) - Authentication helpers (login, MFA, token serialization)
- [tools/garmin.py](../../src/agent/tools/garmin.py) - `garmin_connect` read-only LangGraph tool
- [tools/garmin_workout.py](../../src/agent/tools/garmin_workout.py) - `garmin_workout` read/write workout-editing tool
- [tools/garmin_session.py](../../src/agent/tools/garmin_session.py) - per-user cached client sessions
- [routes/garmin.py](../../src/api/routes/garmin.py) - Auth endpoints
- [migrations/0028_add_garmin_fields.py](../../migrations/0028_add_garmin_fields.py) - Database schema

**Frontend:**
- [settings/garmin.ts](../../web/src/components/settings/garmin.ts) - Connection UI (email/password form, MFA step)
- [api/integrations.ts](../../web/src/api/integrations.ts) - API methods
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [popups.css](../../web/src/styles/components/popups.css) - Styles

## Testing

- Unit tests: [test_garmin_tool.py](../../tests/unit/test_garmin_tool.py), [test_garmin_workout_tool.py](../../tests/unit/test_garmin_workout_tool.py) (incl. `TestToolSchema`), [test_garmin_auth.py](../../tests/unit/test_garmin_auth.py)
- Integration tests: [test_routes_garmin.py](../../tests/integration/test_routes_garmin.py)

## See Also

- [Integrations](integrations.md) - all integrations and the shared not-connected messaging
- [Rouvy](rouvy.md) - the other sports integration (indoor-cycling workouts)
- [Setup](../setup.md) - connecting Garmin
