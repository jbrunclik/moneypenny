# Turn Budgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every chat turn is bounded by what actually costs - money, time, loops - instead of a 6-round cap, and ends with one tools-off answer that names what is left.

**Architecture:** The graph state carries the turn's budget (start time, running cost, failed-call signatures, a final-answer flag). `check_tool_results` (after every tool round) decides whether a limit is hit; when it is, the next `chat` call runs with tools disabled and the turn records why it stopped. The tool node blocks identical repeated failures. Everything ships behind `TURN_BUDGETS_ENABLED` (off) next to the old cap, is measured with an eval A/B, then switched on and the old cap removed.

**Tech Stack:** Python 3.14, LangGraph, langchain-google-genai (Gemini, explicit context cache), SQLite/yoyo, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-thorough-turns-and-conversation-facts-design.md`, section "Turn budgets replace the round cap" (decided Oct 26 2026). Read it before Task 1.

## Global Constraints

- Production daily driver: every step ships behind config defaults that keep ordinary turns unchanged until it is measured (`TURN_BUDGETS_ENABLED=false` until Task 6).
- Applies to every turn; a thorough turn (later, part 4) only raises the values.
- Drop the round-4 "aim to answer within a round or two" nudge (`AGENT_TOOL_ROUNDS_SOFT_NUDGE`); at most a batching hint with no pressure to finish.
- Cost guard: ordinary ceiling ~$0.15 a turn (typical turns cost $0.02-0.05); thorough ~$1 later.
- Wall-clock: one "wrap up now" notice at ~80% of the budget, appended to the latest tool result (results are read; prompt text is not).
- Loop detector: hash tool name + canonical args; warn, then block, repeated identical failures and A-B-A-B cycles; a successful write resets the count; a second byte-identical large result becomes a back-reference.
- Round backstop ~20, against runaways only.
- At any limit: one final call with tools disabled that answers from what was found and names what is left. Keep `stopped_early` + Continue.
- Batch mode must match streaming. New SSE event types (none planned) would join the stream journal.
- New env vars: `src/config.py` with a default, `.env.example`, both `.env` files (production flips need Jiri's OK), and `docs/features/` (agent-graph / chat-and-streaming).
- Report the cost of every eval run.
- Rule A8 (Jiri, Nov 9 2026): everything ships instrumented for the regular review - a structured log line per decision, the check in `docs/regular-review.md`, and a dated re-measure in TODO.md.
- Repo is public: no hostnames or infrastructure in docs or commits.

## Values (the builder's call, from the spec's ranges)

| Config | Default | Note |
|---|---|---|
| `TURN_BUDGETS_ENABLED` | `false` | Task 6 flips it after the A/B |
| `TURN_COST_LIMIT_USD` | `0.15` | running cost of this turn's model calls |
| `TURN_TIME_BUDGET_SECONDS` | `240` | well under `CHAT_TIMEOUT_SECONDS` (600) |
| `TURN_WRAP_UP_FRACTION` | `0.8` | the one notice |
| `TURN_MAX_TOOL_ROUNDS` | `20` | backstop; `round_cap_override` (deep research subagents, 4) keeps working |
| `TURN_LOOP_BLOCK_AFTER` | `2` | identical failures warned at 1, blocked from the 3rd call |
| `TURN_DUPLICATE_RESULT_MIN_CHARS` | `2000` | a byte-identical repeat this long becomes a back-reference |

## Review Focus

1. **A single tool call that runs past the whole time budget** (a slow fetch or sandbox run) - the turn still gets exactly one tools-off answer, never two, and never a timeout instead of an answer. Test in Task 2 (`test_time_budget_past_due_stops_once`).
2. **The tools-off final call comes back empty** - the turn must not save an empty reply: it falls back to a short "Here is what I found so far" built from nothing more than the model's last text, else a fixed line. Test in Task 3 (`test_empty_final_answer_gets_a_fallback_line`).
3. **An interjection arriving after a limit was hit** - the final answer takes it into account; it never re-opens tools. Test in Task 2 (`test_interjection_after_stop_keeps_tools_off`).
4. **The model fell back to the other tier mid-turn** - the cost guard prices each call with the model that answered it. Test in Task 1 (`test_cost_uses_the_answering_model`).
5. **A subagent run inside a tool call** (`delegate_task`, deep research) - its own graph run has its own budget and does not reset or consume the outer turn's. Test in Task 1 (`test_nested_run_has_its_own_budget`).

---

### Task 1: The turn's budget in the graph state

**Files:**
- Modify: `src/agent/graph_state.py` (new keys), `src/agent/agent.py:377,465` (initial state), `src/agent/chat_node.py:109-146` (running cost)
- Create: `src/agent/turn_budget.py` (limits, pricing helper)
- Modify: `src/config.py` (the Values table), `.env.example`, both `.env`
- Test: `tests/unit/test_turn_budget.py`

**Interfaces:**
- Produces:
  - `AgentState` gains `NotRequired` keys: `turn_started_at: float` (time.monotonic), `turn_cost_usd: float`, `failed_calls: dict[str, int]`, `final_answer: str` (the stop reason once a limit is hit), `wrap_up_noticed: bool`.
  - `initial_state(messages: list[BaseMessage]) -> dict[str, Any]` in `turn_budget.py`: `{"messages", "turn_started_at", "turn_cost_usd": 0.0, "failed_calls": {}}`; both graph invokes in `agent.py` use it.
  - `call_cost_usd(response: AIMessage, model_name: str) -> float` in `turn_budget.py`, from `usage_metadata` and the existing pricing in `src/services/costs.py` (cached input priced as cached).
  - `chat_node` returns `turn_cost_usd = state.get("turn_cost_usd", 0.0) + call_cost_usd(response, answering_model)`; the answering model is `fallback_name` when the fallback answered.

- [ ] **Step 1: Write the failing tests** - `test_initial_state_starts_the_clock`, `test_chat_node_adds_each_calls_cost` (two fake model responses with usage 1000 in / 100 out -> the state's cost equals twice the priced call), `test_cost_uses_the_answering_model` (fallback answered: priced with the fallback's rates), `test_nested_run_has_its_own_budget` (a graph run inside a tool call starts at cost 0 and leaves the outer state's cost unchanged).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_turn_budget.py -q -n0` - Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the keys, `initial_state`, `call_cost_usd`, and the chat node's running total. Config entries per the Values table (comment each with its unit and reason).
- [ ] **Step 4: Run** the test file and `make test` - Expected: PASS; no behaviour change (nothing reads the budget yet).
- [ ] **Step 5: Commit** `feat(agent): the turn's running cost and clock in the graph state`

