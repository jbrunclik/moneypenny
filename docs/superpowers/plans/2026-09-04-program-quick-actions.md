# Program Quick Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-tap, per-program saved prompts (with optional fields appended as `Label: value` lines) in sports and language program conversations, editable per program, on desktop and mobile.

**Architecture:** Quick actions are stored inside each program object in the existing `programs` KV list (never under the `{program_id}:` prefix, which is injected into the prompt every turn). The shared program route factory gains one `PUT .../quick-actions` endpoint and returns `quick_actions` on every program item. The frontend gets a chip bar above the composer (mounted only in program conversations), a field form (bottom sheet on mobile, popover on desktop), an editor modal, and a "Save as quick action" message action. Sending composes an ordinary user message and reuses `sendMessage()`.

**Tech Stack:** Flask + apiflask + Pydantic (backend), Vite + TypeScript + Zustand (frontend), pytest, vitest (jsdom), Playwright.

**Spec:** `docs/superpowers/specs/2026-09-04-program-quick-actions-design.md`

## Global Constraints

- Limits (server-validated): ≤ 12 actions per program, label ≤ 40 chars, body ≤ 2000 chars, ≤ 6 fields, field label ≤ 40 chars, emoji 1–10 chars.
- Message format: body, blank line, then `Label: value` per non-empty field; multi-line values indent continuation lines with two spaces; all-empty → body only.
- Quick actions must NOT be stored under `{program_id}:*` in KV.
- No new message type; sends go through `sendMessage()` in `web/src/core/messaging.ts`.
- Mobile (≤ 768 px): bar visible only when the composer textarea is empty and no reply is streaming; desktop: always visible in program conversations, chips disabled while streaming.
- Transitions are opacity/transform only, never animated height.
- Never hand-edit `web/src/types/generated-api.ts` or `static/openapi.json`; run `make openapi && make types`.
- Check exit codes directly; never pipe `make lint`/`pytest` through `grep`/`tail` in `&&` chains.
- After any frontend change, `make build` before running Playwright (E2E serves `static/assets/`).
- Auto-format hook runs `ruff format`/`eslint --fix` after every edit; re-read a file before a second edit if unsure.
- Commit messages: Conventional Commits, e.g. `feat(programs): ...`, ending with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_013TaM13DFmuBJwVjcCsKF7b`.

## File Structure

Backend
- Create `src/api/routes/program_quick_actions.py` — defaults per namespace, `sanitize_quick_actions()`, `resolve_quick_actions()`, `register_quick_action_routes()`.
- Modify `src/api/routes/programs.py` — include `quick_actions` on list/create items; seed on create; call `register_quick_action_routes`.
- Modify `src/api/schemas.py` — `QuickActionItem`, `UpdateQuickActionsRequest`, `quick_actions` field on `SportsProgramItem` and `LanguageProgramItem`.
- Modify `src/agent/prompts.py` — one sentence in `_PROGRAM_STATIC_PREAMBLE`.
- Create `tests/integration/test_routes_program_quick_actions.py`, `tests/unit/test_program_quick_actions.py`.

Frontend
- Modify `web/src/types/api.ts` — `QuickAction`, `quick_actions` on `SportsProgram`/`LanguageProgram`.
- Modify `web/src/api/client.ts` — `sports.updateQuickActions`, `language.updateQuickActions`.
- Create `web/src/core/quick-actions.ts` — compose, mount/unmount, visibility, send, editor glue, save-from-message.
- Create `web/src/components/QuickActionsBar.ts`, `web/src/components/QuickActionForm.ts`, `web/src/components/QuickActionsEditor.ts`.
- Create `web/src/styles/components/quick-actions.css`; import in `web/src/styles/main.css`.
- Modify `web/src/core/init.ts` — bar mount point in the composer markup + `initQuickActions()`.
- Modify `web/src/core/composer-height.ts` — measure from the bar's top when visible.
- Modify `web/src/core/sports.ts`, `web/src/core/language.ts`, `web/src/components/SportsDashboard.ts`, `web/src/components/LanguageDashboard.ts` — mount bar, header gear button.
- Modify `web/src/components/messages/actions.ts` — "Save as quick action" button on user messages.
- Tests: `web/tests/unit/quick-actions.test.ts`, `web/tests/component/QuickActionsBar.test.ts`, `web/tests/component/QuickActionForm.test.ts`, `web/tests/component/QuickActionsEditor.test.ts`, `web/tests/e2e/quick-actions.spec.ts`, `web/tests/visual/quick-actions.visual.ts`.

Docs
- Modify `docs/features/ui-features.md`, `.claude/rules/programs.md`, spec status line.

---

### Task 1: Backend schemas, defaults, sanitization

**Files:**
- Create: `src/api/routes/program_quick_actions.py`
- Modify: `src/api/schemas.py:1530-1600`
- Test: `tests/unit/test_program_quick_actions.py`

**Interfaces:**
- Produces: `QuickActionItem` (Pydantic: `id`, `emoji`, `label`, `body`, `fields: list[str]`), `UpdateQuickActionsRequest(quick_actions: list[QuickActionItem])`, `QUICK_ACTION_DEFAULTS: dict[str, list[dict[str, Any]]]`, `sanitize_quick_actions(raw: Any) -> list[dict[str, Any]]`, `resolve_quick_actions(program: dict[str, Any], namespace: str) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_program_quick_actions.py
"""Unit tests for quick-action defaults and sanitization."""

from src.api.routes.program_quick_actions import (
    QUICK_ACTION_DEFAULTS,
    resolve_quick_actions,
    sanitize_quick_actions,
)


def _valid(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "abc123",
        "emoji": "\U0001f4ca",
        "label": "Log & review",
        "body": "Assess today's session.",
        "fields": ["Results", "Comments"],
    }
    base.update(overrides)
    return base


class TestDefaults:
    def test_sports_and_language_have_defaults(self) -> None:
        assert len(QUICK_ACTION_DEFAULTS["sports"]) == 2
        assert len(QUICK_ACTION_DEFAULTS["language"]) == 2

    def test_defaults_pass_sanitization_unchanged(self) -> None:
        for ns, defaults in QUICK_ACTION_DEFAULTS.items():
            assert sanitize_quick_actions(defaults) == defaults, ns


class TestSanitize:
    def test_keeps_valid_entries(self) -> None:
        assert sanitize_quick_actions([_valid()]) == [_valid()]

    def test_drops_malformed_entries_but_keeps_the_rest(self) -> None:
        raw = [_valid(), {"id": "x"}, "garbage", _valid(id="def456", fields=[])]
        result = sanitize_quick_actions(raw)
        assert [a["id"] for a in result] == ["abc123", "def456"]

    def test_non_list_input_yields_empty(self) -> None:
        assert sanitize_quick_actions(None) == []
        assert sanitize_quick_actions({"id": "x"}) == []

    def test_caps_at_twelve_actions(self) -> None:
        raw = [_valid(id=f"id{i}") for i in range(15)]
        assert len(sanitize_quick_actions(raw)) == 12

    def test_drops_entries_over_limits(self) -> None:
        too_long_body = _valid(body="x" * 2001)
        too_many_fields = _valid(fields=[f"f{i}" for i in range(7)])
        assert sanitize_quick_actions([too_long_body, too_many_fields]) == []


class TestResolve:
    def test_missing_key_returns_namespace_defaults(self) -> None:
        program = {"id": "pushups", "name": "Push-ups", "emoji": "x", "created_at": "t"}
        assert resolve_quick_actions(program, "sports") == QUICK_ACTION_DEFAULTS["sports"]

    def test_explicit_empty_list_stays_empty(self) -> None:
        program = {"id": "p", "quick_actions": []}
        assert resolve_quick_actions(program, "sports") == []

    def test_stored_actions_are_sanitized(self) -> None:
        program = {"id": "p", "quick_actions": [_valid(), "junk"]}
        assert resolve_quick_actions(program, "language") == [_valid()]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_program_quick_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.routes.program_quick_actions'`

- [ ] **Step 3: Add the Pydantic schemas**

In `src/api/schemas.py`, directly above `class SportsProgramItem` (line ~1530), add:

```python
# ============================================================================
# Program Quick Actions (shared by sports + language)
# ============================================================================

QUICK_ACTIONS_MAX_PER_PROGRAM = 12
QUICK_ACTION_MAX_FIELDS = 6


class QuickActionItem(BaseModel):
    """A one-tap saved prompt for a program conversation."""

    id: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    emoji: str = Field(..., min_length=1, max_length=10)
    label: str = Field(..., min_length=1, max_length=40)
    body: str = Field(..., min_length=1, max_length=2000)
    fields: list[str] = Field(default_factory=list, max_length=QUICK_ACTION_MAX_FIELDS)

    @field_validator("fields")
    @classmethod
    def _fields_non_empty_and_short(cls, value: list[str]) -> list[str]:
        cleaned = [f.strip() for f in value]
        if any(not f or len(f) > 40 for f in cleaned):
            raise ValueError("each field label must be 1-40 characters")
        return cleaned


class UpdateQuickActionsRequest(BaseModel):
    """Replace a program's full ordered quick-action list."""

    quick_actions: list[QuickActionItem] = Field(
        default_factory=list, max_length=QUICK_ACTIONS_MAX_PER_PROGRAM
    )
```

Check that `field_validator` is imported at the top of `schemas.py` (`from pydantic import BaseModel, Field, field_validator`); add it if missing.

Then add `quick_actions: list[QuickActionItem] = Field(default_factory=list)` as the last field of both `SportsProgramItem` and `LanguageProgramItem`.

- [ ] **Step 4: Create the quick-actions module**

```python
# src/api/routes/program_quick_actions.py
"""Quick actions for program conversations (sports, language).

A quick action is a per-program saved prompt (emoji, label, body, optional
field labels). They live INSIDE each program object in the namespace's
``programs`` K/V list - never under the ``{program_id}:`` prefix, which
program_context.py injects into the system prompt on every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas import (
    QUICK_ACTIONS_MAX_PER_PROGRAM,
    QuickActionItem,
    UpdateQuickActionsRequest,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from apiflask import APIBlueprint

    from src.api.routes.programs import ProgramRoutesConfig

logger = get_logger(__name__)

QUICK_ACTION_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "sports": [
        {
            "id": "plan-today",
            "emoji": "\U0001f4cb",
            "label": "Plan today",
            "body": (
                "Plan today's session. Check my Garmin readiness first and tell me "
                "which numbers drove the intensity call."
            ),
            "fields": ["Comments"],
        },
        {
            "id": "log-review",
            "emoji": "\U0001f4ca",
            "label": "Log & review",
            "body": (
                "Assess today's session against the plan and stored progress, note any "
                "PRs, update the Garmin workouts for the next session, and prepare the "
                "overview table."
            ),
            "fields": ["Results", "Comments"],
        },
    ],
    "language": [
        {
            "id": "new-lesson",
            "emoji": "\U0001f4d6",
            "label": "New lesson",
            "body": "Start a new lesson.",
            "fields": [],
        },
        {
            "id": "quiz-me",
            "emoji": "\U0001f9e0",
            "label": "Quiz me",
            "body": "Quiz me on the vocabulary from the last two lessons.",
            "fields": [],
        },
    ],
}


def sanitize_quick_actions(raw: Any) -> list[dict[str, Any]]:
    """Validate stored actions, dropping malformed entries instead of failing."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in raw:
        try:
            item = QuickActionItem.model_validate(entry)
        except (ValidationError, TypeError):
            logger.warning("Dropping malformed quick action", extra={"entry": repr(entry)[:200]})
            continue
        result.append(item.model_dump())
        if len(result) >= QUICK_ACTIONS_MAX_PER_PROGRAM:
            break
    return result


def resolve_quick_actions(program: dict[str, Any], namespace: str) -> list[dict[str, Any]]:
    """Actions for a program: stored list (sanitized) or namespace defaults when absent."""
    if "quick_actions" not in program:
        return [dict(a) for a in QUICK_ACTION_DEFAULTS.get(namespace, [])]
    return sanitize_quick_actions(program["quick_actions"])


def register_quick_action_routes(api: APIBlueprint, cfg: ProgramRoutesConfig) -> None:
    """Register PUT /{ns}/programs/<program_id>/quick-actions."""
    from src.api.routes.programs import _get_programs, _save_programs, program_to_item

    ns = cfg.namespace

    @api.route(f"/{ns}/programs/<program_id>/quick-actions", methods=["PUT"])
    @api.output(cfg.programs_response)
    @api.doc(responses=[400, 401, 404, 429])
    @rate_limit_conversations
    @require_auth
    @validate_request(UpdateQuickActionsRequest)
    def update_quick_actions(user: User, program_id: str, data: Any) -> dict[str, Any]:
        """Replace the program's quick actions (create/edit/reorder/delete)."""
        programs = _get_programs(user.id, ns)
        program = next((p for p in programs if p["id"] == program_id), None)
        if program is None:
            raise_not_found_error("Program")

        program["quick_actions"] = [a.model_dump() for a in data.quick_actions]
        _save_programs(user.id, ns, programs)

        logger.info(
            "Quick actions updated",
            extra={
                "namespace": ns,
                "user_id": user.id,
                "program_id": program_id,
                "count": len(program["quick_actions"]),
            },
        )
        return {"programs": [program_to_item(user.id, ns, program)]}
```

