# Program Self-Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A program coach proposes changes to its own quick actions and standing instructions - on a proposal card when it notices evidence, and as a per-item list from a Review button in the Quick actions sheet - and only the user's yes applies them.

**Architecture:** One service (`src/services/program_setup.py`) owns a program's setup: reading it, validating, describing, applying a `SetupChange`, fingerprints and the declined list. The in-the-moment path is an agent tool that files a `program_setup` proposal whose apply/decline call that service. The Review path is a structured-output model call (`src/services/program_review.py`) behind two program routes, rendered in the Quick actions editor; nothing it does touches the chat.

**Tech Stack:** Flask + APIFlask routes, Pydantic schemas, LangChain Gemini (`create_chat_model`), the proposals registry (`src/agent/proposals.py`), vanilla TS + Vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-11-program-self-tuning-design.md`

## Global Constraints

- Instruction keys (the only KV keys either path may change): sports `goals`, `preferences`, `routine`; language `profile`, `grammar`.
- Every suggestion carries evidence: 1-5 items, each starting with a `YYYY-MM-DD` date of a turn in that chat; no evidence, no suggestion.
- Declined = Decline / typed no on a card, or Reject in the Review list. An expired card is not a decline: the same fingerprint may be filed again at most once more, and not before 3 days after the expiry (`SETUP_REOFFER_AFTER_DAYS = 3`).
- A declined fingerprint is offered again only with evidence dated after the decline.
- The user's own requests keep working directly (no change to `kv_store` or the existing quick-action PUT route).
- Quick action limits are the existing schema's (`QuickActionItem`: label <= 40, body <= 2000, fields <= `QUICK_ACTION_MAX_FIELDS`, list <= `QUICK_ACTIONS_MAX_PER_PROGRAM`).
- Layers: routes -> helpers -> agent -> services -> db. The agent tool imports the service, never `src/api/routes`.
- Logs carry user ids, never emails; no prompt or message text beyond short excerpts.

## Review Focus

1. A card approved after the user already edited that quick action by hand (stale `edit`/`remove` target) - apply refuses with a plain reason, changes nothing (Task 1 test `test_edit_of_a_vanished_action_is_refused`).
2. A program still on default quick actions (no `quick_actions` key) - an `add` starts from the defaults, not an empty list (Task 1 test `test_add_starts_from_the_defaults`).
3. The Review model returns junk: unknown key, a fifth field, no evidence, a declined fingerprint - each item dropped, the rest shown (Task 3 test `test_invalid_and_declined_items_are_dropped`).
4. A tool call outside a program chat (a normal chat, a Command Center agent) - refused with a tool error, no proposal filed (Task 2 test `test_outside_a_program_chat_it_refuses`).
5. Instruction keys holding a non-JSON string (older coaches wrote prose) - the patch replaces the value only when it is a dict; a string value takes a `{"text": ...}` replace, shown before/after (Task 1 test `test_a_prose_instruction_is_replaced_whole`).

---

### Task 1: The setup service

**Files:**
- Create: `src/services/program_setup.py`
- Modify: `src/api/routes/program_quick_actions.py` (move `QUICK_ACTION_DEFAULTS`, `sanitize_quick_actions`, `resolve_quick_actions` into the service; the route imports them)
- Modify: `src/config.py` (`SETUP_REOFFER_AFTER_DAYS = 3`, `SETUP_DECLINED_MAX = 50`)
- Test: `tests/unit/test_program_setup.py`

**Interfaces:**
- Produces:
  - `INSTRUCTION_KEYS: dict[str, tuple[str, ...]]` (values from Global Constraints)
  - `@dataclass(frozen=True) class ProgramRef: namespace: str; program_id: str`
  - `program_for_conversation(conversation_id: str, user_id: str) -> ProgramRef | None` (via `PROGRAM_FEATURES[ns].program_column` on the conversation)
  - `class SetupChange(TypedDict, total=False)`: `target: Literal["quick_action", "instruction"]`; `op: Literal["add", "edit", "remove"]` (quick_action) ; `action_id: str`; `action: dict[str, object]` (a `QuickActionItem` dump; add/edit); `key: str`; `patch: dict[str, object]` (instruction: a JSON merge patch, `None` removes a field) ; `text: str` (instruction: replace a prose value)
  - `class ProgramSetup(TypedDict)`: `quick_actions: list[dict[str, object]]`; `instructions: dict[str, object]` (key -> parsed JSON, or the raw string)
  - `load_setup(user_id: str, ref: ProgramRef) -> ProgramSetup`
  - `validate_change(namespace: str, change: Mapping[str, object]) -> SetupChange | str` (str = why not)
  - `describe_change(setup: ProgramSetup, change: SetupChange) -> tuple[str, str]` (before, after; short, human)
  - `apply_change(user_id: str, ref: ProgramRef, change: SetupChange) -> str` (result line; raises `SetupChangeError(str)` when stale or invalid)
  - `fingerprint(change: SetupChange) -> str` (target, op, action id or key, and a sha1 of the normalized label/body or patch - 12 hex chars)
  - `declined(user_id: str, ref: ProgramRef) -> list[DeclinedEntry]` with `DeclinedEntry(TypedDict)`: `fingerprint: str; summary: str; declined_at: str` (ISO date)
  - `record_decline(user_id: str, ref: ProgramRef, change: SetupChange, summary: str) -> None` (stored at `{program_id}:setup_declined`, newest `SETUP_DECLINED_MAX` kept)
  - `blocked_by_decline(entries: list[DeclinedEntry], change: SetupChange, evidence: list[str]) -> bool` (True when the fingerprint was declined and no evidence date is after `declined_at`)

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_program_setup.py` (use `test_database`, a sports program saved with `save_programs`-equivalent KV, and `kv_set` for instruction keys):
  - `test_add_starts_from_the_defaults` - program without `quick_actions`; `apply_change(add)` -> stored list is the sports defaults + the new action at the end.
  - `test_edit_replaces_only_the_named_action` / `test_remove_drops_it`
  - `test_edit_of_a_vanished_action_is_refused` - `SetupChangeError`, stored list unchanged.
  - `test_instruction_patch_merges` - `routine` `{"days": 3, "z2_watts": 120}` + patch `{"z2_watts": 125, "days": None}` -> `{"z2_watts": 125}`.
  - `test_a_prose_instruction_is_replaced_whole` - `goals` holds `"Ride 200 km"`; `text` change replaces it; a `patch` on it is refused.
  - `test_only_instruction_keys_may_change` - `progress`, `vocabulary`, `programs` refused by `validate_change` with a reason naming the allowed keys.
  - `test_quick_action_limits_hold` - label 41 chars / 5 fields / over the per-program max -> reason strings.
  - `test_describe_shows_before_and_after` - edit -> `("⏭️ Next workout: 'What is my next workout?'", "⏭️ Next workout: 'What is my next workout? Date: …'")` shape (assert both contain the label and differ).
  - `test_decline_is_remembered_and_blocks_until_newer_evidence` - `record_decline` on day D; `blocked_by_decline(..., ["D-1: …"])` True, `(["D+1: …"])` False; list capped at `SETUP_DECLINED_MAX`.
  - `test_fingerprint_ignores_case_and_spacing_of_the_body`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_program_setup.py -q -p no:xdist` - Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the service. Quick action writes reuse `QuickActionItem` validation and the moved `resolve_quick_actions`; programs are read and saved through `db.kv_get/kv_set(user_id, ns, "programs")` (the route's `get_programs`/`save_programs` stay and call the same KV). Instruction patches use `src/utils/json_merge.merge_patch`.
- [ ] **Step 4: Run** the new tests plus `tests/unit -k "quick_action or program" -q` and `tests/integration -k quick_action -q` - Expected: PASS (the route behaves as before).
- [ ] **Step 5: Commit** `feat(programs): a service for a program's setup - read, validate, apply, decline`.

