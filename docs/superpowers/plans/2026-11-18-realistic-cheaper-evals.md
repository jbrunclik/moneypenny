# Realistic, Cheaper Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `make eval` predict how a model does on the family's ordinary chats (long shared synthetic context, write checks, canned web) and cost well under ~$8 a full run, with a cheap per-model comparison.

**Architecture:** Harness-only change under `evals/` (no production code changes). Shared synthetic chats are YAML fixtures that cases inherit via `history_from:`, with a frozen compaction summary seeded as production stores it. New fakes (`FakeWeb`, `FakeCalendar`, stateful `FakeGarmin` workouts) replace HTTP/client seams. The freshness gate's verdict is captured by wrapping `freshness.decide_freshness`. `run.py` gains `--model` and `--repeat`; `ab.py` gains model sides.

**Tech Stack:** Python 3, PyYAML, pytest, `unittest.mock.patch`, httpx (fake `Response` objects), LangChain/Gemini (live runs only).

**Spec:** `docs/superpowers/specs/2026-11-18-realistic-cheaper-evals-design.md`

## Global Constraints

- Public repo: synthetic people, places and numbers only; no hostnames; no real household names, addresses or health data.
- Fakes replace the HTTP/client seam, not the tool: tool formatting, untrusted-content wrapping and error envelopes stay real.
- `.claude/rules/evals.md`: report USD cost for every run; commit `evals/history.jsonl` with the change it measured; metered search keys stay blanked (`EVAL_BLANKED_SEARCH_KEYS`).
- Estimate and report spend before every live run; unit tests never hit the network.
- `--model <id>` swaps the turn's chat model only; `DELEGATE_MODEL`, `DEEP_RESEARCH_SUBAGENT_MODEL`, `AI_ASSIST_MODEL`, `PROGRAM_REVIEW_MODEL`, side models (gate, grounding, summarizer) and the Carbon judge stay as configured.
- A case without a `web:` block runs on canned web with no results (never live). `web: live` keeps today's ddgs path.
- Shared-chat inheritance: the case's own fields win; case `history` is appended after the chat's messages.
- Before committing code: `make lint` and `make test` green, checked via exit code (backend/harness-only change: no E2E needed). Conventional Commits, explicit paths, push, deploy, verify SHA, watch CI by full SHA.

## Review Focus

1. **A canned-web case whose model fetches a URL not in `pages`** - expect the real tool's error envelope for a 404 ("page unavailable"), not a crash and not a live fetch. Test in Task 4.
2. **The freshness gate's prefetch on a canned case** - the gate's lookup goes through `research` → `search_web`/`fetch_page_text`; it must hit `FakeWeb`, not ddgs. Test in Task 4 (patch covers `src.services.search_provider.search_web_detailed`, which `search_web` calls).
3. **A sports-mode case inheriting a shared chat with a frozen summary** - `_program_conversation` stores user turns only; the summary must still reach the turn and the KV compaction state. Test in Task 1.
4. **`garmin_workout update` on a fake workout** - `apply_edits` reassigns step ids; the fake must return the edited workout on the re-fetch so the tool's "refreshed" view is the saved one. Test in Task 3.
5. **A typo in `history_from`** - must fail at load time naming the case and the missing chat, not run a context-free case silently. Test in Task 1.

---

### Task 1: Shared synthetic chats (`history_from`, frozen summary)

**Files:**
- Create: `evals/chats.py`, `evals/fixtures/chats/` (directory; fixtures arrive in Task 7)
- Modify: `evals/run.py` (`EvalCase`, `load_cases`, `_seed_case`)
- Test: `tests/unit/test_eval_chats.py`

**Interfaces:**
- Produces:
  - `EvalCase.history_from: str | None = None`, `EvalCase.frozen_summary: str | None = None`
  - `CHATS_DIR = Path(__file__).parent / "fixtures" / "chats"`
  - `load_chat(name: str, directory: Path = CHATS_DIR) -> dict[str, Any]` - parsed fixture, dates resolved; raises `ValueError(f"unknown shared chat {name!r}")`
  - `merge_chat(case_data: dict[str, Any], chat: dict[str, Any]) -> dict[str, Any]` - raw case dict with inherited `mode`, `program_kv`, `integrations`, `web`, `compact_history` (case wins key by key; `program_kv` and `integrations` merged one level deep, case wins per key), `history = chat.messages + case.history`, `summary` carried as `frozen_summary`
  - `seed_frozen_summary(case: EvalCase, user: Any, db: Any, conversation_id: str) -> list[dict[str, Any]]` - stores every history message in the conversation, writes the compaction KV state (one segment, `end = len(history) - keep`), returns `[_summary_message(summary), *recent]`