`program_to_item` is added to `programs.py` in Task 2; the import is inside the function so this module still imports cleanly for the unit tests in this task.

- [ ] **Step 5: Run the unit tests**

Run: `.venv/bin/python -m pytest tests/unit/test_program_quick_actions.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/schemas.py src/api/routes/program_quick_actions.py tests/unit/test_program_quick_actions.py
git commit -m "feat(programs): quick action schemas, defaults and sanitization"
```

---

### Task 2: Program routes return and update quick actions

**Files:**
- Modify: `src/api/routes/programs.py`
- Modify: `src/api/routes/sports.py`, `src/api/routes/language.py` (no code change needed if the factory registers the route; verify)
- Test: `tests/integration/test_routes_program_quick_actions.py`

**Interfaces:**
- Consumes: `resolve_quick_actions`, `register_quick_action_routes`, `QUICK_ACTION_DEFAULTS` from Task 1.
- Produces: `program_to_item(user_id: str, namespace: str, program: dict[str, Any], conv_program_ids: set[str] | None = None) -> dict[str, Any]` in `programs.py`; `GET /api/{ns}/programs` items include `quick_actions`; `POST /api/{ns}/programs` seeds defaults; `PUT /api/{ns}/programs/<id>/quick-actions`.

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_routes_program_quick_actions.py
"""Integration tests for program quick actions (sports namespace; language shares the factory)."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

from src.api.routes.program_quick_actions import QUICK_ACTION_DEFAULTS

if TYPE_CHECKING:
    from src.db.models import Database, User


def _seed(test_database: "Database", user_id: str, program: dict) -> None:
    test_database.kv_set(user_id, "sports", "programs", json.dumps([program]))


LEGACY_PROGRAM = {
    "id": "pushups",
    "name": "Push-ups",
    "emoji": "\U0001f4aa",
    "created_at": "2026-01-01T00:00:00",
}

ACTION = {
    "id": "hang",
    "emoji": "\U0001f9d7",
    "label": "Hang test",
    "body": "Log my dead hang.",
    "fields": ["Hang time (s)"],
}


class TestListIncludesQuickActions:
    def test_legacy_program_gets_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]

    def test_stored_actions_are_returned(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, {**LEGACY_PROGRAM, "quick_actions": [ACTION]})
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == [ACTION]

    def test_language_namespace_has_its_own_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        test_database.kv_set(test_user.id, "language", "programs", json.dumps([LEGACY_PROGRAM]))
        resp = client.get("/api/language/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["language"]


class TestCreateSeedsDefaults:
    def test_create_returns_and_persists_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        resp = client.post(
            "/api/sports/programs",
            headers=auth_headers,
            json={"name": "Rowing", "emoji": "\U0001f6a3"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]
        stored = json.loads(test_database.kv_get(test_user.id, "sports", "programs"))
        assert stored[0]["quick_actions"] == QUICK_ACTION_DEFAULTS["sports"]


class TestUpdateQuickActions:
    def test_requires_auth(self, client: FlaskClient) -> None:
        resp = client.put("/api/sports/programs/pushups/quick-actions", json={"quick_actions": []})
        assert resp.status_code == 401

    def test_unknown_program_404(self, client: FlaskClient, auth_headers: dict) -> None:
        resp = client.put(
            "/api/sports/programs/nope/quick-actions",
            headers=auth_headers,
            json={"quick_actions": []},
        )
        assert resp.status_code == 404

    def test_put_replaces_list_and_returns_program(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": [ACTION]},
        )
        assert resp.status_code == 200
        item = resp.get_json()["programs"][0]
        assert item["id"] == "pushups"
        assert item["quick_actions"] == [ACTION]
        assert item["has_conversation"] is False
        stored = json.loads(test_database.kv_get(test_user.id, "sports", "programs"))
        assert stored[0]["quick_actions"] == [ACTION]

    def test_put_empty_list_clears_defaults(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": []},
        )
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.get_json()["programs"][0]["quick_actions"] == []

    def test_put_rejects_over_limits(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, LEGACY_PROGRAM)
        too_many = [{**ACTION, "id": f"a{i}"} for i in range(13)]
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": too_many},
        )
        assert resp.status_code == 400
        resp = client.put(
            "/api/sports/programs/pushups/quick-actions",
            headers=auth_headers,
            json={"quick_actions": [{**ACTION, "body": "x" * 2001}]},
        )
        assert resp.status_code == 400

    def test_corrupt_stored_actions_are_dropped_on_read(
        self, client: FlaskClient, auth_headers: dict, test_database: "Database", test_user: "User"
    ) -> None:
        _seed(test_database, test_user.id, {**LEGACY_PROGRAM, "quick_actions": [ACTION, {"id": "bad"}]})
        resp = client.get("/api/sports/programs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["programs"][0]["quick_actions"] == [ACTION]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_routes_program_quick_actions.py -v`
Expected: FAIL (`quick_actions` missing from list items → `KeyError`; PUT → 405/404)

- [ ] **Step 3: Add `program_to_item` and wire the factory**

In `src/api/routes/programs.py`:

Add import after the existing imports:

```python
from src.api.routes.program_quick_actions import (
    QUICK_ACTION_DEFAULTS,
    register_quick_action_routes,
    resolve_quick_actions,
)
```

Add a module-level helper after `_save_programs`:

```python
def program_to_item(
    user_id: str,
    namespace: str,
    program: dict[str, Any],
    conv_program_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Shape a stored program dict as the API's program item."""
    if conv_program_ids is None:
        from src.db.models.programs import PROGRAM_FEATURES

        column = PROGRAM_FEATURES[namespace].program_column
        conv_program_ids = {
            getattr(c, column) for c in db.list_program_conversations(namespace, user_id)
        }
    return {
        "id": program["id"],
        "name": program["name"],
        "emoji": program["emoji"],
        "created_at": program["created_at"],
        "has_conversation": program["id"] in conv_program_ids,
        "quick_actions": resolve_quick_actions(program, namespace),
    }
```

Replace the body of `list_programs` after `programs = _get_programs(...)` with:

```python
        from src.db.models.programs import PROGRAM_FEATURES

        program_column = PROGRAM_FEATURES[ns].program_column
        conv_programs = {
            getattr(c, program_column) for c in db.list_program_conversations(ns, user.id)
        }
        return {"programs": [program_to_item(user.id, ns, p, conv_programs) for p in programs]}
```

In `create_program`, add `"quick_actions": [dict(a) for a in QUICK_ACTION_DEFAULTS.get(ns, [])],` to `new_program`, and change the return to:

```python
        return {"programs": [program_to_item(user.id, ns, new_program, set())]}
```

At the end of `register_program_routes` (after `reset_conversation`), add:

```python
    register_quick_action_routes(api, cfg)
```

`sports.py` and `language.py` need no change.

- [ ] **Step 4: Run the new tests and the existing program route tests**

Run: `.venv/bin/python -m pytest tests/integration/test_routes_program_quick_actions.py tests/integration/test_routes_sports.py tests/integration/test_routes_language.py tests/unit/test_program_quick_actions.py -v`
Expected: all PASS

- [ ] **Step 5: Regenerate the OpenAPI spec and TypeScript types**

Run: `make openapi > /tmp/openapi.log 2>&1; echo "exit=$?"` then `make types > /tmp/types.log 2>&1; echo "exit=$?"`
Expected: both `exit=0`; `git status` shows `static/openapi.json` and `web/src/types/generated-api.ts` modified, containing `QuickActionItem`.

- [ ] **Step 6: Lint**

Run: `make lint > /tmp/lint.log 2>&1; echo "exit=$?"`
Expected: `exit=0`. If not, read `/tmp/lint.log` and fix.

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/programs.py tests/integration/test_routes_program_quick_actions.py static/openapi.json web/src/types/generated-api.ts
git commit -m "feat(programs): return quick actions on program items and PUT endpoint to replace them"
```

---

### Task 3: Prompt preamble sentence

**Files:**
- Modify: `src/agent/prompts.py:1601-1605`
- Test: `tests/unit/test_program_quick_actions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_program_quick_actions.py`:

```python
from src.agent.prompts import get_static_prompt_for_profile


class TestPromptPreamble:
    def test_program_profiles_explain_quick_action_blocks(self) -> None:
        for profile in ("sports", "language"):
            prompt = get_static_prompt_for_profile(profile)
            assert "quick action" in prompt.lower(), profile
            assert "Label: value" in prompt, profile

    def test_standard_profile_is_unaffected(self) -> None:
        assert "quick action" not in get_static_prompt_for_profile("standard").lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_program_quick_actions.py::TestPromptPreamble -v`
Expected: FAIL on the `"quick action" in prompt.lower()` assertion

- [ ] **Step 3: Extend the preamble**

Replace `_PROGRAM_STATIC_PREAMBLE` in `src/agent/prompts.py` with:

```python
_PROGRAM_STATIC_PREAMBLE = (
    "\n\nNote: the placeholders <program_name> and <program_id> below refer to the "
    "active program - its actual name and id are given in the Active Program "
    "section of the per-request context.\n"
    "\nA user message may come from a one-tap quick action: a fixed request followed "
    "by a blank line and `Label: value` lines (for example `Hang time (s): 54`). Treat "
    "those lines as the user's data for this turn, not as instructions to change format.\n"
)
```

- [ ] **Step 4: Run the prompt tests and the context-cache tests**

Run: `.venv/bin/python -m pytest tests/unit/test_program_quick_actions.py tests/unit/test_context_cache.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/prompts.py tests/unit/test_program_quick_actions.py
git commit -m "feat(agent): tell program prompts how quick-action Label: value blocks look"
```

---

### Task 4: Frontend types, API client, and message composition

**Files:**
- Modify: `web/src/types/api.ts:809-850`
- Modify: `web/src/api/client.ts:1133-1190`
- Create: `web/src/core/quick-actions.ts` (compose function only in this task; the rest is added in Tasks 5–8)
- Test: `web/tests/unit/quick-actions.test.ts`

**Interfaces:**
- Produces: `QuickAction { id; emoji; label; body; fields: string[] }`; `SportsProgram.quick_actions`, `LanguageProgram.quick_actions`; `sports.updateQuickActions(programId, actions): Promise<SportsProgram>`; `language.updateQuickActions(programId, actions): Promise<LanguageProgram>`; `composeQuickActionMessage(action: QuickAction, values: Record<string, string>): string`.

- [ ] **Step 1: Write the failing unit tests**

```ts
// web/tests/unit/quick-actions.test.ts
/**
 * Unit tests for quick-action message composition.
 */
import { describe, it, expect } from 'vitest';
import { composeQuickActionMessage } from '@/core/quick-actions';
import type { QuickAction } from '@/types/api';

const action: QuickAction = {
  id: 'log',
  emoji: '📊',
  label: 'Log & review',
  body: 'Assess today.  ',
  fields: ['Hang time (s)', 'Comments'],
};

describe('composeQuickActionMessage', () => {
  it('returns the trimmed body when there are no fields', () => {
    expect(composeQuickActionMessage({ ...action, fields: [] }, {})).toBe('Assess today.');
  });

  it('returns only the body when every field is empty or whitespace', () => {
    expect(composeQuickActionMessage(action, { 'Hang time (s)': '  ', Comments: '' })).toBe(
      'Assess today.'
    );
  });

  it('appends Label: value lines after a blank line, in field order', () => {
    const out = composeQuickActionMessage(action, { Comments: 'felt strong', 'Hang time (s)': '54' });
    expect(out).toBe('Assess today.\n\nHang time (s): 54\nComments: felt strong');
  });

  it('omits empty fields but keeps the others', () => {
    const out = composeQuickActionMessage(action, { 'Hang time (s)': '', Comments: 'ok' });
    expect(out).toBe('Assess today.\n\nComments: ok');
  });

  it('indents continuation lines of multi-line values by two spaces', () => {
    const out = composeQuickActionMessage(action, { Comments: 'line one\nline two\n' });
    expect(out).toBe('Assess today.\n\nComments: line one\n  line two');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/quick-actions.test.ts`
