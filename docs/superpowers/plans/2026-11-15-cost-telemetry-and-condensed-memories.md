# Cost Telemetry and Condensed Memories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure per-call cache use, prefix sharing and side-call spend; show condensed memories in the per-turn context with the full text a lookup away.

**Architecture:** Side calls write a `side_costs` row through one helper. `_invoke_model` appends a per-call entry (tokens, prefix hash, gap since that prefix was last sent, same user) to `ModelTiming`, which lands in `turn_timing.calls`; the "last sent" record lives in the kv store. Memories gain a `summary` column, cleared by a trigger when the text changes and filled by the scheduler pass with Flash-Lite; the per-turn list shows summaries, `search_memory` takes an id.

**Tech Stack:** Python, SQLite (yoyo), LangChain / google-genai.

**Spec:** docs/superpowers/specs/2026-11-15-cost-telemetry-design.md

## Global Constraints

- Migrations: `0093_side_costs`, `0094_memory_summary` (check the highest number on main right before committing).
- `MEMORY_SUMMARY_MAX_CHARS = 150`, `MEMORY_SUMMARY_MODEL = "gemini-3.5-flash-lite"`, `MEMORY_SUMMARIES_PER_PASS = 20` (plain Config constants with units where they apply; no `.env` changes).
- Telemetry never raises into a turn or a side call: failures are logged.
- A memory without a summary (short, new, or just edited) is shown in full - the list is never wrong, at most longer.
- Static prompt changes: `make prompt-snapshots` in the same commit.
- Gate per task: `make lint` + `make test`; TDD; commit by explicit paths. Evals: report the cost.

## Review Focus

- A memory edited (any path: tool, review, defrag, UI) keeps no stale summary: the trigger clears it (Task 3 test via `apply_memory_batch` and `bulk_update_memories`).
- `search_memory` with an id of another user's memory: nothing returned (Task 3 test).
- The kv "last sent" record under two workers at once: a lost update only skews one gap; no error (accepted, noted in the code).
- A side call whose response has no usage: a row with zero tokens is not written; a log line instead (Task 1 test).
- The scheduler pass with Flash-Lite down: summaries stay null, the pass completes, items still run (Task 3 test).

---

### Task 1: Side-call costs

**Files:**
- Create: `migrations/0093_side_costs.py`, `src/db/models/side_costs.py` (mixin on `Database`), `src/services/side_costs.py`
- Modify: the call sites - `src/agent/title.py`, `src/agent/program_review.py`, `src/agent/instructions_review.py`, `src/api/routes/agent_assist.py` (2), `src/agent/compaction.py`, `src/agent/memory_review.py`; any other side call found by `grep -rn "chat_model(\|generate_content(" src` that does not already reach `message_costs` (freshness and grounding do via the turn)
- Test: `tests/unit/test_side_costs.py`

**Interfaces:**
- Produces: `record_side_cost(feature: str, model: str, usage: object, user_id: str | None = None) -> None` in `src/services/side_costs.py` - `usage` is a LangChain message (its `usage_metadata`) or a google-genai response (its `usage_metadata`); cost via `calculate_token_cost`.

- [ ] Step 1: tests - a LangChain AIMessage with usage 1000 in / 200 cached / 50 out records one row with those tokens and the computed cost; a genai response likewise (`prompt_token_count`, `cached_content_token_count`, `candidates_token_count` + `thoughts_token_count`); no usage -> no row, one warning; a DB error -> logged, not raised; `generate_title` records feature `title` with the title model.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; wire every site with its feature name.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs - `docs/features/` cost page (what `side_costs` holds), `docs/regular-review.md` (side costs per feature per week); commit `feat(costs): record side-call spend per feature`.

### Task 2: Per-call cache telemetry

**Files:**
- Modify: `src/agent/turn_usage.py` (`ModelTiming`, `TurnClock.timing`), `src/agent/chat_node.py` (`_invoke_model`), a small `src/agent/prefix_cache.py` (hash + last-sent record)
- Test: `tests/unit/test_turn_timing.py`, `tests/unit/test_prefix_cache.py`

**Interfaces:**
- Produces: `prefix_key(model_name: str, messages: list[BaseMessage], tool_names: list[str]) -> str` (8 hex, sha256 of the model name, the first SystemMessage's text and the tool names in order); `note_prefix_sent(key: str, user_id: str | None, now: float) -> tuple[float | None, bool | None]` (gap seconds and same-user, None the first time; kv namespace `prefix-cache`, system user, wall-clock seconds).

- [ ] Step 1: tests - two calls with the same prefix 30 s apart by users A then B -> the second has `gap_s` 30 and `same_user` False; a different tool list -> a different key; `turn_timing["calls"]` lists each call's `input`, `cached`, `output`, `ms`, `prefix`, `gap_s`, `same_user`; a batch turn (no prefix info) still records tokens; a kv error -> the call entry without gap, no raise.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; tokens from the response's `usage_metadata` (`input_tokens`, `output_tokens`, `input_token_details.cache_read`); the user id from the request context the tools already use.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs - `docs/regular-review.md` cache section (hit rate by `gap_s` bucket and by `same_user`, first call vs rounds); commit `feat(agent): record each model call's cache use and prefix sharing`.

### Task 3: Condensed memories

**Files:**
- Create: `migrations/0094_memory_summary.py` (column `summary TEXT`, trigger clearing it when `content` changes), `src/services/memory_summaries.py`
- Modify: `src/db/models/memory.py` (`Memory.summary`, `_row_to_memory`, `memories_needing_summary(min_chars, limit)`, `set_memory_summary(id, content, summary)` only if the content is unchanged), `src/agent/scheduler.py` (a summaries step after the items), `src/agent/prompt_memory.py` (list rendering), `src/agent/tools/memory.py` (`search_memory` by id; `memory_fetch` counted), the memory guidance in `src/agent/prompt_texts/`, `src/agent/turn_usage.py` (`memory_fetches` in `turn_timing`)
- Test: `tests/unit/test_memory_summaries.py`, `tests/integration/test_db_memory_summary.py`

- [ ] Step 1: tests -
  - the trigger: updating a memory's content (via `apply_memory_batch` and `bulk_update_memories`) clears its summary; updating only `protected` keeps it;
  - `memories_needing_summary(150, 20)` returns live memories longer than 150 chars without a summary;
  - `summarize_pending()` writes Flash-Lite's summary (cut to 150) and records a `memory_summary` side cost; a memory edited between read and write keeps no summary; Flash-Lite failing -> nothing written, no raise;
  - the list shows a summary with `"full_chars": N` for a condensed memory and the full text for others (no summary, or short);
  - `search_memory("<an id>")` returns that memory's full text; another user's id returns nothing; each id lookup counts one `memory_fetches`;
  - the scheduler pass runs the summaries step after the items and completes when it fails.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; the guidance: entries with `full_chars` are condensed - look the id up with `search_memory` when a detail matters, and before updating one; `make prompt-snapshots`.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: evals - the memory cases (`make eval` with `--only cz_memory_respect,cz_memory_write,memory_write,memory_patch,instructions_fact_stays_memory`) on today's list (before) and with summaries for the eval users' memories (after); report cost; any case that passes before and fails after blocks the commit. Docs: `docs/features/` memory page, `docs/regular-review.md` (`memory_fetches` per turn; pays while < ~1 in 4), TODO (~Nov 23 decision line). Commit `feat(memory): condensed memories in the per-turn context`.