- Fixture shape: `{mode?, program_kv?, integrations?, web?, summary?: str, messages: [{role, content, metadata?}]}`

- [ ] **Step 1: Write failing tests**

```python
def test_case_inherits_chat_fields_and_wins(tmp_path):
    chat = {"mode": "sports", "program_kv": {"plan": "A", "log": "x"},
            "messages": [{"role": "user", "content": "ahoj"}, {"role": "assistant", "content": "čau"}]}
    merged = merge_chat({"id": "c", "user": "u", "program_kv": {"plan": "B"},
                         "history": [{"role": "user", "content": "own"}]}, chat)
    assert merged["mode"] == "sports"
    assert merged["program_kv"] == {"plan": "B", "log": "x"}
    assert [h["content"] for h in merged["history"]] == ["ahoj", "čau", "own"]

def test_unknown_chat_fails_at_load(tmp_path):  # Review Focus 5
    (tmp_path / "c.yaml").write_text("id: c\nuser: u\nhistory_from: nope\nexpect: {rubric: r}\n")
    with pytest.raises(ValueError, match="c.yaml.*nope"):
        load_cases(tmp_path)

def test_frozen_summary_seeds_kv_and_history(eval_db):  # sports mode, Review Focus 3
    # 20-message history, keep=12 -> summary message + last 12 verbatim;
    # conv_compaction KV row has covered_count == 8 and the summary text
```