### Task 2: Limits decide when the turn stops

**Files:**
- Modify: `src/agent/turn_budget.py`, `src/agent/tool_round_check.py:56-239`
- Test: `tests/unit/test_turn_budget.py`

**Interfaces:**
- Consumes: Task 1's state keys.
- Produces:
  - `StopReason = Literal["cost", "time", "rounds", "loop"]`.
  - `budget_stop(state: AgentState, tool_rounds: int, now: float) -> StopReason | None` - cost >= `TURN_COST_LIMIT_USD`, elapsed >= `TURN_TIME_BUDGET_SECONDS`, rounds >= `tool_round_cap()` (which now returns the override or `TURN_MAX_TOOL_ROUNDS` when budgets are on).
  - `wrap_up_due(state, now) -> bool` - elapsed >= fraction x budget and not `wrap_up_noticed`.
  - Every stop logs one `Turn budget stop` line with `reason`, `tool_rounds`, `elapsed_s`, `cost_usd`, and every wrap-up notice and loop block its own line (`Turn wrap-up notice`, `Tool loop blocked` with the tool name, never args) - the regular review reads these.
  - In `check_tool_results`, when `TURN_BUDGETS_ENABLED`: after the interjection check, a stop sets `final_answer: <reason>` plus the final guidance (the existing "answer with what you have, then list what you would do next" text, minus "do not call tools" since tools will be off); a due wrap-up appends `"\n\n[Time is nearly up: finish with what you have in your next reply.]"` to the latest `ToolMessage`'s content and sets `wrap_up_noticed`. The soft nudge and the old round-pressure guidance run only when budgets are off.