Expected: FAIL, cannot resolve `@/core/quick-actions`

- [ ] **Step 3: Add the types**

In `web/src/types/api.ts`, above `export interface SportsProgram`:

```ts
/** A one-tap saved prompt for a program conversation (sports, language). */
export interface QuickAction {
  id: string;
  emoji: string;
  label: string;
  body: string;
  /** Ordered field labels asked for before sending; answers append as `Label: value`. */
  fields: string[];
}
```

Add `quick_actions: QuickAction[];` as the last member of both `SportsProgram` and `LanguageProgram`.

- [ ] **Step 4: Add the client methods**

In `web/src/api/client.ts`, inside `export const sports = {` after `reset`:

```ts
  async updateQuickActions(programId: string, actions: QuickAction[]): Promise<SportsProgram> {
    const response = await request<SportsProgramsResponse>(
      `/api/sports/programs/${encodeURIComponent(programId)}/quick-actions`,
      { method: 'PUT', body: JSON.stringify({ quick_actions: actions }) }
    );
    return response.programs[0];
  },
```

And inside `export const language = {` after `reset`:

```ts
  async updateQuickActions(programId: string, actions: QuickAction[]): Promise<LanguageProgram> {
    const response = await request<LanguageProgramsResponse>(
      `/api/language/programs/${encodeURIComponent(programId)}/quick-actions`,
      { method: 'PUT', body: JSON.stringify({ quick_actions: actions }) }
    );
    return response.programs[0];
  },
```

Add `QuickAction` to the `import type { ... } from '../types/api'` list at the top of `client.ts`.

- [ ] **Step 5: Create the compose function**

```ts
// web/src/core/quick-actions.ts
/**
 * Quick actions: one-tap saved prompts for program conversations.
 *
 * This module owns message composition, mounting the chip bar above the
 * composer while a program conversation is open, its mobile visibility
 * rules, sending, and the editor glue. Components in
 * components/QuickActions*.ts are presentation only.
 */
import type { QuickAction } from '../types/api';

/**
 * Body, blank line, then one `Label: value` line per non-empty field (in
 * field order). Multi-line values indent continuation lines by two spaces.
 * All-empty fields -> body only.
 */
export function composeQuickActionMessage(
  action: QuickAction,
  values: Record<string, string>
): string {
  const body = action.body.trim();
  const lines: string[] = [];
  for (const field of action.fields) {
    const value = (values[field] ?? '').trim();
    if (!value) continue;
    lines.push(`${field}: ${value.split('\n').join('\n  ')}`);
  }
  return lines.length > 0 ? `${body}\n\n${lines.join('\n')}` : body;
}
```

- [ ] **Step 6: Run the unit tests and typecheck**

Run: `cd web && npx vitest run tests/unit/quick-actions.test.ts && npx tsc --noEmit`
Expected: tests PASS; tsc reports errors ONLY where `SportsProgram`/`LanguageProgram` objects are constructed without `quick_actions` (test mocks, `web/tests/**`). Fix each by adding `quick_actions: []` to the literal. Re-run until tsc exits 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/types/api.ts web/src/api/client.ts web/src/core/quick-actions.ts web/tests/unit/quick-actions.test.ts web/tests
git commit -m "feat(web): quick action types, client methods and message composition"
```

---

### Task 5: Chip bar component, styles, mount point, visibility rules

**Files:**
- Create: `web/src/components/QuickActionsBar.ts`
- Create: `web/src/styles/components/quick-actions.css`
- Modify: `web/src/styles/main.css:41-43`
- Modify: `web/src/core/init.ts:125-130` (markup), `~464-498` (init call)
- Modify: `web/src/core/composer-height.ts:46`
- Modify: `web/src/core/quick-actions.ts`
- Test: `web/tests/component/QuickActionsBar.test.ts`, `web/tests/unit/quick-actions.test.ts` (append), `web/tests/unit/composer-height.test.ts` (append)

**Interfaces:**
- Produces (component): `renderQuickActionsBar(container: HTMLElement, actions: QuickAction[], onTap: (action: QuickAction, chip: HTMLElement) => void): void`, `setQuickActionsBarDisabled(container: HTMLElement, disabled: boolean): void`.
- Produces (core): `mountQuickActionsBar(ctx: QuickActionsContext): void`, `unmountQuickActionsBar(): void`, `initQuickActions(): void`, `shouldShowQuickActionsBar(input: { mobile: boolean; composerEmpty: boolean; streaming: boolean }): boolean`, `QuickActionsContext { namespace: 'sports' | 'language'; programId: string; actions: QuickAction[]; save: (actions: QuickAction[]) => Promise<QuickAction[]> }`.
- Markup: `<div id="quick-actions-bar" class="quick-actions-bar hidden" role="toolbar" aria-label="Quick actions"></div>` inside `.input-wrapper`, directly before `#input-container`.

- [ ] **Step 1: Write the failing component test**

```ts
// web/tests/component/QuickActionsBar.test.ts
/**
 * Component tests for the quick-actions chip bar.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderQuickActionsBar, setQuickActionsBarDisabled } from '@/components/QuickActionsBar';
import type { QuickAction } from '@/types/api';

const actions: QuickAction[] = [
  { id: 'a', emoji: '📋', label: 'Plan today', body: 'Plan.', fields: [] },
  { id: 'b', emoji: '📊', label: 'Log & review', body: 'Log.', fields: ['Comments'] },
];

describe('QuickActionsBar', () => {
  let container: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<div id="quick-actions-bar" class="quick-actions-bar hidden"></div>';
    container = document.getElementById('quick-actions-bar')!;
  });

  it('renders one chip per action with emoji, label and data-action-id', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    const chips = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].dataset.actionId).toBe('a');
    expect(chips[0].querySelector('.quick-action-chip-emoji')!.textContent).toBe('📋');
    expect(chips[0].querySelector('.quick-action-chip-label')!.textContent).toBe('Plan today');
  });

  it('escapes label text (no HTML injection)', () => {
    renderQuickActionsBar(container, [{ ...actions[0], label: '<img src=x onerror=alert(1)>' }], vi.fn());
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('.quick-action-chip-label')!.textContent).toContain('<img');
  });

  it('calls onTap with the action and chip element (event delegation)', () => {
    const onTap = vi.fn();
    renderQuickActionsBar(container, actions, onTap);
    const chip = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip')[1];
    chip.querySelector('.quick-action-chip-label')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onTap).toHaveBeenCalledWith(actions[1], chip);
  });

  it('re-render replaces chips instead of appending', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    renderQuickActionsBar(container, actions.slice(0, 1), vi.fn());
    expect(container.querySelectorAll('.quick-action-chip').length).toBe(1);
  });

  it('disabled state disables every chip', () => {
    renderQuickActionsBar(container, actions, vi.fn());
    setQuickActionsBarDisabled(container, true);
    const chips = container.querySelectorAll<HTMLButtonElement>('.quick-action-chip');
    expect([...chips].every((c) => c.disabled)).toBe(true);
    setQuickActionsBarDisabled(container, false);
    expect([...chips].every((c) => !c.disabled)).toBe(true);
  });
});
```

- [ ] **Step 2: Write the failing visibility-rule unit tests**

Append to `web/tests/unit/quick-actions.test.ts`:

```ts
import { shouldShowQuickActionsBar } from '@/core/quick-actions';

describe('shouldShowQuickActionsBar', () => {
  it('desktop: always visible', () => {
    expect(shouldShowQuickActionsBar({ mobile: false, composerEmpty: false, streaming: true })).toBe(true);
  });
  it('mobile: visible only when composer is empty and nothing streams', () => {
    expect(shouldShowQuickActionsBar({ mobile: true, composerEmpty: true, streaming: false })).toBe(true);
    expect(shouldShowQuickActionsBar({ mobile: true, composerEmpty: false, streaming: false })).toBe(false);
    expect(shouldShowQuickActionsBar({ mobile: true, composerEmpty: true, streaming: true })).toBe(false);
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `cd web && npx vitest run tests/component/QuickActionsBar.test.ts tests/unit/quick-actions.test.ts`
Expected: FAIL (module not found / export missing)

- [ ] **Step 4: Create the bar component**

```ts
// web/src/components/QuickActionsBar.ts
/**
 * Quick-actions chip bar: horizontally scrolling row of one-tap prompts
 * rendered above the composer in program conversations. Presentation only;
 * core/quick-actions.ts decides when it is mounted/visible and what a tap does.
 */
import type { QuickAction } from '../types/api';
import { clearElement, escapeHtml } from '../utils/dom';

type TapHandler = (action: QuickAction, chip: HTMLElement) => void;

// One delegated listener per container; re-renders swap the handler.
const handlers = new WeakMap<HTMLElement, { actions: QuickAction[]; onTap: TapHandler }>();

export function renderQuickActionsBar(
  container: HTMLElement,
  actions: QuickAction[],
  onTap: TapHandler
): void {
  clearElement(container);
  const scroller = document.createElement('div');
  scroller.className = 'quick-actions-scroller';
  scroller.innerHTML = actions
    .map(
      (a) => `
      <button type="button" class="quick-action-chip" data-action-id="${escapeHtml(a.id)}" title="${escapeHtml(a.body)}">
        <span class="quick-action-chip-emoji" aria-hidden="true">${escapeHtml(a.emoji)}</span>
        <span class="quick-action-chip-label">${escapeHtml(a.label)}</span>
      </button>`
    )
    .join('');
  container.appendChild(scroller);

  if (!handlers.has(container)) {
    container.addEventListener('click', (e) => {
      const chip = (e.target as HTMLElement).closest<HTMLElement>('.quick-action-chip');
      if (!chip || (chip as HTMLButtonElement).disabled) return;
      const entry = handlers.get(container);
      const action = entry?.actions.find((a) => a.id === chip.dataset.actionId);
      if (entry && action) entry.onTap(action, chip);
    });
  }
  handlers.set(container, { actions, onTap });
}

export function setQuickActionsBarDisabled(container: HTMLElement, disabled: boolean): void {
  container.classList.toggle('quick-actions-bar--disabled', disabled);
  for (const chip of container.querySelectorAll<HTMLButtonElement>('.quick-action-chip')) {
    chip.disabled = disabled;
  }
}
```

- [ ] **Step 5: Add the styles and import them**

```css
/* web/src/styles/components/quick-actions.css */
/* ============================================
   Quick Actions (program conversations)
   ============================================
   - Chip bar above the composer
   - Field form (popover desktop / bottom sheet mobile)
   - Editor modal
*/

/* ----------------------------------------
   Chip bar
   ---------------------------------------- */

.quick-actions-bar {
    /* Sits inside .input-wrapper directly above the composer pill.
       Visibility toggles via .hidden (display:none) - never animate height. */
    padding: 0 0 var(--space-2);
}

.quick-actions-bar.hidden {
    display: none;
}

.quick-actions-scroller {
    display: flex;
    gap: var(--space-2);
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
    /* Let the first/last chip breathe past the pill's rounded edge */
    padding: 2px var(--space-1);
}

.quick-actions-scroller::-webkit-scrollbar {
    display: none;
}

.quick-action-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
    max-width: 240px;
    padding: var(--space-1) var(--space-3);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-primary);
    font-size: var(--font-size-sm);
    font-weight: 500;
    line-height: 1.4;
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast),
        opacity var(--transition-fast), transform var(--transition-fast);
}

.quick-action-chip:hover:not(:disabled) {
    background: var(--bg-hover);
    border-color: var(--accent);
}

.quick-action-chip:active:not(:disabled) {
    transform: scale(0.97);
}

