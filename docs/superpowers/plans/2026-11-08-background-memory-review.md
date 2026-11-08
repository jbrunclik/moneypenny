# Background Memory Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every few user turns, a cheap background pass rereads the chat and conservatively adds or patches memories, then labels the triggering reply with "Memory updated: ...".

**Architecture:**
- **Trigger:** `save_message_to_db` (the save path for chat turns only; agent runs use the executor) calls a trigger. The trigger keeps a per-chat counter plus a review cursor in `kv_store`. When the counter reaches its threshold, it starts a daemon thread.
- **Pass:** the thread asks `AI_ASSIST_MODEL` for JSON memory operations and applies them one at a time through the memory tool's guards.
- **Label:** the pass stores the result on the reply's new `memory_note` column. The open chat's in-place merge patches the label in without a re-render.

**Tech Stack:** Flask, google-genai (`shared_genai_client`), SQLite/yoyo, vanilla TS, Playwright, `evals/run.py`.

**Spec:** `docs/superpowers/specs/2026-11-08-background-memory-review-design.md`

## Global Constraints

- **Config** in `src/config.py`, in `.env.example` and on the docs page:
  - `MEMORY_REVIEW_ENABLED` (default true)
  - `MEMORY_REVIEW_EVERY_TURNS` (6)
  - `MEMORY_REVIEW_MAX_TURNS` (12)
  - `MEMORY_REVIEW_MAX_OPS` (3)
- **Operations:** add and patch only; deletes are dropped. There is no approval queue.
- **Where it runs:** never in anonymous or planning chats, and never in agent runs.
- **Logs:** user ids, never emails. Excerpts at most 80 chars.
- **Label copy:** "Memory updated: " + up to two items + ", and N more". Tapping it opens Memories (the Data page).
- **Migration:** before committing, check the highest migration number on `main`; the next one should be `0077`.
- **Commits and gate:**
  - Conventional Commits.
  - Stage explicit paths.
  - Run `make lint` and `E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit`, checking the exit code directly.

## Review Focus

1. **A pass that crashes or times out never affects the turn**, and the cursor does not move, so the next pass retries those turns. Test in Task 3.
2. **Two passes in one chat.** A slow pass is still running when the next threshold hits, so the second must not start. Guard: an in-process set of running conversation ids, plus the cursor written only on success. Test in Task 3.
3. **Every operation rejected**, e.g. a full bank or a bad `old_text`. Nothing is labelled, a log line is written, and the cursor still moves, so the pass doesn't reread forever. Test in Task 3.
4. **Model returns non-JSON, fenced JSON or an object instead of a list.** Fenced JSON parses; anything else counts as zero operations. Test in Task 2.
5. **Label-only change on an open chat.** The label patches in on the merge with no full re-render, and the scroll position is kept. Test in Task 4 (unit test on the patch function).

Known limit (spec-consistent, noted in docs): agent chats sync by message count, so a label shows in an open agent chat only after a reload.

---

### Task 1: The `memory_note` column, cost top-up, API field

**Files:**
- Create: `migrations/0077_message_memory_note.py`
- Modify:
  - `src/db/models/dataclasses.py` (`Message.memory_note: str | None = None`)
  - `src/db/models/message.py` (row mapping; `set_memory_note`)
  - `src/db/models/cost.py` (`add_message_cost_usd`)
  - `src/api/schemas/chat.py` (`memory_note` on the message response, next to `delivery`)
  - `src/api/helpers/` (wherever `delivery` is mapped into the response)
  - `tests/e2e_server/` (the seed accepts `memory_note` per message, like `delivery`)
  - `static/openapi.json` and `web/src/types/generated-api.ts` (via `make openapi && make types`)
- Test: `tests/unit/db/test_message_memory_note.py`, `tests/integration/test_routes_conversations.py`

**Interfaces:**
- Produces:
  - `db.set_memory_note(message_id: str, note: str) -> None`
  - `db.add_message_cost_usd(message_id: str, cost_usd: float) -> None`: adds to an existing cost row's `cost_usd`; no row means a no-op.
  - API `MessageResponse.memory_note: str | None`

