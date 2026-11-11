# Instructions Self-Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The assistant proposes changes to the user's custom instructions (and the memories on their border) through a Settings Review and in-chat cards, applied only on the user's yes; the instructions limit becomes 8000.

**Architecture:** A service `src/services/instructions_tuning.py` owns the change model (passage edit on the instructions text + optional memory write), validation, field rows, evidence, declines and the all-or-nothing apply (one SQLite transaction across `users` and `user_memories`). `src/agent/instructions_review.py` is one structured Gemini call like `program_review.py`. Routes under `/api/users/me/instructions-review` reuse the program Review's request/response schemas, so the frontend reuses `QuickActionsReview.ts` generalized over its texts. The tool `propose_instruction_change` files `custom_instructions` proposal cards in ordinary chats.

**Tech Stack:** Flask/APIFlask + Pydantic, LangChain/Gemini structured output, SQLite, vanilla TS + Vitest + Playwright.

**Spec:** docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md

## Global Constraints

- Instructions limit: `Config.CUSTOM_INSTRUCTIONS_MAX_CHARS = 8000` (env `CUSTOM_INSTRUCTIONS_MAX_CHARS`), mirrored as `CUSTOM_INSTRUCTIONS_MAX_CHARS` in `web/src/config.ts`.
- New-rule evidence: 1-5 items `"YYYY-MM-DD: ..."` on days the user wrote in the review window (Review) / this chat (tool). Clean-up evidence: items `"Memory: <exact memory text>"` / `"Instructions: <exact passage>"` that match current state. A suggestion that adds or changes instruction text not coming from a memory needs at least one dated item.
- Memory suggestions only at the instructions' border: a memory add only as half of a move out of the instructions; patch/delete alone allowed (duplicate, contradiction, corrected). Protected memories never touched. Categories: preference, fact, context, goal.
- Text checks: `find_injection` on every new instruction passage and memory content; instructions ≤ 8000 after the change; memory ≤ `MEMORY_MAX_ENTRY_CHARS`; bank < `MEMORY_MAX_ENTRIES` for an add.
- Declines: per user, KV namespace `instructions_tuning` (added to `RESERVED_NAMESPACES`), key `declined`, newest `SETUP_DECLINED_MAX` kept. Re-offer of an ignored card: per user, once, after `SETUP_REOFFER_AFTER_DAYS`.
- Review: `INSTRUCTIONS_REVIEW_MODEL` (default `PROGRAM_REVIEW_MODEL`'s value), `INSTRUCTIONS_REVIEW_MESSAGES=60`, `INSTRUCTIONS_REVIEW_REPLY_CHARS=300`, `INSTRUCTIONS_REVIEW_MAX_SUGGESTIONS=8`, timeout reuses `PROGRAM_REVIEW_TIMEOUT_SECONDS`. New env vars go to `src/config.py`, `.env.example`, docs.
- Ordinary chat = not planning, agent, sports, language, what's new, standing, anonymous, deleted.
- Logs: user ids only; no instruction or memory text (lengths and targets only).
- Conventional Commits; stage explicit paths; full gate before each commit (`E2E_PORT=8046 caffeinate -i nice -n 10 make pre-commit`); push, then deploy.

## Review Focus

1. A move where the memory changed meanwhile: nothing changes (instructions untouched), 409 refresh for a delete half, 400 otherwise.
2. A replace whose old passage now appears twice (user pasted it again): refused as ambiguous, not applied to the first.
3. Evidence item "Memory: x" naming a protected or deleted memory: the suggestion is dropped.
4. Accept in Settings while the textarea holds unsaved typing: the typing is saved first (blur), the change applies on top, textarea shows the result.
5. Proposed text with an injection pattern (e.g. from a pasted page in chat): dropped by the Review, refused by the tool.

---

### Task 1: The 8000-character limit

**Files:** `src/config.py`, `.env.example`, `src/api/schemas/settings.py:23`, `web/src/config.ts`, `web/src/components/settings/instructions.ts`, tests `tests/integration/test_routes_settings*.py` (the existing settings route test file), `web/tests/unit` or component test for the counter.

- [ ] Test: PATCH settings with 8000 chars → 200; 8001 → 400. Counter reads `0/8000`.
- [ ] Run: fails (2000 limit).
- [ ] `Config.CUSTOM_INSTRUCTIONS_MAX_CHARS`; schema `max_length=Config.CUSTOM_INSTRUCTIONS_MAX_CHARS`; `CHAR_LIMIT` replaced by the web config constant; `make openapi && make types`.
- [ ] Run: passes. Commit `feat(settings): custom instructions hold up to 8000 characters`.

### Task 2: The change model and apply (service + db)

**Files:** Create `src/services/instructions_tuning.py`; modify `src/db/models/memory.py` (transaction method), `src/db/models/message.py` or `message_pagination.py` (window query), `src/agent/tools/agent_kv.py` (reserved namespace); test `tests/unit/test_instructions_tuning.py`.

**Interfaces (Produces):**
```python
class InstructionEdit(TypedDict, total=False):
    op: Literal["append", "replace", "remove"]; old: str; new: str
class MemoryEdit(TypedDict, total=False):
    op: Literal["add", "patch", "delete"]; id: str; content: str; category: str; expected: str
class InstructionChange(TypedDict, total=False):
    instructions: InstructionEdit; memory: MemoryEdit
class TuningState(TypedDict): instructions: str; memories: list[Memory]
class InstructionsChangeError(Exception); class InstructionsConflictError(InstructionsChangeError)
def load_state(user_id: str) -> TuningState
def validate_change(raw: object) -> InstructionChange | str          # shape, border rule, limits, find_injection
def field_changes(state: TuningState, change: InstructionChange) -> list[FieldChange]  # from program_setup
def with_snapshot(state, change) -> InstructionChange                 # memory.expected = current content
def evidence_problem(evidence: list[str], known_days: set[date], state: TuningState, change) -> str | None
def fingerprint(change) -> str
def declined(user_id) -> list[DeclinedEntry]; def record_decline(user_id, change, summary) -> None
def blocked_by_decline(entries, change, evidence) -> bool
def apply_change(user_id: str, change: InstructionChange) -> str      # returns the new instructions text
def log_resolved(source: Literal["review","card"], outcome: str, change) -> None
def ordinary_turns(user_id: str) -> list[Turn]   # Turn: day: date, user: str, reply: str (excerpt of the reply it answered)
# db: apply_instructions_change(user_id, expected_instructions: str, new_instructions: str, writes: list[MemoryWrite]) -> None
#     raises MemoryWriteConflictError (memory half) / InstructionsConflict (users row changed) - one BEGIN IMMEDIATE
# db: recent_ordinary_user_turns(user_id, limit) -> list[tuple[datetime, str, str | None]]
```

- [ ] Tests (one class each): `TestValidate` (unknown op, memory add without instruction remove → refused, protected-memory target refused, injection text refused, >8000 after append refused); `TestApply` (append adds a paragraph with a blank line; replace/remove act only on an exact single occurrence; twice → "appears more than once", gone → conflict; move = instruction append + memory delete in one transaction, memory changed → nothing changed, instructions unchanged); `TestFieldChanges` (rows "Instructions" / "Memory (preference)" with before/after); `TestEvidence` (dated vs item references, a new rule without a dated item refused, a "Memory:" item not matching any memory refused); `TestDeclines` (record, block without newer evidence, unblock with newer dated turn); `TestOrdinaryTurns` (excludes program, agent, anonymous, planner chats; pairs the preceding assistant excerpt).
- [ ] Run: all fail (module missing).
- [ ] Implement. Reuse `program_setup.evidence_dates`, `FieldChange`, `EVIDENCE_MAX` (import, don't copy). Apply computes the new text from the current row, then the db call with `expected_instructions` = that row (an edit between read and write is a conflict).
- [ ] Run: pass; `make lint`. Commit `feat(instructions): a change model for instructions and their border memories`.

### Task 3: The Review call

**Files:** Create `src/agent/instructions_review.py`; config entries; test `tests/unit/test_instructions_review.py`; E2E fake in `tests/e2e_server/llm_fakes.py` (`mock_instructions_review_invoke`, one append suggestion dated today) wired like `mock_program_review_invoke`.

**Interfaces:** `review_instructions(user_id) -> list[Suggestion]` (Suggestion = program_review's shape: id, change, summary, before, after, changes, evidence); `refresh_suggestion(user_id, change, summary, evidence) -> Suggestion | None` (memory delete with changed content → rebuilt; anything else gone → None). Flat `ReviewItem`: `kind: Literal["add_rule","change_rule","remove_rule","move_to_instructions","move_to_memory","remove_memory","fix_memory"]`, `old_passage`, `new_passage`, `memory_id`, `memory_content`, `category`, `summary`, `evidence`.

- [ ] Tests with the model call patched: invalid items dropped (bad evidence, declined, injection, unknown memory id), duplicates by fingerprint dropped, cap at 8, one log line "Instructions review" with returned/suggestions/cost_usd/duration_ms, prompt contains the declined list and no memory ids of protected memories as removable.
- [ ] Run: fail. Implement (prompt: rules vs facts, border-only memory suggestions, clean-up cites items, "no suggestions" is a good answer, user's language; turns fenced as data like the memory review's boundary).
- [ ] Run: pass. Commit `feat(instructions): the instructions Review`.

### Task 4: Routes

**Files:** Create `src/api/routes/instructions_review.py` (registered next to settings routes); schemas: reuse `SetupReviewResponse` and `SetupChangeRequest`, add `InstructionsChangeResponse { custom_instructions: str }`; `make openapi && make types`; test `tests/integration/test_routes_instructions_review.py`.

- [ ] Tests: review returns suggestions (patched); apply returns the new text and stores it; conflict → 409 with `details.suggestion` for a refreshable memory delete, 400 "That no longer applies - nothing was changed." otherwise; reject records a decline (204); 401 without auth; validation error on a malformed change.
- [ ] Run: fail. Implement (rate limit like program routes; `log_resolved("review", ...)`).
- [ ] Run: pass. Commit `feat(instructions): Review, apply and reject endpoints`.

### Task 5: The in-the-moment tool and card

**Files:** Create `src/agent/tools/instructions_tool.py` (`propose_instruction_change(change: str, evidence: list[str], reason: str)`, kind `custom_instructions`, `register_kind` with apply/decline); `src/agent/tools/__init__.py` (bind in ordinary non-anonymous non-planner chats only; `_NON_PERMISSIONED_TOOLS`); `src/agent/tool_display.py` (metadata "Suggesting an instruction" / "Suggested an instruction", `_CONDITIONAL_TOOLS`, detail `reason`); `src/api/routes/agent_assist.py`, `src/api/helpers/lost_actions.py` if the checklist applies (it files a card: not a side effect until approved - document the call); `web/src/core/startup/message-ui.ts` (on an approved `custom_instructions` card, refetch settings into the store); test `tests/unit/test_instructions_tool.py`.

- [ ] Tests: refuses outside ordinary chats; files a card with "Change" rows, "Applies to" line "Every chat, coaches and agents included", "Based on"; evidence days from this chat; per-user re-offer rule; decline recorded; approve applies and logs `card/approved`; schema guard (every arg typed).
- [ ] Run: fail. Implement; the result text steers ("Card shown - don't also save this as a memory").
- [ ] Run: pass. Commit `feat(instructions): the assistant offers an instructions change in the moment`.

### Task 6: Rules go to instructions, not memory

**Files:** `src/agent/prompt_texts/memory.py` (principle 1: a lasting rule about how to respond is not a memory - in an ordinary chat offer it with `propose_instruction_change`, elsewhere just follow it); `src/agent/prompt_texts/memory_review.py` (drop "how they like answers" from save-list; add "rules about how the assistant should respond" to never-save); `tests/unit/test_prompt_snapshots.py` baselines if they snapshot these; eval cases `evals/cases/instructions_*.yaml`: proposes on "stop using bullet points from now on", silent on "make this one shorter", saves a memory (no card) on "my daughter's name is Ema".

- [ ] Update snapshots/tests; run evals `--only instructions_` 3x, report the cost.
- [ ] Commit `feat(memory): style rules go to the instructions, facts stay in memory`.

### Task 7: The Settings Review UI

**Files:** `web/src/components/QuickActionsReview.ts` (export `renderSetupReview` with a `texts: ReviewTexts` option: title, phases, empty, failed; quick actions pass today's texts); `web/src/config.ts` (`INSTRUCTIONS_REVIEW_PHASES`); `web/src/api/settings.ts` (`instructionsReview`: review / apply → new text / reject, timeout `QUICK_ACTION_REVIEW_TIMEOUT_MS`); `web/src/components/settings/instructions.ts` (Review button under the counter; the review renders inside the section; accepted change sets textarea value, counter and store); `web/src/core/` handler wiring like `quick-actions.ts` (`refreshedOr` reused); evidence rows show "Memory"/"Instructions" items with a label; tests: `web/tests/component/InstructionsReview.test.ts`, E2E `web/tests/e2e/settings.spec.ts` (desktop + 375px: Review → Accept → textarea contains the passage).

- [ ] Tests first (component + E2E); run: fail. Implement; `make build`; run: pass. Screenshots desktop/mobile light/dark via a throwaway spec (deleted after); `/regen-baselines` if `popups.visual.ts` changes.
- [ ] Commit `feat(settings): Review suggests changes to your instructions`.

### Task 8: Instrumentation, docs, What's new

**Files:** `docs/features/memory-and-context.md` (Custom Instructions section: limit, Review, card, routing rule, logs), `docs/features/agent-tools.md` (tools table), `docs/features/proposals.md` (kind list), `docs/regular-review.md` (check: "Instructions review" cost/suggestions, resolved outcomes by source and target, refusals by reason, accept rate; instructions length distribution from the DB, counts only), `TODO.md` (re-measure ~Nov 25 2026), `announcements/2026-11-11-instructions-review.md` (Czech + English, for the family).

- [ ] Commit `docs(instructions): self-tuning docs, review check, re-measure, What's new`.

Final: whole-branch review on the most capable model, one fix pass, deploy after each green commit (≥30 min apart when a migration is involved - none planned).