.quick-action-chip:disabled {
    opacity: 0.5;
    cursor: default;
}

.quick-action-chip-label {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ----------------------------------------
   Field form (Task 6)
   ---------------------------------------- */

/* ----------------------------------------
   Editor (Task 7)
   ---------------------------------------- */
```

In `web/src/styles/main.css`, after `@import './components/language.css';` add:

```css
@import './components/quick-actions.css';
```

- [ ] **Step 6: Add the mount point and init call**

In `web/src/core/init.ts` composer markup, insert directly before `<div id="input-container" class="input-container">`:

```html
          <div id="quick-actions-bar" class="quick-actions-bar hidden" role="toolbar" aria-label="Quick actions"></div>
```

In the "Initialize components" block, after `initComposerHeight();`, add `initQuickActions();` and import it: `import { initQuickActions } from './quick-actions';`.

- [ ] **Step 7: Make composer-height measure from the bar when visible**

In `web/src/core/composer-height.ts`, replace

```ts
    const pill = inputArea.querySelector<HTMLElement>('.input-container') ?? inputArea;
```

with

```ts
    // The quick-actions bar (program conversations) sits above the pill and
    // must be cleared too when visible.
    const pill =
      inputArea.querySelector<HTMLElement>('.quick-actions-bar:not(.hidden)') ??
      inputArea.querySelector<HTMLElement>('.input-container') ??
      inputArea;
```

Append a new `describe` block to `web/tests/unit/composer-height.test.ts` (it already imports `cleanupComposerHeight`, `initComposerHeight`, and defines `getVar()`):

```ts
describe('composer height with quick-actions bar', () => {
  afterEach(() => cleanupComposerHeight());

  function arrange(barHidden: boolean): void {
    document.body.innerHTML = `
      <div class="input-area">
        <div id="quick-actions-bar" class="quick-actions-bar${barHidden ? ' hidden' : ''}"></div>
        <div class="input-container"></div>
      </div>`;
    const inputArea = document.querySelector('.input-area') as HTMLDivElement;
    const bar = document.getElementById('quick-actions-bar') as HTMLDivElement;
    const pill = document.querySelector('.input-container') as HTMLDivElement;
    // Box spans 0..200; pill top at 120 (footprint 80); bar top at 80 (footprint 120)
    vi.spyOn(inputArea, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 200, height: 200 } as DOMRect);
    vi.spyOn(pill, 'getBoundingClientRect').mockReturnValue({ top: 120, bottom: 200, height: 80 } as DOMRect);
    vi.spyOn(bar, 'getBoundingClientRect').mockReturnValue({ top: 80, bottom: 120, height: 40 } as DOMRect);
  }

  it('measures from the pill when the bar is hidden', () => {
    arrange(true);
    initComposerHeight();
    expect(getVar()).toBe('80px');
  });

  it('measures from the bar top when the bar is visible', () => {
    arrange(false);
    initComposerHeight();
    expect(getVar()).toBe('120px');
  });
});
```

- [ ] **Step 8: Add mount/visibility logic to core**

Append to `web/src/core/quick-actions.ts`:

```ts
import { useStore } from '../state/store';
import { renderQuickActionsBar, setQuickActionsBarDisabled } from '../components/QuickActionsBar';
import { isMobileViewport } from '../components/MessageInput';
import { getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';

const log = createLogger('quick-actions');

export interface QuickActionsContext {
  namespace: 'sports' | 'language';
  programId: string;
  actions: QuickAction[];
  /** Persist the full list; resolves with the server's copy. */
  save: (actions: QuickAction[]) => Promise<QuickAction[]>;
}

let current: QuickActionsContext | null = null;
let unsubscribeStore: (() => void) | null = null;

export function shouldShowQuickActionsBar(input: {
  mobile: boolean;
  composerEmpty: boolean;
  streaming: boolean;
}): boolean {
  if (!input.mobile) return true;
  return input.composerEmpty && !input.streaming;
}

function isCurrentConversationStreaming(): boolean {
  const state = useStore.getState();
  const convId = state.currentConversation?.id;
  return convId !== undefined && state.activeRequests.has(convId);
}

/** Re-evaluate visibility + disabled state from composer/stream state. */
export function refreshQuickActionsBar(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar) return;
  if (!current || current.actions.length === 0) {
    bar.classList.add('hidden');
    return;
  }
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  const streaming = isCurrentConversationStreaming();
  const visible = shouldShowQuickActionsBar({
    mobile: isMobileViewport(),
    composerEmpty: !textarea || textarea.value.trim() === '',
    streaming,
  });
  bar.classList.toggle('hidden', !visible);
  setQuickActionsBarDisabled(bar, streaming);
}

function renderCurrent(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar || !current) return;
  renderQuickActionsBar(bar, current.actions, (action, chip) => handleChipTap(action, chip));
  refreshQuickActionsBar();
}

// Filled in by Task 6 (send + form). Kept here so Task 5 compiles.
function handleChipTap(action: QuickAction, chip: HTMLElement): void {
  log.debug('Quick action tapped', { id: action.id, chip: chip.tagName });
}

export function mountQuickActionsBar(ctx: QuickActionsContext): void {
  current = ctx;
  document.body.classList.add('has-quick-actions');
  renderCurrent();
}

export function unmountQuickActionsBar(): void {
  current = null;
  document.body.classList.remove('has-quick-actions');
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (bar) bar.classList.add('hidden');
}

/** Wire composer + store listeners once at app init. */
export function initQuickActions(): void {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  textarea?.addEventListener('input', refreshQuickActionsBar);
  window.addEventListener('resize', refreshQuickActionsBar);
  unsubscribeStore?.();
  unsubscribeStore = useStore.subscribe(
    (state) => state.activeRequests,
    () => refreshQuickActionsBar()
  );
}
```

Check that `useStore.subscribe(selector, listener)` matches how `MessageInput.ts` subscribes (it does: `useStore.subscribe((state) => ..., () => ...)`, so the store has the `subscribeWithSelector` middleware).

- [ ] **Step 9: Run tests, typecheck, lint**

Run: `cd web && npx vitest run tests/component/QuickActionsBar.test.ts tests/unit/quick-actions.test.ts tests/unit/composer-height.test.ts && npx tsc --noEmit && npx eslint src tests --max-warnings 0`
Expected: all PASS, exit 0

- [ ] **Step 10: Commit**

```bash
git add web/src/components/QuickActionsBar.ts web/src/styles/components/quick-actions.css web/src/styles/main.css web/src/core/init.ts web/src/core/composer-height.ts web/src/core/quick-actions.ts web/tests/component/QuickActionsBar.test.ts web/tests/unit/quick-actions.test.ts web/tests/unit/composer-height.test.ts
git commit -m "feat(web): quick-actions chip bar above the composer with mobile visibility rules"
```

---

### Task 6: Field form and sending

**Files:**
- Create: `web/src/components/QuickActionForm.ts`
- Modify: `web/src/styles/components/quick-actions.css` (form section)
- Modify: `web/src/core/quick-actions.ts` (`handleChipTap`, `sendQuickAction`)
- Test: `web/tests/component/QuickActionForm.test.ts`

**Interfaces:**
- Consumes: `composeQuickActionMessage`, `sendMessage()` from `core/messaging.ts`, `isMobileViewport()` from `components/MessageInput.ts`.
- Produces: `showQuickActionForm(action: QuickAction, anchor: HTMLElement, onSend: (values: Record<string, string>) => void): void`, `closeQuickActionForm(): void`, `sendQuickAction(action: QuickAction, values: Record<string, string>): Promise<void>`.

- [ ] **Step 1: Write the failing component tests**

```ts
// web/tests/component/QuickActionForm.test.ts
/**
 * Component tests for the quick-action field form.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showQuickActionForm, closeQuickActionForm } from '@/components/QuickActionForm';
import type { QuickAction } from '@/types/api';

const action: QuickAction = {
  id: 'log',
  emoji: '📊',
  label: 'Log & review',
  body: 'Assess.',
  fields: ['Hang time (s)', 'Comments'],
};

describe('QuickActionForm', () => {
  let anchor: HTMLElement;
  beforeEach(() => {
    document.body.innerHTML = '<button id="anchor">chip</button>';
    anchor = document.getElementById('anchor')!;
  });
  afterEach(() => closeQuickActionForm());

  it('renders one textarea per field with the label, first field focused', () => {
    showQuickActionForm(action, anchor, vi.fn());
    const form = document.querySelector('.quick-action-form')!;
    const areas = form.querySelectorAll<HTMLTextAreaElement>('textarea');
    expect(areas.length).toBe(2);
    expect(form.querySelectorAll('label')[0].textContent).toBe('Hang time (s)');
    expect(document.activeElement).toBe(areas[0]);
    expect(form.querySelector('.quick-action-form-title')!.textContent).toContain('Log & review');
  });

  it('Send calls onSend with values keyed by field label and closes', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    const areas = document.querySelectorAll<HTMLTextAreaElement>('.quick-action-form textarea');
    areas[0].value = '54';
    areas[1].value = 'felt ok';
    (document.querySelector('.quick-action-form-send') as HTMLButtonElement).click();
    expect(onSend).toHaveBeenCalledWith({ 'Hang time (s)': '54', Comments: 'felt ok' });
    expect(document.querySelector('.quick-action-form')).toBeNull();
  });

  it('Cancel and Escape close without sending', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    (document.querySelector('.quick-action-form-cancel') as HTMLButtonElement).click();
    expect(document.querySelector('.quick-action-form')).toBeNull();
    showQuickActionForm(action, anchor, onSend);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.querySelector('.quick-action-form')).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('Cmd/Ctrl+Enter inside a field sends', () => {
    const onSend = vi.fn();
    showQuickActionForm(action, anchor, onSend);
    const area = document.querySelector<HTMLTextAreaElement>('.quick-action-form textarea')!;
    area.value = '60';
    area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    expect(onSend).toHaveBeenCalledWith({ 'Hang time (s)': '60', Comments: '' });
  });

  it('opening a second form replaces the first', () => {
    showQuickActionForm(action, anchor, vi.fn());
    showQuickActionForm(action, anchor, vi.fn());
    expect(document.querySelectorAll('.quick-action-form').length).toBe(1);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/component/QuickActionForm.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Create the form component**

```ts
// web/src/components/QuickActionForm.ts
/**
 * Field form shown when a quick action has fields. Popover anchored to the
 * chip on desktop, bottom sheet on mobile (both share the same DOM; CSS
 * switches layout at the 768px breakpoint). Presentation only.
 */
import type { QuickAction } from '../types/api';
import { escapeHtml, autoResizeTextarea } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import { isMobileViewport } from './MessageInput';

let overlay: HTMLElement | null = null;
let keydownHandler: ((e: KeyboardEvent) => void) | null = null;

export function closeQuickActionForm(): void {
  if (keydownHandler) document.removeEventListener('keydown', keydownHandler);
  keydownHandler = null;
  overlay?.remove();
  overlay = null;
}

export function showQuickActionForm(
  action: QuickAction,
  anchor: HTMLElement,
  onSend: (values: Record<string, string>) => void
): void {
  closeQuickActionForm();

  overlay = document.createElement('div');
  overlay.className = 'quick-action-form-overlay';

  const form = document.createElement('div');
  form.className = 'quick-action-form';
  form.setAttribute('role', 'dialog');
  form.setAttribute('aria-modal', 'true');
  form.setAttribute('aria-label', action.label);
  form.innerHTML = `
    <div class="quick-action-form-title">${escapeHtml(action.emoji)} ${escapeHtml(action.label)}</div>
    <div class="quick-action-form-fields">
      ${action.fields
        .map(
          (f, i) => `
        <div class="quick-action-form-field">
          <label for="qa-field-${i}">${escapeHtml(f)}</label>
          <textarea id="qa-field-${i}" data-field="${escapeHtml(f)}" rows="1" placeholder="Optional"></textarea>
        </div>`
        )
        .join('')}
    </div>
    <div class="quick-action-form-actions">
      <button type="button" class="quick-action-form-cancel">Cancel</button>
      <button type="button" class="quick-action-form-send">Send</button>
    </div>`;
  overlay.appendChild(form);
  document.body.appendChild(overlay);

  // Desktop: anchor the popover above the chip. Mobile: CSS pins it bottom.
  if (!isMobileViewport()) {
    const rect = anchor.getBoundingClientRect();
    form.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - form.offsetWidth - 8))}px`;
    form.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  }

  const collect = (): Record<string, string> => {
    const values: Record<string, string> = {};
    for (const area of form.querySelectorAll<HTMLTextAreaElement>('textarea')) {
      values[area.dataset.field ?? ''] = area.value;
    }
    return values;
  };
  const submit = (): void => {
    const values = collect();
    closeQuickActionForm();
    onSend(values);
  };

  form.querySelector('.quick-action-form-send')!.addEventListener('click', submit);
  form.querySelector('.quick-action-form-cancel')!.addEventListener('click', closeQuickActionForm);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeQuickActionForm();
  });
  form.addEventListener('input', (e) => {
    const t = e.target as HTMLElement;
    if (t instanceof HTMLTextAreaElement) autoResizeTextarea(t);
  });
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  });
  keydownHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeQuickActionForm();
      return;
    }
    trapTabKey(form, e);
  };
  document.addEventListener('keydown', keydownHandler);

  form.querySelector<HTMLTextAreaElement>('textarea')?.focus();
}
```