- [ ] **Step 1: Failing tests.**
  - `test_set_memory_note_round_trips`: save a message, call `set_memory_note(id, "Ema - ballet on Tuesdays")`, then `get_messages` returns it.
  - `test_set_memory_note_bumps_sync_change`: `get_sync_cursor()` increases.
  - `test_add_message_cost_usd_tops_up`: a cost row at 0.01 plus 0.002 gives 0.012.
  - Integration test `test_conversation_messages_carry_memory_note`: GET of the conversation shows `memory_note`.
- [ ] **Step 2:** Run `pytest tests/unit/db/test_message_memory_note.py -v`. Expected: FAIL (no column or method).
- [ ] **Step 3:** Write the migration (`ALTER TABLE messages ADD COLUMN memory_note TEXT`; rollback drops it), the model methods, the schema field and the seed support. Then run `make openapi && make types`.
- [ ] **Step 4:** Run the tests from Step 1. Expected: PASS.
- [ ] **Step 5:** Commit `feat(memory): a memory_note column on replies`.

### Task 2: The review pass (model call, parsing, one-at-a-time apply)

**Files:**
- Create:
  - `src/agent/prompt_texts/memory_review.py` (`MEMORY_REVIEW_PROMPT`)
  - `src/agent/memory_review.py`
- Modify: `src/agent/tools/memory.py` (add `apply_single_op`)
- Test: `tests/unit/agent/test_memory_review.py`, `tests/unit/agent/tools/test_memory_single_op.py`