- [ ] **Step 1: Write the failing tests** - `test_cost_limit_stops_the_turn`, `test_time_limit_stops_the_turn`, `test_round_backstop_stops_the_turn` (20 rounds; and 4 under `round_cap_override(4)`), `test_wrap_up_notice_once_on_the_tool_result` (at 80%: the latest ToolMessage ends with the notice; the next round adds none), `test_time_budget_past_due_stops_once` (first check already past 100%: one stop, no wrap-up notice, `final_answer == "time"`), `test_interjection_after_stop_keeps_tools_off` (state already has `final_answer`; an interjection arrives: its guidance is added and `final_answer` stays set), `test_budgets_off_keeps_the_old_cap` (flag off: the 6-round guidance and the round-4 nudge as today), `test_a_stop_logs_its_reason` (caplog: one `Turn budget stop` line with reason, rounds, elapsed and cost).
- [ ] **Step 2: Run** - Expected: FAIL.
- [ ] **Step 3: Implement** `budget_stop`, `wrap_up_due`, and the branch in `check_tool_results` (keep each helper under 50 lines; the existing `_round_pressure_update` stays for the flag-off path).
- [ ] **Step 4: Run** the file and `make test` - Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): turn budgets - cost, time and a round backstop decide the stop`

### Task 3: One tools-off final answer

**Files:**
- Modify: `src/agent/chat_node.py`, `src/agent/chat_model.py`, `src/agent/graph.py` (`should_continue`)
- Test: `tests/unit/test_turn_budget.py`, `tests/integration/test_turn_budget_live.py` (marked like the other live-model tests, skipped without a key)

**Interfaces:**
- Consumes: `final_answer` (Task 2).
- Produces: when `state.get("final_answer")`, `chat_node` calls the model with tools disabled and `should_continue` routes to `"end"` whatever the response holds.

- [ ] **Step 1: Spike (no commit)** - with a real key, check whether `invoke(..., tool_config={"function_calling_config": {"mode": "NONE"}})` (or langchain-google-genai's equivalent) works on a model created with `cached_content` (the cache holds the tool declarations). Decision rule: works -> the final call reuses the turn's model with that config (stays cached); fails -> the final call uses `create_chat_model(model_name, with_tools=False, ...)` without the cache. Ledger the result as a ruling; the live test in Step 2 pins whichever path was chosen.
- [ ] **Step 2: Write the failing tests** - `test_final_answer_call_has_no_tools` (fake model records the call; asserts tools disabled per the chosen path), `test_final_answer_ends_the_turn` (a response with tool_calls under `final_answer` still routes to `"end"` and the calls are dropped from the saved message), `test_empty_final_answer_gets_a_fallback_line` (empty text -> the saved reply is the model's last non-empty text from earlier in the turn, if any, followed by the fixed line "I stopped before finishing - say *continue* and I'll pick up from here."; the reply language follows the turn's usual language handling, the fixed line stays English), live `test_final_call_answers_without_tools`.
- [ ] **Step 3: Run** - Expected: FAIL.
- [ ] **Step 4: Implement** the tools-off call in `chat_node` (a helper `_final_answer_call(...)`), the routing in `should_continue`, and the empty-answer fallback.
- [ ] **Step 5: Run** the tests, `make test`, and one batch + one streaming E2E turn on the fake model (`make test-fe-e2e` subset: `chat/*.spec.ts`) - Expected: PASS.
- [ ] **Step 6: Commit** `feat(agent): a stopped turn ends with one tools-off answer`

### Task 4: Loop detector

**Files:**
- Create: `src/agent/tool_loops.py`
- Modify: `src/agent/tool_node.py` (block before running), `src/agent/tool_round_check.py` (record failures, A-B-A-B warning)
- Test: `tests/unit/test_tool_loops.py`

**Interfaces:**
- Produces:
  - `call_signature(name: str, args: Mapping[str, object]) -> str` - sha1 of name + `json.dumps(args, sort_keys=True, ensure_ascii=False)`.
  - `record_results(failed_calls: dict[str, int], calls: list[ToolCall], messages: list[ToolMessage]) -> dict[str, int]` - +1 per failed signature; a successful call of a write-level tool (`WRITE_LEVEL_TOOLS`, `manage_memory`) clears the dict.
  - `blocked_calls(failed_calls, calls) -> set[str]` - ids of calls whose signature failed `TURN_LOOP_BLOCK_AFTER` times; the tool node answers them with an error ToolMessage ("This exact call already failed twice this turn - change the approach or answer with what you have.", `retriable: false`) without running them.
  - `is_ab_cycle(recent: list[str]) -> bool` - the last four round signatures are A, B, A, B; `check_tool_results` adds a one-off warning guidance ("You are alternating between the same two calls...").
  - `dedupe_result(previous: dict[str, str], signature: str, content: str) -> str` - a byte-identical repeat of at least `TURN_DUPLICATE_RESULT_MIN_CHARS` becomes "Same result as the earlier identical call (unchanged)."; state key `seen_results: dict[str, str]` (signature -> sha1 of content).
- All of it runs only when `TURN_BUDGETS_ENABLED`; a blocked loop that leaves nothing else to call sets `final_answer: "loop"` via Task 2's path when the same signature is blocked twice.

- [ ] **Step 1: Write the failing tests** - `test_signature_ignores_arg_order`, `test_third_identical_failure_is_blocked`, `test_a_successful_write_resets_the_count`, `test_ab_cycle_warns_once`, `test_identical_large_result_becomes_a_back_reference`, `test_small_identical_result_is_kept`, `test_loop_stop_after_repeated_blocks`.
- [ ] **Step 2: Run** - Expected: FAIL.
- [ ] **Step 3: Implement** per the Interfaces block (the tool node's existing `_split_blocked_tool_calls` is the pattern for answering calls without running them).
- [ ] **Step 4: Run** the file and `make test` - Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): turn budgets - block repeated identical failures and A-B-A-B loops`

### Task 5: Why the turn stopped, and Continue

**Files:**
- Create: `migrations/0084_message_costs_stopped_by.py` (check the highest number on main right before committing)
- Modify: `src/agent/turn_usage.py` (usage_info `stopped_by`), `src/db/models/cost.py:195` (history query), `src/api/utils.py:154-222,258-359` (`stopped_early` from `stopped_by`), `src/api/routes/chat.py:172`, `src/api/helpers/stream_finalize.py:60,103`, the cost-saving path (store `stopped_by`)
- Test: `tests/integration/test_stopped_by.py`, existing `stopped_early` tests

**Interfaces:**
- Consumes: `final_answer` (Task 2/4).
- Produces: `usage_info["stopped_by"]: StopReason | None`; `message_costs.stopped_by TEXT`; `stopped_early = stopped_by is not None` everywhere (live done event, batch response, history reload). Migration backfills `stopped_by = 'rounds'` where `tool_rounds >= 6` so old capped replies keep their Continue; rollback drops the column.
- With the flag off, `stopped_by` is set to `"rounds"` when the old cap was hit, so one field carries both paths.

- [ ] **Step 1: Write the failing tests** - `test_stopped_by_reaches_the_done_event_and_history` (streaming and batch both), `test_migration_backfills_old_capped_turns`, `test_rollback_0084`.
- [ ] **Step 2: Run** - Expected: FAIL.
- [ ] **Step 3: Implement**; `is_round_capped` stays only for the flag-off path until Task 7.
- [ ] **Step 4: Run** `make test` and the chat E2E subset - Expected: PASS.
- [ ] **Step 5: Commit** `feat(chat): replies record why the turn stopped (cost, time, rounds, loop)`

### Task 6: Measure, then switch on

**Files:**
- Modify: `src/config.py` (default), `.env.example`, both `.env` (production with Jiri's OK), `evals/cases/` (two new cases)
- Test: evals

- [ ] **Step 1: Add eval cases** `budget_hard_to_find` (a fact needing several lookups, judged on the answer) and `budget_loop_bait` (a request whose first search always fails in the fake, e.g. an obscure part number; pass = no third identical call and an honest answer).
- [ ] **Step 2: A/B** - run the hard-to-find cases (`cz_batched_lookups`, `alpine_trip_advice`, the floor-plan/PDF case, the two new ones) with `TURN_BUDGETS_ENABLED=false` then `true`, 2 runs each. Record rounds, cost, judge score per case in the ledger. Report the total USD cost.
- [ ] **Step 3: Decide** - switch on when the judge mean does not drop and cost per case rises no more than 25%; otherwise ledger the numbers and stop for Jiri.
- [ ] **Step 4: Flip the default** to `true` in `src/config.py`, `.env.example` and the local `.env`; ask Jiri before changing the production `.env` (the default applies if it has no key).
- [ ] **Step 5: Commit** `feat(agent): turn budgets on - measured against the round cap`

### Task 7: The old cap goes; docs

**Files:**
- Modify: `src/agent/tool_round_check.py` (remove `_round_pressure_update`'s cap and the soft nudge), `src/config.py` (remove `AGENT_MAX_TOOL_ROUNDS`, `AGENT_TOOL_ROUNDS_SOFT_NUDGE`, `TURN_BUDGETS_ENABLED`), `src/api/utils.py` (remove `is_round_capped`), `.env.example` and both `.env` (remove the keys), `docs/architecture/agent-graph.md`, `docs/features/chat-and-streaming.md`, `TODO.md` (remove part 3 from the Thorough turns item and the Next up line; add a dated re-measure ~2 weeks after deploy: the `stopped_by` mix, p90 cost and time, and retune the values)
- Test: the suite

- [ ] **Step 1:** Remove the flag-off path and its tests (`test_budgets_off_keeps_the_old_cap` goes with it); grep for the removed names in `src`, `tests`, `evals`, `docs` -> none left.
- [ ] **Step 2:** Docs: the agent-graph page describes the budgets (state keys, limits, the final call, the loop detector, `stopped_by`); production check after deploy (counts only): `stopped_by` distribution and p90 turn cost from `message_costs` over the first days.
- [ ] **Step 3:** Gate: `E2E_PORT=8042 caffeinate -i nice -n 10 make pre-commit` green.
- [ ] **Step 4: Commit** `refactor(agent): the round cap and the soft nudge go - turn budgets bound every turn`
- [ ] **Step 5:** Opus review of the branch, one fix pass, deploy (one at a time, health check), CI watch.