Check the signature of `trapTabKey` in `web/src/utils/focus-trap.ts` (`trapTabKey(container: HTMLElement, e: KeyboardEvent)` as used in `SportsDashboard.ts`).

- [ ] **Step 4: Add form styles**

Replace the `/* Field form (Task 6) */` placeholder in `quick-actions.css` with:

```css
/* ----------------------------------------
   Field form
   ---------------------------------------- */

.quick-action-form-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    background: transparent;
}

.quick-action-form {
    position: fixed;
    width: min(360px, calc(100vw - 16px));
    padding: var(--space-3);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
}

.quick-action-form-title {
    font-weight: 600;
    font-size: var(--font-size-ui);
}

.quick-action-form-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

.quick-action-form-field label {
    display: block;
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
    margin-bottom: 2px;
}

.quick-action-form-field textarea {
    width: 100%;
    resize: none;
    padding: var(--space-2);
    background: var(--bg-primary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font: inherit;
    font-size: var(--font-size-ui);
    max-height: 160px;
}

.quick-action-form-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
}

.quick-action-form-cancel,
.quick-action-form-send {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
    font-weight: 500;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--bg-tertiary);
    color: var(--text-secondary);
}

.quick-action-form-send {
    background: var(--accent);
    border-color: transparent;
    color: #fff;
}

.quick-action-form-send:hover {
    background: var(--accent-hover);
}

@media (max-width: 768px) {
    .quick-action-form-overlay {
        background: rgba(0, 0, 0, 0.35);
    }

    .quick-action-form {
        left: 0 !important;
        right: 0;
        bottom: 0 !important;
        width: auto;
        border-radius: var(--radius-lg) var(--radius-lg) 0 0;
        padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom));
    }

    .quick-action-form-cancel,
    .quick-action-form-send {
        flex: 1;
        padding: var(--space-3);
    }
}
```

All tokens used above (`--z-modal`, `--shadow-lg`, `--accent`, `--accent-hover`, `--bg-*`, `--text-*`, `--border`, `--radius-*`, `--space-*`, `--font-size-*`) exist in `web/src/styles/variables.css`.

- [ ] **Step 5: Wire tap → send/form in core**

In `web/src/core/quick-actions.ts`, add imports:

```ts
import { sendMessage } from './messaging';
import { showQuickActionForm } from '../components/QuickActionForm';
import { toast } from '../components/Toast';
```

Replace the placeholder `handleChipTap` with:

```ts
function handleChipTap(action: QuickAction, chip: HTMLElement): void {
  if (isCurrentConversationStreaming()) {
    toast.info('Please wait for the current response to finish.');
    return;
  }
  if (action.fields.length === 0) {
    void sendQuickAction(action, {});
    return;
  }
  showQuickActionForm(action, chip, (values) => void sendQuickAction(action, values));
}

/** Compose the message, put it in the composer and send through the normal path. */
export async function sendQuickAction(
  action: QuickAction,
  values: Record<string, string>
): Promise<void> {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!textarea) return;
  const text = composeQuickActionMessage(action, values);
  log.info('Sending quick action', { id: action.id, fields: Object.keys(values).length });
  textarea.value = text;
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sendMessage();
}
```

Note: `sendMessage()` reads the textarea via `getMessageInput()` and clears it on success, exactly like `triggerSportsAnalysis` in `core/sports.ts`. Check `core/messaging.ts` does not import `core/quick-actions.ts` (avoid a cycle); it must not.

- [ ] **Step 6: Run tests, typecheck, lint**

Run: `cd web && npx vitest run tests/component/QuickActionForm.test.ts tests/component/QuickActionsBar.test.ts tests/unit/quick-actions.test.ts && npx tsc --noEmit && npx eslint src tests --max-warnings 0`
Expected: PASS, exit 0

- [ ] **Step 7: Commit**

```bash
git add web/src/components/QuickActionForm.ts web/src/styles/components/quick-actions.css web/src/core/quick-actions.ts web/tests/component/QuickActionForm.test.ts
git commit -m "feat(web): quick-action field form and one-tap send"
```

---

### Task 7: Mount the bar in sports and language programs + header gear button

**Files:**
- Modify: `web/src/core/sports.ts:163-250, 327-360`
- Modify: `web/src/core/language.ts` (same structure: `navigateToLanguageProgram` ~163-250, `leaveLanguageView` ~329)
- Modify: `web/src/components/SportsDashboard.ts:253-283`, `web/src/components/LanguageDashboard.ts:237-263`
- Modify: `web/src/core/quick-actions.ts` (`openQuickActionsEditor` stub for the gear button; real editor in Task 8)
- Test: `web/tests/component/ChatHeader.test.ts` untouched; add `web/tests/unit/quick-actions-mount.test.ts`

**Interfaces:**
- `renderSportsProgramHeader(program, onBack, onReset, onQuickActions: () => void)`; `renderLanguageProgramHeader(program, onBack, onReset, onQuickActions: () => void)`.
- Produces in core: `openQuickActionsEditor(draft?: Partial<QuickAction>): void` (body implemented in Task 8), `getQuickActionsContext(): QuickActionsContext | null`.

- [ ] **Step 1: Write the failing mount test**

```ts
// web/tests/unit/quick-actions-mount.test.ts
/**
 * mount/unmount of the quick-actions bar and the body marker class.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  mountQuickActionsBar,
  unmountQuickActionsBar,
  getQuickActionsContext,
} from '@/core/quick-actions';

describe('quick actions mount', () => {
  beforeEach(() => {
    document.body.className = '';
    document.body.innerHTML = `
      <div class="input-area"><div class="input-wrapper">
        <div id="quick-actions-bar" class="quick-actions-bar hidden"></div>
        <div id="input-container"><textarea id="message-input"></textarea></div>
      </div></div>`;
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
  });

  it('mount renders chips, shows the bar and marks body; unmount hides and unmarks', () => {
    mountQuickActionsBar({
      namespace: 'sports',
      programId: 'pushups',
      actions: [{ id: 'a', emoji: '📋', label: 'Plan', body: 'Plan.', fields: [] }],
      save: vi.fn(),
    });
    const bar = document.getElementById('quick-actions-bar')!;
    expect(bar.classList.contains('hidden')).toBe(false);
    expect(bar.querySelectorAll('.quick-action-chip').length).toBe(1);
    expect(document.body.classList.contains('has-quick-actions')).toBe(true);
    expect(getQuickActionsContext()?.programId).toBe('pushups');

    unmountQuickActionsBar();
    expect(bar.classList.contains('hidden')).toBe(true);
    expect(document.body.classList.contains('has-quick-actions')).toBe(false);
    expect(getQuickActionsContext()).toBeNull();
  });

  it('mount with zero actions keeps the bar hidden', () => {
    mountQuickActionsBar({ namespace: 'language', programId: 'es', actions: [], save: vi.fn() });
    expect(document.getElementById('quick-actions-bar')!.classList.contains('hidden')).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/quick-actions-mount.test.ts`
Expected: FAIL (`getQuickActionsContext` not exported)

- [ ] **Step 3: Add `getQuickActionsContext` and an editor entry point stub**

In `web/src/core/quick-actions.ts` add:

```ts
export function getQuickActionsContext(): QuickActionsContext | null {
  return current;
}

/** Open the per-program editor (implemented in Task 8). */
export function openQuickActionsEditor(draft?: Partial<QuickAction>): void {
  log.debug('openQuickActionsEditor', { hasDraft: Boolean(draft) });
}
```

- [ ] **Step 4: Header gear button (sports)**

In `web/src/components/SportsDashboard.ts`, change `renderSportsProgramHeader` to accept a fourth parameter `onQuickActions: () => void` and build a second button before `renderChatHeader`:

```ts
  const quickActionsBtn = document.createElement('button');
  quickActionsBtn.className = 'sports-reset-btn program-quick-actions-btn';
  quickActionsBtn.title = 'Quick actions';
  quickActionsBtn.setAttribute('aria-label', 'Edit quick actions');
  quickActionsBtn.innerHTML = `${SLIDERS_ICON}<span>Quick actions</span>`;
  quickActionsBtn.addEventListener('click', onQuickActions);
```

and pass `actions: [quickActionsBtn, resetBtn]`. Add `SLIDERS_ICON` to the icons import.

Do the same in `web/src/components/LanguageDashboard.ts` (`renderLanguageProgramHeader`), using class `language-reset-btn program-quick-actions-btn`.

Add to `quick-actions.css` (editor section placeholder stays for Task 8):

```css
/* Header button: icon-only on mobile to save width */
@media (max-width: 768px) {
    .program-quick-actions-btn span {
        display: none;
    }
}
```

- [ ] **Step 5: Mount/unmount in sports navigation**

In `web/src/core/sports.ts`:

Import:

```ts
import { mountQuickActionsBar, unmountQuickActionsBar, openQuickActionsEditor } from './quick-actions';
import type { QuickAction } from '../types/api';
```

In `navigateToSportsProgram`, inside `if (program) { ... }` replace the `renderSportsProgramHeader(...)` call with:

```ts
      renderSportsProgramHeader(
        program,
        () => navigateToSports(),
        () => handleProgramReset(programId),
        () => openQuickActionsEditor(),
      );
      mountQuickActionsBar({
        namespace: 'sports',
        programId,
        actions: program.quick_actions ?? [],
        save: (actions: QuickAction[]) => saveSportsQuickActions(programId, actions),
      });
```

and in the `else` branch (no program found) call `unmountQuickActionsBar();` after `renderChatHeader(null);`.

Add a helper near the CRUD section:

```ts
/** Persist quick actions and refresh the cached program list. */
async function saveSportsQuickActions(programId: string, actions: QuickAction[]): Promise<QuickAction[]> {
  const updated = await sports.updateQuickActions(programId, actions);
  const store = useStore.getState();
  const programs = store.sportsPrograms ?? [];
  store.setSportsPrograms(programs.map((p) => (p.id === updated.id ? updated : p)));
  return updated.quick_actions;
}
```

In `navigateToSports` (list view), right after `hideInputArea();` add `unmountQuickActionsBar();`. In `leaveSportsView`, add `unmountQuickActionsBar();` right after `renderChatHeader(null);`.

- [ ] **Step 6: Same for language**

Mirror Step 5 in `web/src/core/language.ts`: import from `./quick-actions`, pass `() => openQuickActionsEditor()` as the fourth argument to `renderLanguageProgramHeader`, mount with `namespace: 'language'` and a `saveLanguageQuickActions` helper using `language.updateQuickActions` + `setLanguagePrograms`, and unmount in `navigateToLanguage` (after `hideInputArea()`) and `leaveLanguageView` (after `renderChatHeader(null)`).

- [ ] **Step 7: Also unmount when a normal conversation is opened**

Search for the place that opens a regular conversation and resets program state (grep `leaveSportsView\|leaveLanguageView` in `web/src/core/conversation.ts` and `web/src/core/init.ts`). Those call sites already call the `leave*View` functions, which now unmount. Confirm with: `cd web && grep -rn "leaveSportsView()" src | wc -l` (≥ 1) and no other path renders the composer for a non-program conversation without going through them. If one exists, add `unmountQuickActionsBar()` there.