(`eval_db`: reuse the temp-DB fixture `tests/unit/test_eval_harness.py` already uses; if none fits, migrate a `tmp_path` DB the same way `evals/pool.py:_init_worker` does.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_eval_chats.py -v` - expect FAIL (import error).

- [ ] **Step 3: Implement** `evals/chats.py`; in `load_cases`, when `data.get("history_from")`, `data = merge_chat(data, load_chat(...))` before building the case, wrapping errors as `ValueError(f"{path.name}: ...")`. In `_seed_case`, when `case.frozen_summary` and not `case.compact_history`, `history = seed_frozen_summary(...)`. For sports/language mode, `_program_conversation` already stored user turns: `seed_frozen_summary` takes a `store_messages: bool` keyword so the program path does not double-store (`_seed_case` passes `case.mode not in _CANNED_PROGRAMS`).

- [ ] **Step 4: Run** the new tests plus `tests/unit/test_eval_harness.py` - PASS.

- [ ] **Step 5: Commit** `feat(evals): shared synthetic chats with frozen compaction summaries`

### Task 2: `required_actions` check

**Files:**
- Modify: `evals/run.py` (`EvalCase`, `load_cases`, `deterministic_failures`, `_agent_turn`, `_run_case`)
- Test: `tests/unit/test_eval_harness.py`

**Interfaces:**
- Produces: `EvalCase.required_actions: dict[str, list[str]]` keyed by fake name (`todoist`, `garmin`, `calendar`), each a list of regexes that must each match at least one recorded action line of that fake. `deterministic_failures(..., actions: dict[str, list[str]] | None = None)`. `_agent_turn` returns the raw `{name: actions}` alongside the description (6-tuple; update `_memory_review_turn` and every caller).
- `kv_store` writes need no new check: cases use the existing `required_arg_patterns: {kv_store.action: ["^(set|append)$"]}` (confirm the write action names in `src/agent/tools/agent_kv.py` and use them).

- [ ] **Step 1: Failing tests** - `test_required_action_missing_fails` (garmin pattern `^updated workout` vs actions `[]` → one failure naming `garmin` and the pattern); `test_required_action_matched_passes`; `test_required_action_for_absent_fake_fails`.
- [ ] **Step 2: Run** - FAIL.
- [ ] **Step 3: Implement**, parsing `expect.required_actions` like `required_arg_patterns`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/unit/test_eval_harness.py -v` - PASS.
- [ ] **Step 5: Commit** `feat(evals): required_actions checks a fake recorded the write`

### Task 3: Stateful Garmin workouts

**Files:**
- Modify: `evals/fakes.py` (`FakeGarmin`, `fake_integrations`)
- Test: `tests/unit/test_eval_fakes.py`

**Interfaces:**
- Fixture: `garmin: {state, data: {...}, workouts: [<raw Garmin workout JSON>]}` (raw = what `get_workout_by_id` returns: `workoutId`, `workoutName`, `sportType`, `workoutSegments[].workoutSteps[]`).
- `FakeGarmin(data: dict, workouts: list[dict] | None = None)`: `get_workouts(start, limit)` → the workouts list; `get_workout_by_id(id)` → deep copy (unknown id raises `Exception("404 workout not found")`); `update_workout(id, payload)` stores the payload and appends `f"updated workout {name!r}: {summary}"` to `actions`, where summary is the `slim_workout` diff of exercise/sets/reps/weight between old and new (one line per changed step, e.g. `"Bench press weight 60->62.5 kg"`). Everything else keeps the `__getattr__` fixture lookup.

- [ ] **Step 1: Failing tests** driving the real tool: `garmin_workout.invoke({"action": "list"})` lists the fixture; `get` then `update` with a weight edit → `actions` has one `updated workout` line containing `62.5`, and the tool's returned `workout` shows the new weight (Review Focus 4).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_eval_fakes.py -v` - FAIL.
- [ ] **Step 3: Implement**; build the test fixture from an existing workout JSON in `tests/` if one exists (grep `workoutSegments`), else the minimal raw shape `garmin_workout_edits.slim_workout` reads.
- [ ] **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(evals): Garmin fake keeps workouts and records edits`

### Task 4: Canned web (`FakeWeb`)

**Files:**
- Create: `evals/fake_web.py`
- Modify: `evals/fakes.py` (`fake_integrations` takes the case's `web` spec), `evals/run.py` (`EvalCase.web: dict | str | None`, `load_cases`, `_agent_turn`, result field `"web": "canned" | "live"`)
- Test: `tests/unit/test_eval_fake_web.py`

**Interfaces:**
- `FakeWeb(spec: dict[str, Any])` with `results: list[{url, title, snippet}]`, `pages: dict[url, text]`; records `queries: list[str]` and `fetched: list[str]`.
  - `search_web_detailed(query: str, num_results: int) -> tuple[list[dict[str, str]], str]` → `(results[:num_results], "canned")`
  - `fetch_response(url: str, timeout: float | None = None) -> tuple[httpx.Response | None, str | None, int | None]` → canned URL: `httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"}, request=httpx.Request("GET", url))` (wrap plain text in `<html><body>` paragraphs so the real HTML extractor runs); other URL: `(None, f"HTTP 404 for {url}", 404)` matching the real `_fetch_response` error wording (read it).
- Patches when `web` is not `"live"`: `src.services.search_provider.search_web_detailed`, `src.agent.tools.web.search_web_detailed`, `src.agent.tools.web._fetch_response`, and `src.agent.tools.browser._availability_error` → `"The browser is not available here."`
- `fake_integrations(spec, web=...)` puts the fake under `fakes["web"]`; `describe_actions` ignores it (no `actions`).

- [ ] **Step 1: Failing tests** (all through real tools): `research` returns the canned page text wrapped as untrusted content; `fetch_url` of an unknown URL returns the tool's error JSON (Review Focus 1); `web_search` with no `web:` block returns the real no-results note; `freshness.prefetch_messages` with a lookup decision hits `FakeWeb.queries` (Review Focus 2); `web="live"` installs no patch.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_eval_fake_web.py -v` - FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** with `tests/unit/test_eval_fakes.py` - PASS.
- [ ] **Step 5: Commit** `feat(evals): canned web behind the search and fetch seams by default`

### Task 5: Fake Google Calendar

**Files:**
- Create: `evals/fake_calendar.py`
- Modify: `evals/fakes.py` (`fake_integrations`: `calendar` key)
- Test: `tests/unit/test_eval_fake_calendar.py`

**Interfaces:**
- Fixture: `calendar: {state: connected|not_connected, calendars: [{id, summary, primary?}], events: [{id, calendar_id, summary, start: {dateTime|date}, end: {...}, location?, description?}]}` with `{today}`-style placeholders (already resolved by `load_cases`).
- `FakeCalendar(fixture)`: `api_request(method, endpoint, token, params=None, data=None, _retry_on_401=True)` replacing `src.agent.tools.google_calendar._google_calendar_api_request`, serving `/users/me/calendarList`, `GET /calendars/{id}/events` (filtered by `timeMin`/`timeMax` overlap, `q` substring), `GET/PATCH/DELETE /calendars/{id}/events/{eid}`, `POST /calendars/{id}/events`; mutations append to `actions` (`created event 'X' <start>`, `updated event 'X' {fields}`, `deleted event 'X'`). Read the real tool's endpoints and response shapes (`items`, `nextPageToken`) before writing; unknown endpoints raise loudly.
- Connected: also patch `_get_google_calendar_access_token` → `("fake", "eval@example.com")` and `_is_google_calendar_configured` → `True`. `not_connected`: token → `None` (the real not-connected message).

- [ ] **Step 1: Failing tests** via `google_calendar.invoke(...)`: `list_events` for this week returns only in-range fixture events; `create_event` records an action and a following `list_events` sees it; `not_connected` returns the real not-connected text.
- [ ] **Step 2: Run** - FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `feat(evals): Google Calendar fake for logistics cases`

### Task 6: Gate verdict, `--model`, `--repeat`, run log, model A/B

**Files:**
- Modify: `evals/run.py`, `evals/pool.py` (if the env var must reach workers - it does via `os.environ` inheritance; confirm), `evals/ab.py`, `Makefile` (`eval-ab` passes `MODEL_A`/`MODEL_B`)
- Test: `tests/unit/test_eval_harness.py`, `tests/unit/test_eval_ab.py`

**Interfaces:**
- `chat_model() -> str` in `run.py`: `os.environ.get("EVAL_CHAT_MODEL") or Config.DEFAULT_MODEL`; used for `ChatAgent(model_name=...)`, `turn_cost`, `_cost_summary["agent_model"]`. `--model` sets `EVAL_CHAT_MODEL` before workers start and must name a key of `Config.MODELS` (else exit 1 with the list).
- Gate capture: `_agent_turn` wraps `src.agent.freshness.decide_freshness` (patch the module attribute; `agent.py` calls it through the module) recording the decision; result gains `"gate": {"thinking": str | None, "lookup": bool} | None` (None where the gate does not run - standing chats).
- `--repeat N` (default 1): runs the selection N times in one invocation; the results file holds `results` from every repeat with `"repeat": i`; summary prints per case `k/N passed` and overall plus gate-`low` pass rate, and the cost line adds the share spent in `web: live` cases.
- `history_line(...)` gains `"model"`, `"repeat"`, `"web": {"canned": n, "live": m}`, `"gate_low": n`, and per case `[pass, score, gate_thinking]` (k/N form `[passes, N, mean_score, gate_thinking]` when repeating).
- `ab.py`: `--model-a`, `--model-b` (both sides run the working tree with `EVAL_CHAT_MODEL` set; `base` becomes optional when models are given; labels are the model ids). `format_report` adds a line per side: pass rate on cases whose majority gate verdict was `low`. `CaseStats` gains `gate_low: int`.

- [ ] **Step 1: Failing tests**: `test_chat_model_env_override`; `test_unknown_model_rejected`; `test_gate_verdict_recorded` (fake `decide_freshness` returning `FreshnessDecision(lookup=False, thinking="low")` → result `gate == {"thinking": "low", "lookup": False}`); `test_history_line_counts_web_modes_and_gate`; `test_aggregate_counts_gate_low` and `test_report_shows_low_subset` in `test_eval_ab.py`; `test_model_sides_need_no_base`.
- [ ] **Step 2: Run** - FAIL.
- [ ] **Step 3: Implement.** Makefile: `eval-ab` passes `$(if $(MODEL_A),--model-a $(MODEL_A))` etc.; add `eval-model: make eval-model MODEL=<id> [ONLY=...] [REPEAT=2]`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/unit/test_eval_harness.py tests/unit/test_eval_ab.py -v` then `make lint` - PASS, exit 0.
- [ ] **Step 5: Commit** `feat(evals): --model, --repeat and the gate's verdict per case`

### Task 7: Author the shared chats and freeze their summaries

**Files:**
- Create: `evals/fixtures/chats/{cycling_program,strength_program,family_logistics,project_research}.yaml`, `evals/freeze_summary.py`
- Test: `tests/unit/test_eval_chats.py` (fixture sanity)

**Interfaces:**
- `evals/freeze_summary.py <chat-name>`: runs the real summarizer (`compaction_segments.extend_segments`) over the chat's older messages (all but `CONVERSATION_COMPACTION_KEEP_RECENT`), joins segments with `render_segments`, writes it to the fixture's `summary:` key; prints the estimated cost. Live call (~$0.01-0.03 a chat): report it.
- Content targets (spec "Shared synthetic chats"): mostly Czech, rambling follow-ups, tool digests in `metadata.tool_outputs`, program data in `program_kv`; program chats ~20-35k characters, ordinary ~15-25k. `cycling_program`: Garmin `data` with recent activities and HRV. `strength_program`: Garmin `workouts` (Task 3 shape) edited in earlier turns. `family_logistics`: `todoist` + `calendar` fixtures. `project_research`: canned `web` with an earlier research turn's sources and an artifact reference.

- [ ] **Step 1: Failing test** `test_shared_chats_are_realistic`: every fixture loads; ≥20 messages; rendered size inside its kind's range; ≥60% of user messages detected Czech (`langdetect`); program chats have `program_kv`; each has a non-empty `summary`. (No automated PII check - the names would have to live in the public repo to be checked. Instead, Step 3 ends with a read-through: every person, place and health figure is invented.)
- [ ] **Step 2: Run** - FAIL (no fixtures).
- [ ] **Step 3: Write the four chats**; run `PYTHONPATH=. .venv/bin/python evals/freeze_summary.py <name>` for each; read every summary and fix any wrong fact in the chat or summary.
- [ ] **Step 4: Run** - PASS.
- [ ] **Step 5: Commit** `test(evals): four shared synthetic chats with frozen summaries` (report summarizer spend in the message body).

### Task 8: Cases on shared chats; web cases to canned

**Files:**
- Create: ~25 `evals/cases/*.yaml` with `history_from:`
- Modify: the 15 web-dependent cases (`cz_batched_lookups`, `cz_date_recent_event`, `cz_grounded_no_note`, `cz_history_no_flags`, `cz_local_lookup`, `cz_screenshot_poll_grounding`, `cz_trip_plan_precision`, `dependent_followup_search`, `deep_research_offer_recall`, `fresh_office_holder`, `fresh_keynote_followup`, `fresh_pushback_holds`, `fresh_opinion_current_politics`, `research_multi_source`, `web_lookup_cited`) plus any other case whose last result used `research`/`web_search`/`fetch_url` (check the latest `evals/results/*.json`)

- [ ] **Step 1: Pick the ~5 live cases** (one each: freshness/current events, price lookup, multi-source research, Czech query, deep-research end to end) and mark them `web: live`; give the rest a `web:` block with realistic pages (3-6k characters, boilerplate, a partial answer, one disagreeing source).
- [ ] **Step 2: Write the shared-chat cases**: about half answer from context (recall the plan, follow an earlier instruction, keep tone/language), half use integrations; each program-chat logging case carries `required_arg_patterns` for the `kv_store` write and, where the program says so, `required_actions: {garmin: ["^updated workout"]}`; `family_logistics` cases use `required_actions: {calendar: [...]}`/`{todoist: [...]}`. Aim for 20+ turns the gate will rate `low` (ordinary recall and logistics).
- [ ] **Step 3: Load check** `.venv/bin/pytest tests/unit/test_eval_harness.py -k load -v` and `PYTHONPATH=. .venv/bin/python -c "from evals.run import load_cases; from pathlib import Path; print(len(load_cases(Path('evals/cases'))))"` - loads without error.
- [ ] **Step 4: Targeted live check** (estimate first: ~$0.06 a long-context case → ~$2 for the new cases): `make eval ONLY='<new ids>'`; fix cases that fail for case reasons (wrong fixture, ambiguous rubric), not model reasons. Report cost.
- [ ] **Step 5: Commit** `test(evals): cases on shared chats, web cases on canned pages` with `evals/history.jsonl`.

### Task 9: Baseline, docs, instrumentation

**Files:**
- Modify: `docs/testing/evals.md`, `.claude/rules/evals.md`, `TODO.md`, `evals/history.jsonl`

- [ ] **Step 1: Full Hydrogen run** (estimate ~$5-6 / ~20 min; tell the user before starting): `nice -n 10 make eval`. Then `make eval-model MODEL=gemini-4-hydrogen ONLY='<shared-chat ids>' REPEAT=2` only if the user OKs the extra ~$3.
- [ ] **Step 2: Docs**: `docs/testing/evals.md` - shared chats and `history_from`, `freeze_summary.py`, canned vs live web and which cases stay live, `required_actions`, `--model`/`--repeat`/model A/B, the gate-`low` subset, the new baseline (cost, minutes, pass rate, low-case count) replacing "~$8 / 23 minutes", smoke cost. `.claude/rules/evals.md`: canned web default, cost figure.
- [ ] **Step 3: TODO.md**: "When Gemini 4 Helix ships: `make eval-ab MODEL_A=gemini-4-hydrogen MODEL_B=<helix> RUNS=2` on the full suite; route gate-`low` turns only if its low-subset pass rate holds" and "Re-check the eval suite's cost and flakiness ~Dec 18 2026 (baseline <date>: $X)".
- [ ] **Step 4: Gate** `make lint` and `make test`, exit codes checked.
- [ ] **Step 5: Commit** `docs(evals): realistic suite baseline and how to compare a model`, push, deploy, verify SHA, watch CI by full SHA.