**Interfaces:**
- Consumes: `_plan_batch`, `db.apply_memory_batch`, `_applied_line` (memory.py); `db.list_memories`, `db.list_deleted_memories`.
- Produces:
  - `apply_single_op(user_id: str, conversation_id: str | None, op: MemoryOp) -> str | None` in `memory.py`: the memory's new full text when applied, None when rejected or on a conflict or error. It logs the reason; the log keeps the existing "Memory added/updated via tool" lines plus `source="review"`.
  - `@dataclass ReviewResult(applied: list[str], input_tokens: int, output_tokens: int)` in `memory_review.py`.
  - `review_messages(user_id: str, conversation_id: str, messages: list[Message]) -> ReviewResult`. It is synchronous; the eval and the trigger both call it.
  - `parse_ops(text: str) -> list[MemoryOp]`: strips a ```json fence, keeps only dict items whose action is `add` or `patch`, truncates to `MEMORY_REVIEW_MAX_OPS`, and returns `[]` on anything unparseable.
  - `format_note(applied: list[str]) -> str`: "Ema - ballet on Tuesdays" / "A, B" / "A, B, and 1 more". Each item is truncated to 60 chars with "…".

- [ ] **Step 1: Failing tests.**
  - `test_parse_ops_fenced_json`
  - `test_parse_ops_drops_delete_and_unknown`
  - `test_parse_ops_caps_at_max_ops`
  - `test_parse_ops_garbage_is_empty` (`"sure!"`, `'{"action":"add"}'` → `[]`)
  - `test_format_note_two_and_more` (3 items → `"A, B, and 1 more"`)
  - `test_apply_single_op_applies_valid_and_rejects_bad` (a patch whose `old_text` is absent → None; a valid add → its text)
  - `test_apply_single_op_full_bank_rejects_add_allows_patch`
  - `test_review_messages_builds_prompt_with_bank_and_deleted`: patch the genai client; the captured prompt contains a current memory's id and text and a deleted memory under "do not re-add"; tool messages and tool output are absent.
  - `test_review_messages_applies_each_op_independently`: the model returns one bad op and one good op; `applied` has 1 item.
- [ ] **Step 2:** Run `pytest tests/unit/agent/test_memory_review.py tests/unit/agent/tools/test_memory_single_op.py -v`. Expected: FAIL (import errors).
- [ ] **Step 3: Implement.**
  - The prompt carries the spec's rules verbatim in intent:
    - conservative categories;
    - the do-not-capture list;
    - patch instead of duplicating;
    - never re-add a deleted memory;
    - an empty list is normal;
    - JSON list output only.
  - Transcript input: user and assistant text only, each message truncated to 2000 chars.
  - Model call: `AI_ASSIST_MODEL`, temperature 0.2, `ThinkingLevel.LOW`. Read tokens from `usage_metadata`.
- [ ] **Step 4:** Run the tests from Step 2. Expected: PASS.
- [ ] **Step 5:** Commit `feat(memory): the background review pass`.

### Task 3: The trigger (counter, cursor, daemon thread, label, cost)

**Files:**
- Create: `src/api/helpers/memory_review_trigger.py`
- Modify:
  - `src/api/helpers/chat_save.py` (call `note_turn` right after `record_turn_facts`)
  - `src/config.py`, `.env.example`
- Test: `tests/unit/api/test_memory_review_trigger.py`

**Interfaces:**
- Consumes: `review_messages`, `format_note` (Task 2); `db.set_memory_note`, `db.add_message_cost_usd` (Task 1); `calculate_token_cost` (`src/services/costs.py`).
- Produces: `note_turn(conv_id: str, user_id: str, message_id: str, result_messages: list[Any]) -> None`. It is best-effort and never raises.
- **State:** kv namespace `memory_review`, key = conv id, value JSON `{"turns": int, "cursor": str | null}`. A null cursor means start from the beginning.
- **Thread seam:** `_start(fn)` for tests (they run it inline).

- [ ] **Step 1: Failing tests** (fake `review_messages`, inline `_start`).
  - `test_counts_turns_and_fires_at_threshold`: five calls don't run the pass; the sixth runs it once, sets the label on the sixth reply and resets turns to 0.
  - `test_manage_memory_turn_resets_counter_keeps_cursor`
  - `test_review_reads_from_cursor_capped_at_max_turns`: with 20 user turns after the cursor, the pass gets the last 12 user turns plus their replies.
  - `test_cursor_moves_to_last_reviewed_message_on_success`
  - `test_failure_keeps_cursor_and_never_raises`: the fake raises; `note_turn` returns, the cursor is unchanged and turns are reset.
  - `test_all_rejected_moves_cursor_without_label`
  - `test_second_pass_skipped_while_one_runs`
  - `test_skips_anonymous_planning_and_disabled`
  - `test_records_cost_on_the_triggering_reply`
- [ ] **Step 2:** Run `pytest tests/unit/api/test_memory_review_trigger.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement.**
  - Eligibility: the conversation exists, `not conv.anonymous_mode and not conv.is_planning`, and `MEMORY_REVIEW_ENABLED`.
  - A turn called `manage_memory` when an `AIMessage` in `result_messages` has a tool call of that name.
  - Use the tool's conversation context so `apply_single_op` gets the conv id.
  - Log one line per pass ("Memory review pass": user_id, conversation_id, reviewed_messages, applied, cost_usd).
  - Add the four config keys with unit-free names (counts) and comments.