- [ ] **Step 8: Run tests, typecheck, lint, build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx eslint src tests --max-warnings 0 && cd .. && make build > /tmp/build.log 2>&1; echo "exit=$?"`
Expected: PASS; `exit=0`

- [ ] **Step 9: Manual smoke in the browser (dev)**

Run `make dev`, open a sports program: chips appear above the composer; tapping "Plan today" opens the form, Send posts the composed message and the trainer replies; on a 375 px wide viewport the bar hides while typing and while streaming. Fix anything off before committing.

- [ ] **Step 10: Commit**

```bash
git add web/src/core/sports.ts web/src/core/language.ts web/src/components/SportsDashboard.ts web/src/components/LanguageDashboard.ts web/src/core/quick-actions.ts web/src/styles/components/quick-actions.css web/tests/unit/quick-actions-mount.test.ts
git commit -m "feat(web): show quick-actions bar in sports and language programs with header entry point"
```

---

### Task 8: Quick actions editor

**Files:**
- Create: `web/src/components/QuickActionsEditor.ts`
- Modify: `web/src/styles/components/quick-actions.css` (editor section)
- Modify: `web/src/core/quick-actions.ts` (`openQuickActionsEditor` real implementation)
- Test: `web/tests/component/QuickActionsEditor.test.ts`

**Interfaces:**
- Produces: `showQuickActionsEditor(opts: { actions: QuickAction[]; initialDraft?: Partial<QuickAction>; onSave: (actions: QuickAction[]) => Promise<void> }): void`, `closeQuickActionsEditor(): void`, `newQuickActionId(): string`.
- Reorder uses up/down buttons (works on touch; HTML5 drag does not on iOS). This replaces the spec's "drag reorder".

- [ ] **Step 1: Write the failing component tests**

```ts
// web/tests/component/QuickActionsEditor.test.ts
/**
 * Component tests for the quick-actions editor modal.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showQuickActionsEditor, closeQuickActionsEditor } from '@/components/QuickActionsEditor';
import type { QuickAction } from '@/types/api';

const a: QuickAction = { id: 'a', emoji: '📋', label: 'Plan today', body: 'Plan.', fields: ['Comments'] };
const b: QuickAction = { id: 'b', emoji: '📊', label: 'Log', body: 'Log.', fields: [] };

const q = <T extends Element>(sel: string): T => document.querySelector<T>(sel)!;

describe('QuickActionsEditor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => closeQuickActionsEditor());

  it('lists actions in order with edit/delete/move controls', () => {
    showQuickActionsEditor({ actions: [a, b], onSave: vi.fn() });
    const rows = document.querySelectorAll('.qa-editor-row');
    expect(rows.length).toBe(2);
    expect(rows[0].querySelector('.qa-editor-row-label')!.textContent).toBe('Plan today');
    expect(rows[0].querySelector('.qa-editor-move-up')).not.toBeNull();
    expect(rows[0].querySelector('.qa-editor-delete')).not.toBeNull();
  });

  it('move down reorders and Save sends the new order', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    showQuickActionsEditor({ actions: [a, b], onSave });
    (document.querySelectorAll('.qa-editor-move-down')[0] as HTMLButtonElement).click();
    q<HTMLButtonElement>('.qa-editor-save').click();
    await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].map((x: QuickAction) => x.id)).toEqual(['b', 'a']);
  });

  it('delete removes the row', () => {
    showQuickActionsEditor({ actions: [a, b], onSave: vi.fn() });
    (document.querySelectorAll('.qa-editor-delete')[0] as HTMLButtonElement).click();
    expect(document.querySelectorAll('.qa-editor-row').length).toBe(1);
    expect(q('.qa-editor-row-label').textContent).toBe('Log');
  });

  it('Add opens the detail form; filling it and pressing Done appends a new action', () => {
    showQuickActionsEditor({ actions: [a], onSave: vi.fn() });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLInputElement>('.qa-detail-label').value = 'Week overview';
    q<HTMLTextAreaElement>('.qa-detail-body').value = 'Summarize the week.';
    q<HTMLInputElement>('.qa-detail-field-input').value = 'Notes';
    q<HTMLButtonElement>('.qa-detail-field-add').click();
    q<HTMLButtonElement>('.qa-detail-done').click();
    const labels = [...document.querySelectorAll('.qa-editor-row-label')].map((e) => e.textContent);
    expect(labels).toEqual(['Plan today', 'Week overview']);
  });

  it('Done with an empty label or body shows an inline error and stays open', () => {
    showQuickActionsEditor({ actions: [], onSave: vi.fn() });
    q<HTMLButtonElement>('.qa-editor-add').click();
    q<HTMLButtonElement>('.qa-detail-done').click();
    expect(q('.qa-detail-error').textContent).toContain('Label and body are required');
    expect(document.querySelector('.qa-detail')).not.toBeNull();
  });

  it('initialDraft opens directly in the detail form prefilled', () => {
    showQuickActionsEditor({ actions: [a], initialDraft: { body: 'Saved text' }, onSave: vi.fn() });
    expect(q<HTMLTextAreaElement>('.qa-detail-body').value).toBe('Saved text');
  });

  it('enforces the 12-action cap by disabling Add', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...a, id: `id${i}` }));
    showQuickActionsEditor({ actions: many, onSave: vi.fn() });
    expect(q<HTMLButtonElement>('.qa-editor-add').disabled).toBe(true);
  });

  it('Save failure keeps the editor open', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('boom'));
    showQuickActionsEditor({ actions: [a], onSave });
    q<HTMLButtonElement>('.qa-editor-save').click();
    await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
    await Promise.resolve();
    expect(document.querySelector('.qa-editor')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/component/QuickActionsEditor.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Create the editor component**

```ts
// web/src/components/QuickActionsEditor.ts
/**
 * Editor modal for a program's quick actions: list (reorder via up/down,
 * edit, delete, add) + a detail form (emoji, label, body, fields).
 * Presentation + local draft state only; persistence is the caller's onSave.
 */
import type { QuickAction } from '../types/api';
import { escapeHtml, clearElement } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import { CLOSE_ICON, DELETE_ICON, EDIT_ICON, PLUS_ICON, CHEVRON_DOWN_ICON, SLIDERS_ICON } from '../utils/icons';
import { toast } from './Toast';

export const QUICK_ACTIONS_MAX = 12;
export const QUICK_ACTION_FIELDS_MAX = 6;
const LABEL_MAX = 40;
const BODY_MAX = 2000;

const EMOJIS = ['📋', '📊', '🏋️', '🏃', '🚴', '🧗', '🧘', '📖', '🧠', '✍️', '🗣️', '🔁', '📅', '✅', '⭐', '❤️'];

export function newQuickActionId(): string {
  return Math.random().toString(36).slice(2, 10);
}

interface EditorOptions {
  actions: QuickAction[];
  initialDraft?: Partial<QuickAction>;
  onSave: (actions: QuickAction[]) => Promise<void>;
}

let overlay: HTMLElement | null = null;
let keydownHandler: ((e: KeyboardEvent) => void) | null = null;

export function closeQuickActionsEditor(): void {
  if (keydownHandler) document.removeEventListener('keydown', keydownHandler);
  keydownHandler = null;
  overlay?.remove();
  overlay = null;
}

export function showQuickActionsEditor(opts: EditorOptions): void {
  closeQuickActionsEditor();
  const draftList: QuickAction[] = opts.actions.map((a) => ({ ...a, fields: [...a.fields] }));

  overlay = document.createElement('div');
  overlay.className = 'qa-editor-overlay';
  const modal = document.createElement('div');
  modal.className = 'qa-editor';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.innerHTML = `
    <div class="qa-editor-header">
      <div class="qa-editor-title-row"><span class="qa-editor-icon">${SLIDERS_ICON}</span><h2>Quick actions</h2></div>
      <button type="button" class="qa-editor-close" title="Close">${CLOSE_ICON}</button>
    </div>
    <div class="qa-editor-body"></div>
    <div class="qa-editor-footer">
      <button type="button" class="qa-editor-cancel">Cancel</button>
      <button type="button" class="qa-editor-save">Save</button>
    </div>`;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const body = modal.querySelector<HTMLElement>('.qa-editor-body')!;
  const footer = modal.querySelector<HTMLElement>('.qa-editor-footer')!;

  const renderList = (): void => {
    footer.hidden = false;
    clearElement(body);
    const list = document.createElement('div');
    list.className = 'qa-editor-list';
    if (draftList.length === 0) {
      list.innerHTML = `<p class="qa-editor-empty">No quick actions yet.</p>`;
    }
    draftList.forEach((a, i) => {
      const row = document.createElement('div');
      row.className = 'qa-editor-row';
      row.dataset.index = String(i);
      row.innerHTML = `
        <span class="qa-editor-row-emoji">${escapeHtml(a.emoji)}</span>
        <span class="qa-editor-row-label">${escapeHtml(a.label)}</span>
        <span class="qa-editor-row-fields">${a.fields.length ? `${a.fields.length} field${a.fields.length > 1 ? 's' : ''}` : ''}</span>
        <button type="button" class="btn-icon qa-editor-move-up" title="Move up" ${i === 0 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-move-down" title="Move down" ${i === draftList.length - 1 ? 'disabled' : ''}>${CHEVRON_DOWN_ICON}</button>
        <button type="button" class="btn-icon qa-editor-edit" title="Edit">${EDIT_ICON}</button>
        <button type="button" class="btn-icon qa-editor-delete" title="Delete">${DELETE_ICON}</button>`;
      list.appendChild(row);
    });
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'qa-editor-add';
    add.innerHTML = `${PLUS_ICON}<span>Add quick action</span>`;
    add.disabled = draftList.length >= QUICK_ACTIONS_MAX;
    body.appendChild(list);
    body.appendChild(add);

    list.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      const row = target.closest<HTMLElement>('.qa-editor-row');
      if (!row) return;
      const i = Number(row.dataset.index);
      if (target.closest('.qa-editor-move-up') && i > 0) {
        [draftList[i - 1], draftList[i]] = [draftList[i], draftList[i - 1]];
        renderList();
      } else if (target.closest('.qa-editor-move-down') && i < draftList.length - 1) {
        [draftList[i + 1], draftList[i]] = [draftList[i], draftList[i + 1]];
        renderList();
      } else if (target.closest('.qa-editor-delete')) {
        draftList.splice(i, 1);
        renderList();
      } else if (target.closest('.qa-editor-edit')) {
        renderDetail(draftList[i], i);
      }
    });
    add.addEventListener('click', () => renderDetail({}, null));
  };

  const renderDetail = (initial: Partial<QuickAction>, index: number | null): void => {
    footer.hidden = true;
    clearElement(body);
    const fields = [...(initial.fields ?? [])];
    let emoji = initial.emoji ?? EMOJIS[0];
    const detail = document.createElement('div');
    detail.className = 'qa-detail';
    detail.innerHTML = `
      <div class="qa-detail-row">
        <div class="qa-detail-emoji-wrapper">
          <button type="button" class="qa-detail-emoji-trigger" title="Choose icon">${escapeHtml(emoji)}</button>
          <div class="qa-detail-emoji-popover"><div class="qa-detail-emoji-grid"></div></div>
        </div>
        <input type="text" class="qa-detail-label" placeholder="Label (shown on the chip)" maxlength="${LABEL_MAX}" value="${escapeHtml(initial.label ?? '')}" />
      </div>
      <textarea class="qa-detail-body" rows="4" maxlength="${BODY_MAX}" placeholder="What to send">${escapeHtml(initial.body ?? '')}</textarea>
      <div class="qa-detail-fields">
        <div class="qa-detail-fields-title">Ask for (optional)</div>
        <div class="qa-detail-field-list"></div>
        <div class="qa-detail-field-add-row">
          <input type="text" class="qa-detail-field-input" placeholder="e.g. Hang time (s)" maxlength="40" />
          <button type="button" class="qa-detail-field-add">${PLUS_ICON}</button>
        </div>
      </div>
      <div class="qa-detail-error" role="alert"></div>
      <div class="qa-detail-actions">
        <button type="button" class="qa-detail-back">Back</button>
        <button type="button" class="qa-detail-done">Done</button>
      </div>`;
    body.appendChild(detail);

    const grid = detail.querySelector<HTMLElement>('.qa-detail-emoji-grid')!;
    grid.innerHTML = EMOJIS.map((e) => `<button type="button" class="qa-detail-emoji-option" data-emoji="${e}">${e}</button>`).join('');
    const trigger = detail.querySelector<HTMLButtonElement>('.qa-detail-emoji-trigger')!;
    const popover = detail.querySelector<HTMLElement>('.qa-detail-emoji-popover')!;
    trigger.addEventListener('click', (e) => { e.stopPropagation(); popover.classList.toggle('open'); });
    grid.addEventListener('click', (e) => {
      const opt = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-emoji-option');
      if (!opt?.dataset.emoji) return;
      emoji = opt.dataset.emoji;
      trigger.textContent = emoji;
      popover.classList.remove('open');
    });

    const fieldList = detail.querySelector<HTMLElement>('.qa-detail-field-list')!;
    const fieldInput = detail.querySelector<HTMLInputElement>('.qa-detail-field-input')!;
    const fieldAdd = detail.querySelector<HTMLButtonElement>('.qa-detail-field-add')!;
    const renderFields = (): void => {
      fieldList.innerHTML = fields
        .map((f, i) => `<span class="qa-detail-field-chip">${escapeHtml(f)}<button type="button" class="qa-detail-field-remove" data-index="${i}" title="Remove">${CLOSE_ICON}</button></span>`)
        .join('');
      fieldAdd.disabled = fields.length >= QUICK_ACTION_FIELDS_MAX;
    };
    renderFields();
    const addField = (): void => {
      const v = fieldInput.value.trim();
      if (!v || fields.length >= QUICK_ACTION_FIELDS_MAX) return;
      fields.push(v);
      fieldInput.value = '';
      renderFields();
    };
    fieldAdd.addEventListener('click', addField);
    fieldInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addField(); } });
    fieldList.addEventListener('click', (e) => {
      const btn = (e.target as HTMLElement).closest<HTMLElement>('.qa-detail-field-remove');
      if (!btn) return;
      fields.splice(Number(btn.dataset.index), 1);
      renderFields();
    });

    detail.querySelector('.qa-detail-back')!.addEventListener('click', renderList);
    detail.querySelector('.qa-detail-done')!.addEventListener('click', () => {
      const label = detail.querySelector<HTMLInputElement>('.qa-detail-label')!.value.trim();
      const text = detail.querySelector<HTMLTextAreaElement>('.qa-detail-body')!.value.trim();
      const error = detail.querySelector<HTMLElement>('.qa-detail-error')!;
      if (!label || !text) {
        error.textContent = 'Label and body are required.';
        return;
      }
      const action: QuickAction = { id: initial.id ?? newQuickActionId(), emoji, label, body: text, fields: [...fields] };
      if (index === null) draftList.push(action);
      else draftList[index] = action;
      renderList();
    });
    detail.querySelector<HTMLInputElement>('.qa-detail-label')!.focus();
  };

  modal.querySelector('.qa-editor-close')!.addEventListener('click', closeQuickActionsEditor);
  modal.querySelector('.qa-editor-cancel')!.addEventListener('click', closeQuickActionsEditor);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeQuickActionsEditor(); });
  const saveBtn = modal.querySelector<HTMLButtonElement>('.qa-editor-save')!;
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    try {
      await opts.onSave(draftList);
      closeQuickActionsEditor();
    } catch {
      toast.error('Failed to save quick actions.');
      saveBtn.disabled = false;
    }
  });
  keydownHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') { closeQuickActionsEditor(); return; }
    trapTabKey(modal, e);
  };
  document.addEventListener('keydown', keydownHandler);

  if (opts.initialDraft) renderDetail(opts.initialDraft, null);
  else renderList();
}
```

The move-up button reuses `CHEVRON_DOWN_ICON` rotated via CSS (`.qa-editor-move-up svg { transform: rotate(180deg); }`).

- [ ] **Step 4: Editor styles**

Replace the `/* Editor (Task 7) */` placeholder in `quick-actions.css` with:

```css
/* ----------------------------------------
   Editor modal
   ---------------------------------------- */