### Task 2: The in-the-moment card

**Files:**
- Create: `src/agent/tools/program_setup_tool.py` (tool `propose_setup_change`, kind `program_setup`)
- Modify: `src/agent/tools/__init__.py`, `src/agent/tool_display.py`, the agent editor/prompt-enhancer tool lists and icons (follow `docs/features/agent-tools.md` "Adding a New Tool" and `/new-tool`)
- Modify: `src/db/models/proposals.py` (`kind_proposals(conversation_id: str, kind: str) -> list[Proposal]`, newest first)
- Modify: `src/agent/prompt_programs.py` (one sentence in the program note that the tool exists; directives live in its result)
- Create: `evals/cases/program_setup_repeated_request.yaml`
- Test: `tests/unit/test_program_setup_tool.py`

**Interfaces:**
- Consumes: Task 1 (`program_for_conversation`, `load_setup`, `validate_change`, `describe_change`, `apply_change`, `fingerprint`, `declined`, `record_decline`, `blocked_by_decline`, `SetupChangeError`).
- Produces: tool `propose_setup_change(change: str, evidence: list[str], reason: str) -> str` - `change` a JSON object of `SetupChange` (one schema-typed string keeps every parameter concrete for Gemini), `evidence` 1-5 dated items, `reason` one sentence. Kind `program_setup`, option payload `{"namespace", "program_id", "change", "fingerprint"}`, details `{"Change": "<before> → <after>", "Why": reason, "Based on": "; ".join(evidence)}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_files_a_card_with_before_after_and_evidence` - in a sports program chat; returns `card_shown` text; one pending `program_setup` proposal with those details.
  - `test_outside_a_program_chat_it_refuses` - normal conversation -> tool error, no proposal.
  - `test_without_dated_evidence_it_refuses` - `[]` or `["you often ask"]` -> tool error naming the format.
  - `test_a_declined_change_needs_newer_evidence` - after `record_decline` today, evidence dated yesterday -> refused; tomorrow-dated -> filed.
  - `test_an_ignored_card_comes_back_once_after_three_days` - one expired same-fingerprint proposal 1 day old -> refused; 4 days old -> filed; two expired -> refused.
  - `test_approve_applies_exactly_the_card` - resolve with option 0 -> setup changed, result line names the action/key.
  - `test_decline_records_the_decline` - decline -> `declined()` has the fingerprint.
  - `test_a_stale_card_fails_with_its_reason` - action removed by hand before approving -> proposal `failed`, reason shown.
  - Schema guard: every parameter has a concrete type (as `test_garmin_workout_tool.py::TestToolSchema`).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_program_setup_tool.py -q -p no:xdist` - Expected: FAIL.
- [ ] **Step 3: Implement** the tool and `register_kind("program_setup", apply_setup_change, decline=decline_setup_change)`. Refusals return `tool_error(...)` whose text tells the model what to do instead (e.g. "Not proposed: declined on 2026-11-09; propose again only with a newer turn"). Gate: available only when `program_for_conversation` resolves (the conditional-tools pattern in `tools/__init__.py`); not available to unattended runs.
- [ ] **Step 4: Run** the tests, `tests/unit/test_tool_display.py`, and the eval case 3x: `make eval ARGS="--only program_setup_repeated_request"` - Expected: PASS; report the eval cost.
- [ ] **Step 5: Commit** `feat(programs): the coach proposes setup changes on a card`.

### Task 3: The Review service and routes

**Files:**
- Create: `src/services/program_review.py`
- Create: `src/api/routes/program_setup_review.py` (registered next to the quick-action routes for each program namespace)
- Modify: `src/api/schemas/programs.py` (`SetupSuggestion`, `SetupReviewResponse`, `SetupChangeRequest`)
- Modify: `src/config.py` (`PROGRAM_REVIEW_MODEL` default: the fast tier, `PROGRAM_REVIEW_MESSAGES = 40`, `PROGRAM_REVIEW_MESSAGE_CHARS = 600`, `PROGRAM_REVIEW_MAX_SUGGESTIONS = 8`), `.env.example`
- Test: `tests/unit/test_program_review.py`, `tests/integration/test_routes_program_setup_review.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `class Suggestion(TypedDict)`: `id: str` (the fingerprint); `change: SetupChange`; `summary: str`; `before: str`; `after: str`; `evidence: list[str]`
  - `review_setup(user_id: str, ref: ProgramRef) -> list[Suggestion]` (one model call with structured output; input = setup, declined list, the program chat's last `PROGRAM_REVIEW_MESSAGES` messages cut to `PROGRAM_REVIEW_MESSAGE_CHARS`, each prefixed with its date; output validated item by item)
  - `POST /api/{ns}/programs/<program_id>/setup-review` -> `{"suggestions": [Suggestion]}` (empty list = nothing to change)
  - `POST /api/{ns}/programs/<program_id>/setup-review/apply` body `{"change", "summary"}` -> the program item (as the quick-action PUT returns)
  - `POST /api/{ns}/programs/<program_id>/setup-review/reject` body `{"change", "summary"}` -> 204
- [ ] **Step 1: Write the failing tests** (model call patched at `program_review._invoke`):
  - `test_returns_validated_suggestions_with_before_after`
  - `test_invalid_and_declined_items_are_dropped` - unknown key, 5 fields, no evidence, declined fingerprint with older evidence -> only the valid one remains.
  - `test_no_program_chat_means_no_turns_but_a_review` - program without a conversation -> the model still sees the setup; `[]` is fine.
  - `test_at_most_eight` - 12 valid -> 8.
  - Integration: `test_review_apply_and_reject_round_trip` (apply changes the program item; reject records the decline; another user's program -> 404); `test_review_logs_its_outcomes` (lines `Setup review` with `suggestions`, `cost_usd`, `duration_ms`; `Setup suggestion resolved` with `source`, `outcome`, `target`).
- [ ] **Step 2: Run** them - Expected: FAIL.
- [ ] **Step 3: Implement**; `make openapi && make types`; client methods `programs.reviewSetup(ns, id)`, `applySetupChange(...)`, `rejectSetupChange(...)` in `web/src/api/programs.ts`. The card path logs the same `Setup suggestion resolved` line from its apply/decline (`source: "card"`).
- [ ] **Step 4: Run** `make lint` and `make test` - Expected: both exit 0.
- [ ] **Step 5: Commit** `feat(programs): a setup review the Quick actions sheet can ask for`.

### Task 4: The Review in the Quick actions sheet

**Files:**
- Create: `web/src/components/QuickActionsReview.ts` (the list view)
- Modify: `web/src/components/QuickActionsEditor.ts` (a **Review** button next to "Add quick action"; opens the review view, returns to the list after)
- Modify: `web/src/styles/components/quick-actions.css` (or the editor's stylesheet), `web/src/config.ts` if a timing is needed
- Test: `web/tests/component/QuickActionsReview.test.ts`, `web/tests/e2e/programs/quick-actions.spec.ts` (extend), the E2E server's fake for the review call

**Interfaces:**
- Consumes: Task 3's client methods and `Suggestion` type (generated).
- Produces: `openQuickActionsReview(session: EditorSession): void` used by the editor.

- [ ] **Step 1: Write the failing tests:**
  - Component: loading state while the call runs; each suggestion shows summary, before -> after, evidence lines, Accept / Reject; Accept calls apply and marks the row "Applied" (the editor's list refreshes from the returned program); Reject marks "Rejected"; an empty result shows "Nothing to change - your quick actions and instructions match how you use them."; a failed call shows a retry line.
  - E2E (desktop + mobile project): open the sheet in a sports program, Review, see the fake's one suggestion, Accept, the new quick action appears in the list and in the bar.
- [ ] **Step 2: Run** `cd web && npx vitest run tests/component/QuickActionsReview.test.ts` - Expected: FAIL.
- [ ] **Step 3: Implement** in the editor's idiom (its list rows and buttons; `createElement`, `setIcon`, event delegation); the copy above is exact.
- [ ] **Step 4: Run** `make build` then `E2E_PORT=8042 make test-fe-e2e` scoped to the spec, desktop and mobile - Expected: PASS. Screenshot the review view at 390px and desktop and check vertical rhythm.
- [ ] **Step 5: Commit** `feat(web): review a program's quick actions and instructions from the sheet`.

### Task 5: Ship

**Files:**
- Modify: `docs/features/proposals.md` (the `program_setup` kind), `docs/features/programs.md` or the sports/language feature page (the setup service, the tool, the Review), `docs/regular-review.md` (counts per source/outcome/target from `Setup suggestion resolved`, review cost), `TODO.md` (re-measure ~Nov 25 2026: accepted share per source, declined repeats, reviews that return nothing)
- Create: `announcements/2026-11-11-coach-tunes-itself.md` (Czech + English, for the family)

- [ ] **Step 1:** Write the docs, the review check, the TODO entry and the announcement.
- [ ] **Step 2: Run** `E2E_PORT=8042 caffeinate -i nice -n 10 make pre-commit` - Expected: "All pre-commit checks passed!", exit 0.
- [ ] **Step 3: Commit** `docs(programs): self-tuning - docs, review check, re-measure, What's new`, then deploy and health-check.