- [ ] **Step 4:** Run the trigger tests, then `make test`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(memory): review memory in the background every few turns`.

### Task 4: The label in the UI (render plus in-place merge)

**Files:**
- Create:
  - `web/src/components/messages/memory-note.ts`
  - `web/tests/unit/memory-note-merge.test.ts`
  - `web/tests/e2e/memory-note.spec.ts`
- Modify:
  - `web/src/components/messages/render.ts`: append the note after the message content, for assistant messages only.
  - `web/src/core/remote-merge.ts`
  - the stylesheet holding `.message-delivery`
  - `web/src/types/api.ts` if `Message` is hand-typed there

**Interfaces:**
- Consumes: `Message.memory_note` (Task 1).
- Produces:
  - `renderMemoryNote(note: string): HTMLElement`: a `button.message-memory-note` with the text "Memory updated: {note}". Clicking it navigates to Memories, using the same route the app uses for the Data page.
  - `patchMemoryNotes(convId: string, container: HTMLElement, local: readonly Message[], server: readonly Message[]): void`, exported from `remote-merge.ts`. For each server message whose `memory_note` differs from the local copy, it replaces or inserts the note element inside that message's `.message-content-wrapper` and updates the store copy. It is called in `mergeOnce` after `reconcileUnfinished`.

- [ ] **Step 1: Failing tests.**
  - Unit test `patches a new memory note into a rendered reply without re-rendering`: the reply element is the same node before and after, and the note text matches.
  - Unit test `leaves replies with an unchanged note alone`.
  - E2E (desktop and 375px mobile): seed a reply with `memory_note: "Ema - ballet on Tuesdays"`. Expect `.message-memory-note` to show "Memory updated: Ema - ballet on Tuesdays". Clicking it lands on the Memories view.
- [ ] **Step 2:** Run `cd web && npx vitest run tests/unit/memory-note-merge.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Quiet style: the same size and colour tokens as `.message-delivery`, a small bookmark or memory icon from `icons.ts` (reuse an existing one), aligned under the reply.
  - Check desktop and mobile screenshots for vertical rhythm.
- [ ] **Step 4:** Run the unit tests, then `make build && E2E_PORT=8041 npx playwright test e2e/memory-note.spec.ts` (from `web/`). Expected: PASS.
- [ ] **Step 5:** Commit `feat(memory): a quiet "Memory updated" note under the reply`.

### Task 5: Evals

**Files:**
- Modify: `evals/run.py`, adding a `memory_review: bool = False` case field. When it is true, `_run_turn` seeds `history` and `memories`, calls `review_messages` on the seeded messages, and returns a synthetic `AIMessage` carrying one `manage_memory` tool call whose args are the applied ops. That keeps the existing `required_tools`/`forbidden_tools`/`forbidden_arg_patterns` and judge grading working unchanged.
- Create:
  - `evals/cases/memory_review_saves_fact.yaml`
  - `evals/cases/memory_review_ignores_oneoffs.yaml`
  - `evals/cases/memory_review_patches.yaml`
- Test: `tests/unit/evals/test_run_memory_review.py`, covering the synthetic tool-call shape with a fake `review_messages`.

**Interfaces:**
- Consumes: `review_messages`, `ReviewResult` (Task 2). Extend `ReviewResult` with `ops: list[MemoryOp]` (the applied ops) if Task 2 didn't include it; ledger it as a ruling.

- [ ] **Step 1:** Failing unit test `test_memory_review_case_reports_applied_ops_as_manage_memory_call`.
- [ ] **Step 2:** Run `pytest tests/unit/evals/test_run_memory_review.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the field and the three cases, following the spec's eval section:
  - "saves a passing household fact" requires `manage_memory`, and the rubric names Ema's ballet on Tuesday 17:00;
  - "ignores one-offs" forbids `manage_memory`;
  - "patches" seeds "Ema - ballet on Mondays" and forbids an `"action": "add"` pattern.
- [ ] **Step 4:** Run `pytest tests/unit/evals -v`. Then run `nice -n 10 make eval CASES=memory_review` (or the harness's filter flag). Expected: 3/3 pass. Report the USD cost.
- [ ] **Step 5:** Commit `test(evals): background memory review cases`.

### Task 6: Docs, TODO, ship

**Files:**
- Modify:
  - the memory page under `docs/features/` (behavior, config, the agent-chat label limit, the re-measure plan)
  - `TODO.md`: remove the "Background memory review" item and add "Re-measure the background memory review (~2 weeks after ship)". It holds the spec's re-measure steps: writes per user, sampled keep or noise, share later deleted or edited, and tighten if noise is above about 1 in 5.

- [ ] **Step 1:** Write the docs and the TODO.
- [ ] **Step 2:** Run `make lint`, then `E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit`. Check both exit codes directly.
- [ ] **Step 3:** Commit `docs(memory): background review`. Then do the final review per executing-plans, deploy with a health check, and watch CI.