.qa-editor-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.5);
}

.qa-editor {
    width: 90%;
    max-width: 560px;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
}

.qa-editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
}

.qa-editor-title-row { display: flex; align-items: center; gap: var(--space-2); }
.qa-editor-title-row h2 { margin: 0; font-size: var(--font-size-xl); font-weight: 600; }
.qa-editor-icon svg { width: 18px; height: 18px; color: var(--text-secondary); }

.qa-editor-close {
    display: inline-flex;
    padding: var(--space-1);
    border: 0;
    background: transparent;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    cursor: pointer;
}
.qa-editor-close svg { width: 18px; height: 18px; }
.qa-editor-close:hover { background: var(--bg-hover); color: var(--text-primary); }

.qa-editor-body { padding: var(--space-4); overflow-y: auto; flex: 1; }

.qa-editor-footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--border);
}

.qa-editor-cancel, .qa-editor-save, .qa-detail-back, .qa-detail-done {
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--font-size-sm);
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition-fast);
}
.qa-editor-cancel:hover, .qa-detail-back:hover { background: var(--bg-hover); }
.qa-editor-save, .qa-detail-done { background: var(--accent); border-color: transparent; color: #fff; }
.qa-editor-save:hover, .qa-detail-done:hover { background: var(--accent-hover); }
.qa-editor-save:disabled { opacity: 0.6; cursor: default; }

.qa-editor-list { display: flex; flex-direction: column; gap: var(--space-1); }
.qa-editor-row {
    display: grid;
    grid-template-columns: auto 1fr auto auto auto auto auto;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg-primary);
}
.qa-editor-row-label { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qa-editor-row-fields { font-size: var(--font-size-sm); color: var(--text-secondary); }
.qa-editor-move-up svg { transform: rotate(180deg); }
.qa-editor-empty { color: var(--text-secondary); text-align: center; padding: var(--space-4); }
.qa-editor-add {
    display: inline-flex; align-items: center; gap: var(--space-2);
    margin-top: var(--space-3); padding: var(--space-2) var(--space-3);
    border: 1px dashed var(--border); border-radius: var(--radius-md);
    background: transparent; color: var(--text-secondary); cursor: pointer;
}
.qa-editor-add:disabled { opacity: 0.5; cursor: default; }
.qa-detail { display: flex; flex-direction: column; gap: var(--space-3); }
.qa-detail-row { display: flex; gap: var(--space-2); align-items: center; }
.qa-detail-label, .qa-detail-body, .qa-detail-field-input {
    width: 100%; padding: var(--space-2); font: inherit; font-size: var(--font-size-ui);
    background: var(--bg-primary); color: var(--text-primary);
    border: 1px solid var(--border); border-radius: var(--radius-md);
}
.qa-detail-body { resize: vertical; min-height: 96px; }
.qa-detail-emoji-wrapper { position: relative; }
.qa-detail-emoji-trigger { font-size: 1.25rem; width: 40px; height: 40px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-primary); cursor: pointer; }
.qa-detail-emoji-popover { display: none; position: absolute; top: calc(100% + 4px); left: 0; z-index: 2; padding: var(--space-2); background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius-md); }
.qa-detail-emoji-popover.open { display: block; }
.qa-detail-emoji-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 2px; }
.qa-detail-emoji-option { font-size: 1.1rem; padding: 4px; background: transparent; border: 0; border-radius: var(--radius-sm); cursor: pointer; }
.qa-detail-emoji-option:hover { background: var(--bg-hover); }
.qa-detail-fields-title { font-size: var(--font-size-sm); color: var(--text-secondary); margin-bottom: var(--space-1); }
.qa-detail-field-list { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-bottom: var(--space-2); }
.qa-detail-field-chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px var(--space-2); border-radius: 999px; background: var(--bg-tertiary); font-size: var(--font-size-sm); }
.qa-detail-field-remove { border: 0; background: transparent; cursor: pointer; display: inline-flex; color: var(--text-secondary); }
.qa-detail-field-remove svg { width: 12px; height: 12px; }
.qa-detail-field-add-row { display: flex; gap: var(--space-2); }
.qa-detail-field-add { padding: 0 var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-tertiary); cursor: pointer; }
.qa-detail-error { color: var(--color-error-500); font-size: var(--font-size-sm); min-height: 1.2em; }
.qa-detail-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
@media (max-width: 768px) {
    .qa-editor { width: 100vw; max-width: none; height: 100dvh; border-radius: 0; }
    .qa-editor-row { grid-template-columns: auto 1fr auto auto auto; }
    .qa-editor-row-fields { display: none; }
}
```

- [ ] **Step 5: Real `openQuickActionsEditor` in core**

In `web/src/core/quick-actions.ts`, import `showQuickActionsEditor` and replace the stub:

```ts
export function openQuickActionsEditor(draft?: Partial<QuickAction>): void {
  const ctx = current;
  if (!ctx) return;
  showQuickActionsEditor({
    actions: ctx.actions,
    initialDraft: draft,
    onSave: async (actions) => {
      const saved = await ctx.save(actions);
      if (current && current.programId === ctx.programId) {
        current.actions = saved;
        renderCurrent();
      }
      toast.success('Quick actions saved.');
    },
  });
}
```

- [ ] **Step 6: Run tests, typecheck, lint**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx eslint src tests --max-warnings 0`
Expected: PASS, exit 0

- [ ] **Step 7: Commit**

```bash
git add web/src/components/QuickActionsEditor.ts web/src/styles/components/quick-actions.css web/src/core/quick-actions.ts web/tests/component/QuickActionsEditor.test.ts
git commit -m "feat(web): quick-actions editor (add, edit, reorder, delete, save)"
```

---

### Task 9: "Save as quick action" on user messages

**Files:**
- Modify: `web/src/components/messages/actions.ts:175-230`
- Modify: `web/src/core/quick-actions.ts` (`initQuickActions` listens for the event)
- Modify: `web/src/styles/components/quick-actions.css` (hide button outside programs)
- Test: `web/tests/component/Messages.test.ts` (append) or a new `web/tests/component/MessageActionsQuickAction.test.ts`

**Interfaces:**
- New user-message button `.message-save-quick-action-btn`; dispatches `document` CustomEvent `message:save-quick-action` with `{ messageId }`. Core handler looks up the message text from `useStore.getState().getMessages(convId)` and calls `openQuickActionsEditor({ body })`.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/component/MessageActionsQuickAction.test.ts
import { describe, it, expect, vi } from 'vitest';
import { createMessageActions } from '@/components/messages/actions';

describe('message actions - save as quick action', () => {
  it('user messages get the button and it dispatches message:save-quick-action', () => {
    const actions = createMessageActions('m1', '2026-09-04T10:00:00Z', undefined, undefined, 'user');
    const btn = actions.querySelector<HTMLButtonElement>('.message-save-quick-action-btn');
    expect(btn).not.toBeNull();
    const handler = vi.fn();
    document.addEventListener('message:save-quick-action', handler);
    btn!.click();
    expect(handler).toHaveBeenCalledTimes(1);
    expect((handler.mock.calls[0][0] as CustomEvent).detail).toEqual({ messageId: 'm1' });
  });

  it('assistant messages do not get the button', () => {
    const actions = createMessageActions('m2', '2026-09-04T10:00:00Z', undefined, undefined, 'assistant');
    expect(actions.querySelector('.message-save-quick-action-btn')).toBeNull();
  });
});
```

Check the exact parameter order of `createMessageActions` in `actions.ts:175` (`messageId, createdAt, sources, generatedImages, role, language`) and adjust the calls if it differs.

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/component/MessageActionsQuickAction.test.ts`
Expected: FAIL (button null)

- [ ] **Step 3: Add the button and handler**

In `web/src/components/messages/actions.ts`, next to `showEditButton`, add `const showSaveQuickActionButton = role === 'user';` and inside the `.message-actions-buttons` template right after the edit button line:

```ts
      ${showSaveQuickActionButton ? `<button class="message-save-quick-action-btn" title="Save as quick action">${PIN_ICON}</button>` : ''}
```

Add `PIN_ICON` to the icons import. After `if (showEditButton) attachEditHandler(...)` add `if (showSaveQuickActionButton) attachSaveQuickActionHandler(actions, messageId);` and define:

```ts
function attachSaveQuickActionHandler(actions: HTMLElement, messageId: string): void {
  actions.querySelector('.message-save-quick-action-btn')?.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('message:save-quick-action', { detail: { messageId } }));
  });
}
```

In `quick-actions.css`, hide it outside program conversations:

```css
/* "Save as quick action" only makes sense inside a program conversation */
.message-save-quick-action-btn { display: none; }
body.has-quick-actions .message-save-quick-action-btn { display: inline-flex; }
```

In `web/src/core/quick-actions.ts` `initQuickActions()`, add:

```ts
  document.addEventListener('message:save-quick-action', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    const convId = useStore.getState().currentConversation?.id;
    if (!convId || !current) return;
    const message = useStore.getState().getMessages(convId).find((m) => m.id === messageId);
    if (!message) return;
    openQuickActionsEditor({ body: message.content });
  });
```

- [ ] **Step 4: Run tests, typecheck, lint**

Run: `cd web && npx vitest run && npx tsc --noEmit && npx eslint src tests --max-warnings 0`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/messages/actions.ts web/src/core/quick-actions.ts web/src/styles/components/quick-actions.css web/tests/component/MessageActionsQuickAction.test.ts
git commit -m "feat(web): save a sent message as a quick action from the message menu"
```

---

### Task 10: E2E and visual tests

**Files:**
- Create: `web/tests/e2e/quick-actions.spec.ts`
- Create: `web/tests/visual/quick-actions.visual.ts`

**Interfaces:**
- Consumes: `/test/set-sports-programs` seeding endpoint (accepts full program dicts, so include `quick_actions`), hash route `/#/sports/<id>`, mock LLM echoing `message[:100]` with a prefix.

- [ ] **Step 1: Build the frontend**

Run: `make build > /tmp/build.log 2>&1; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 2: Write the E2E spec**

```ts
// web/tests/e2e/quick-actions.spec.ts
/**
 * E2E: program quick actions (chip bar, field form, editor, save-from-message).
 */
import { test, expect } from '../global-setup';

const PROGRAMS = [
  {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '💪',
    created_at: '2026-01-01T00:00:00',
    quick_actions: [
      { id: 'plan', emoji: '📋', label: 'Plan today', body: 'Plan my session please.', fields: [] },
      { id: 'log', emoji: '📊', label: 'Log & review', body: 'Review my session.', fields: ['Hang time (s)', 'Comments'] },
    ],
  },
];

async function openProgram(page: import('@playwright/test').Page): Promise<void> {
  await page.request.post('/test/set-sports-programs', { data: { programs: PROGRAMS } });
  await page.goto('/#/sports/pushups');
  await page.waitForSelector('.sports-program-header');
  // The auto session-start message gets a mock reply; wait for it to finish
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
}

test.describe('Quick actions - desktop', () => {
  test('bar shows chips and a no-field chip sends its body', async ({ page }) => {
    await openProgram(page);
    const chips = page.locator('.quick-action-chip');
    await expect(chips).toHaveCount(2);
    await chips.nth(0).click();
    await expect(page.locator('.message.user').last()).toContainText('Plan my session please.');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  });

  test('a field chip opens the form and sends Label: value lines', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const form = page.locator('.quick-action-form');
    await expect(form).toBeVisible();
    await form.locator('textarea').nth(0).fill('54');
    await form.locator('textarea').nth(1).fill('felt strong');
    await form.locator('.quick-action-form-send').click();
    const last = page.locator('.message.user').last();
    await expect(last).toContainText('Review my session.');
    await expect(last).toContainText('Hang time (s): 54');
    await expect(last).toContainText('Comments: felt strong');
  });

  test('editor adds an action that appears as a chip', async ({ page }) => {
    await openProgram(page);
    await page.locator('.program-quick-actions-btn').click();
    await page.locator('.qa-editor-add').click();
    await page.fill('.qa-detail-label', 'Week overview');
    await page.fill('.qa-detail-body', 'Summarize the week.');
    await page.locator('.qa-detail-done').click();
    await page.locator('.qa-editor-save').click();
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
    await expect(page.locator('.quick-action-chip').nth(2)).toContainText('Week overview');
    // Persisted: reload and check again
    await page.reload();
    await page.waitForSelector('.sports-program-header');
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
  });

  test('save as quick action prefills the editor with the message', async ({ page }) => {
    await openProgram(page);
    await page.fill('#message-input', 'Business as usual please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
    const userMsg = page.locator('.message.user').last();
    await userMsg.hover();
    await userMsg.locator('.message-save-quick-action-btn').click({ force: true });
    await expect(page.locator('.qa-detail-body')).toHaveValue('Business as usual please');
  });

  test('bar is absent in a normal conversation', async ({ page }) => {
    await openProgram(page);
    await page.locator('.chat-header-back').click();
    await page.click('#new-chat-btn');
    await expect(page.locator('#quick-actions-bar')).toBeHidden();
  });
});

test.describe('Quick actions - mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('bar hides while typing and returns when the composer is cleared', async ({ page }) => {
    await openProgram(page);
    const bar = page.locator('#quick-actions-bar');
    await expect(bar).toBeVisible();
    await page.fill('#message-input', 'typing…');
    await expect(bar).toBeHidden();
    await page.fill('#message-input', '');
    await expect(bar).toBeVisible();
  });

  test('field form opens as a bottom sheet and sends', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const form = page.locator('.quick-action-form');
    await expect(form).toBeVisible();
    const box = await form.boundingBox();
    expect(box!.y + box!.height).toBeGreaterThan(800); // pinned to the bottom
    await form.locator('textarea').nth(0).fill('60');
    await form.locator('.quick-action-form-send').click();
    await expect(page.locator('.message.user').last()).toContainText('Hang time (s): 60');
  });
});
```

- [ ] **Step 3: Run the E2E spec (both browsers)**

Run: `cd web && timeout 600 npx playwright test tests/e2e/quick-actions.spec.ts; echo "exit=$?"`
Expected: `exit=0`. If a test fails, use the trace (`npx playwright show-trace`) to find the root cause; do not add waits blindly.

- [ ] **Step 4: Write the visual spec**

```ts
// web/tests/visual/quick-actions.visual.ts
/**
 * Visual regression: quick-actions bar, field form, editor.
 */
import { test, expect } from '../global-setup';

const PROGRAMS = [
  {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '💪',
    created_at: '2026-01-01T00:00:00',
    quick_actions: [
      { id: 'plan', emoji: '📋', label: 'Plan today', body: 'Plan.', fields: ['Comments'] },
      { id: 'log', emoji: '📊', label: 'Log & review', body: 'Log.', fields: ['Results', 'Comments'] },
    ],
  },
];

async function open(page: import('@playwright/test').Page): Promise<void> {
  await page.request.post('/test/set-sports-programs', { data: { programs: PROGRAMS } });
  await page.goto('/#/sports/pushups');
  await page.waitForSelector('.quick-action-chip');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  await page.waitForTimeout(300);
}

test.describe('Visual: Quick actions', () => {
  test('bar above composer', async ({ page }) => {
    await open(page);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-bar.png');
  });

  test('field form popover', async ({ page }) => {
    await open(page);
    await page.locator('.quick-action-chip').nth(1).click();
    await page.waitForTimeout(200);
    await expect(page.locator('.quick-action-form')).toHaveScreenshot('quick-actions-form.png');
  });

  test('editor list', async ({ page }) => {
    await open(page);
    await page.locator('.program-quick-actions-btn').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.qa-editor')).toHaveScreenshot('quick-actions-editor.png');
  });
});

test.describe('Visual: Quick actions mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('bar and bottom-sheet form', async ({ page }) => {
    await open(page);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-bar-mobile.png');
    await page.locator('.quick-action-chip').nth(1).click();
    await page.waitForTimeout(250);
    await expect(page).toHaveScreenshot('quick-actions-form-mobile.png');
  });
});
```

- [ ] **Step 5: Generate local baselines and run**

Run: `cd web && timeout 600 npx playwright test tests/visual/quick-actions.visual.ts --update-snapshots; timeout 600 npx playwright test tests/visual/quick-actions.visual.ts; echo "exit=$?"`
Expected: second run `exit=0`. Inspect the generated `*-darwin.png` files by opening them; the bar must sit inside the composer pill area with no clipped chips.

- [ ] **Step 6: Run the scroll-related suites**

Run: `cd web && timeout 600 npx playwright test tests/e2e/chat/streaming.spec.ts tests/e2e/mobile.spec.ts tests/e2e/pagination.spec.ts; echo "exit=$?"`
Expected: `exit=0` (the bar changes composer height; these cover auto-scroll and mobile keyboard paths).

- [ ] **Step 7: Commit**

```bash
git add web/tests/e2e/quick-actions.spec.ts web/tests/visual/quick-actions.visual.ts web/tests/visual/**/quick-actions-*-darwin.png
git commit -m "test(e2e): quick actions bar, form, editor and save-from-message on desktop and mobile"
```

---

### Task 11: Docs, full suite, Linux baselines

**Files:**
- Modify: `docs/features/ui-features.md`
- Modify: `.claude/rules/programs.md`
- Modify: `docs/superpowers/specs/2026-09-04-program-quick-actions-design.md` (status + reorder note)

- [ ] **Step 1: Document the feature**

Append to `docs/features/ui-features.md` a section:

```markdown
## Program Quick Actions

One-tap saved prompts in sports and language program conversations. A chip bar sits above
the composer; tapping a chip with no fields sends its body immediately, a chip with fields
opens a form (popover on desktop, bottom sheet on mobile) whose answers are appended as
`Label: value` lines under the body (empty fields omitted). Actions are edited per program
from the "Quick actions" button in the program header, or via "Save as quick action" on any
of your own messages.

### Storage

Actions live inside each program object in the namespace's `programs` K/V list — never
under `{program_id}:*`, which `program_context.py` injects into the prompt each turn.
Programs without a `quick_actions` key resolve to the namespace defaults
(`QUICK_ACTION_DEFAULTS` in `src/api/routes/program_quick_actions.py`). Corrupt entries are
dropped on read with a warning.

### Key Files

- `src/api/routes/program_quick_actions.py` — defaults, sanitization, `PUT /api/{ns}/programs/<id>/quick-actions`
- `web/src/core/quick-actions.ts` — composition, mount/visibility, send, editor glue
- `web/src/components/QuickActionsBar.ts`, `QuickActionForm.ts`, `QuickActionsEditor.ts`
- `web/src/styles/components/quick-actions.css`

### Behavior notes

- Mobile: the bar is visible only while the composer is empty and nothing is streaming.
- The bar lives inside `.input-wrapper` above the pill; `composer-height.ts` measures from
  its top when visible so the message list clears it.
- Sends go through `sendMessage()`; the composed text is an ordinary user message.
```

Add to `.claude/rules/programs.md` bullet list:

```markdown
- **Quick actions**: per-program saved prompts stored INSIDE the program object (`programs` KV list), shared route in `routes/program_quick_actions.py`; see [docs/features/ui-features.md](../../docs/features/ui-features.md#program-quick-actions).
```

Update the spec: `**Status:** Implemented 2026-09-04` and under "Creating and editing" note that reorder uses up/down buttons rather than drag (touch support).

- [ ] **Step 2: Full lint and test suite**

Run: `make lint > /tmp/lint.log 2>&1; echo "lint=$?"; make test > /tmp/test.log 2>&1; echo "test=$?"; cd web && npx vitest run > /tmp/fe.log 2>&1; echo "fe=$?"`
Expected: all three `=0`. Read the logs on any non-zero.

- [ ] **Step 3: Commit**

```bash
git add docs/features/ui-features.md .claude/rules/programs.md docs/superpowers/specs/2026-09-04-program-quick-actions-design.md
git commit -m "docs: program quick actions"
```

- [ ] **Step 4: Regenerate Linux visual baselines**

Invoke `/regen-baselines` (CI dispatch workflow) after pushing, and commit the resulting `*-linux.png` files for `quick-actions-*` and any changed `program-header-*` screenshots (the header gained a button).

- [ ] **Step 5: Real-device check**

On an iPhone (standalone PWA and Safari): open a program, confirm the bar sits above the composer with the keyboard closed, hides when typing, the message list clears the bar (no message hidden behind it), and the bottom-sheet form is fully visible above the home indicator. Record any deviation as a follow-up fix before deploying.
