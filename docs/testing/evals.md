# Agent Behavior Evals

Golden-case eval harness for agent quality: run real conversations through
`ChatAgent`, check tool behavior deterministically, and score answers with an
LLM judge. Lives in [evals/](../../evals/).

## When to run

Run `make eval` **before and after** changing:
- the system prompt or tool descriptions ([prompts.py](../../src/agent/prompts.py) assembles; texts in [prompt_texts/](../../src/agent/prompt_texts/))
- the graph flow ([graph.py](../../src/agent/graph.py) and its nodes: `chat_node.py`, `tool_node.py`, `tool_round_check.py`)
- tool registration/bindings
- the default model or thinking settings

Compare pass rates and per-case reasoning. The harness is **informational** —
it hits the live Gemini API and is deliberately NOT part of CI or `make test`.
A full run on Gemini 4 Hydrogen cost ~$8 and took ~23 minutes (107 cases,
all web live, Nov 14 2026). The Nov 18 2026 suite (145 cases: 25 long-chat
cases at $0.93 together, canned web for all but 13 cases) is estimated at
~$5-6 and has not had a full run yet: its first full run is the Hydrogen side of the Gemini 4 Helix comparison (TODO). On Nov 19 2026 the smoke subset cost $0.99 (live web $0.10 of it). For a targeted change run only the affected cases with
`--only`, and A/B a suspicious failure against the previous commit in a
worktree before trusting one run.

**Smoke subset** (Nov 17 2026): `make eval-smoke` runs the 26 cases marked
`smoke: true` - a cheap spread over plain answers, Czech, the freshness gate,
memory, tool-output recall, artifacts, skills, schedules, instructions,
injection, episodic recall, ask_choice and the deep-research offer - for about
$1 in ~7 minutes (first run: $1.28 with two pricier web cases since swapped
out). Run it on any change to `src/agent/`. Its web cases share the laptop's
ddgs throttling: read a web failure's reason before blaming the change.

**Known targets**: `known_failure: <why>` marks a case the agent fails today
on purpose (none since Nov 19 2026: `cz_batched_lookups` and
`fresh_opinion_current_politics` passed once their web was canned - their
failures came from canned search returning one list for every query and
from live pages drifting off the rubric's frozen facts). It still
runs and is judged, but reports `TARGET` instead of `FAIL`, so a run's FAIL
lines are the new failures; a target that passes is reported as "TARGET
PASSED" - drop its marker once it keeps passing.

**Not the agent** (Nov 19 2026): a `web: live` case that fails while every
search of its turn failed (`web_search` errors, `research` "All searches
failed" - the laptop's ddgs throttles) reports `INFRA` instead of `FAIL`, like
a timeout; `ab.py` counts it outside the pass rate. "No results" is a real
outcome and still a FAIL. A canned case whose turn fetched a page its
capture lacks is listed under "Canned pages missing" in the summary
(`web_calls.missing` in the results): an incomplete capture made
`dependent_followup_search` untestable until a population page was added -
recapture before blaming the agent.

**Dates in fixtures**: never write a fixed date or weekday the case depends
on - "exam on the 20th" (`ask_choice_real_fork`) and "Tuesday 12 November"
(`memory_injection_pasted_email`) went stale within days and failed correct
answers. Use the placeholders (they expand in the user message, history,
rubric and fixtures alike). `schedule_reminder_confirm` is deliberately dated
(15 March 2028; its header says to move it before then).

**Run log**: every run appends one line to the tracked
[evals/history.jsonl](../../evals/history.jsonl) (`evals/results/` is
gitignored): time, git sha (`-dirty` with uncommitted changes), agent and
judge model, the selection (`all`, `smoke` or the `--only` patterns), repeat,
passed over ran, the known targets that failed, cost (and the part spent in
live-web cases), minutes, canned vs live web case counts, the number of
gate-`low` cases, the `infra` cases and `canned_missing` (pages fetched but
not captured, per case), and `[pass, score, gate thinking]` per case
(`[passes, runs, mean score, gate]` with `--repeat`). Runs before Nov 18 2026
had no canned web and fewer, shorter cases - do not compare them as equals. Commit it with the change it measured, so the next run has
something to compare against.

**A new tool can make a case stale.** When a tool lands that is the better
answer to a case's request, the case fails "correctly": `cz_todoist_add_task`
asked "remind me tomorrow about the plumber" and required `todoist` (written
Sep 29 2026, when Todoist was the only way to remember anything); from Nov 7
the `schedule` reminder was the right call, and production users approved
those cards. Reword the request to test what the case is for (Nov 14: a task
capture) instead of steering the agent back to the old tool.

## How it works

1. Each YAML file in `evals/cases/` is one single-turn case.
2. `evals/run.py` creates an isolated temp database (each worker
   migrates it, `evals/pool.py`) and a temp blob store next to it (`BLOB_STORAGE_PATH`, so
   attachments and generated files never land in the repo's dev `files.db`),
   and an eval user, then runs each case through
   `ChatAgent.chat_batch` with the production `DEFAULT_MODEL` (or `--model`).
   Web is **canned by default** (Nov 18 2026, [fake_web.py](../../evals/fake_web.py)):
   a case's `web:` block answers every search and page fetch through the real
   tools' seams, and a case without one finds nothing. Only `web: live`
   cases search for real, and there search is `ddgs` only: the metered providers' keys are blanked
   (`EVAL_BLANKED_SEARCH_KEYS`), because the local `.env` holds the same
   keys as prod and eval usage was counted only in the throwaway database -
   until Oct 2 2026 every eval search spent the real monthly quota unseen by
   prod's counters. Results before that date were measured on Brave/Tavily
   search results, so compare pass rates across the switch with care.
3. Deterministic checks run first: `required_tools` (any-of), `forbidden_tools`,
   `max_tool_rounds`.
4. An LLM judge (`EVAL_JUDGE_MODEL`, default Gemini Pro) scores the response
   1–5 against the case rubric and decides pass/fail.
5. Results print as a summary and land in `evals/results/<timestamp>.json`
   (gitignored).

A case passes only if the judge passes it AND no deterministic check failed.
Cases with unmet `requires` (e.g. `code_sandbox` without Docker) are skipped.

## Case format

```yaml
id: web_lookup_cited
description: Current-fact question requires a web tool and a citation
user: What is the current price of Bitcoin in USD?
requires: [code_sandbox]        # optional: skip when unavailable
history_from: family_logistics  # optional: a shared synthetic chat (evals/fixtures/chats/)
                                # whose messages precede `history` and whose mode,
                                # program, program_kv, integrations, web and artifacts
                                # the case inherits (the case's own fields win)
web:                            # optional: canned web (absent = searches find nothing)
  results: [{url: "https://...", title: "...", snippet: "..."}]  # every search returns these
  pages: {"https://...": "page text"}   # a fetch of another URL gets the real 404 envelope
# web: live                     # instead: the real ddgs search (13 cases, on purpose)
smoke: true                     # optional: in the make eval-smoke subset
known_failure: >                # optional: a known target - TARGET, not FAIL
  Why it fails today.
mode: sports                    # optional: chat (default) / sports / language / agent -
                                # a canned standing chat (cycling program, Italian
                                # program, garden agent) built like production
                                # (standing_for_program); e.g. language_quiz_block,
                                # agent_chat_remind_me
program: {id: strength, name: Posilovna}  # optional: the program a sports/language
                                # chat runs as (default: the canned one)
program_kv:                     # optional (sports / language mode): stored program data
  "cycling:routine": "po: kliky, st: trenazer 60min"
history:                        # optional: prior turns for multi-turn cases
  - role: user
    content: Plan me a hike.
  - role: assistant
    content: "Suggested: 9 km karst loop."
    metadata:                   # optional: enriched-history metadata (MSG_CONTEXT),
      tool_outputs: 'garmin_connect({}) -> {"hrv":62}'  # e.g. a persisted tool digest
integrations:                   # optional: fake backends (evals/fakes.py) behind
  todoist:                      # the REAL tools - only the HTTP/client seam
    projects: [{id: p1, name: Work}]   # is replaced. {today}, {tomorrow},
    tasks: [{id: t1, content: "Send invoice", project_id: p1, due: {date: "{today}"}}]
  garmin:                       # {yesterday}, {in_N_days}, {N_days_ago} expand;
    state: connected            # {tuesday} / {monday_plus_N} = the next such weekday
    data: {get_hrv_data: {hrvSummary: {lastNightAvg: 41}}}   # (+N days); _cs / _weekday / _long
    workouts: [<raw get_workout_by_id JSON>]   # give "středa" / "Wednesday" / "Wednesday 25 November".
                                # Saved workouts are stateful; garmin_workout updates
                                # are recorded ("updated workout 'X': field old->new")
  calendar:                     # Google Calendar fake (fake_calendar.py): range-filtered
    state: connected            # reads, create/update/delete recorded
    events: [{id: e1, summary: Keramika, start: {dateTime: "{tuesday}T15:30:00+01:00"}, end: {...}}]
compact_history: true           # optional: compact `history` with the REAL
                                # pipeline first (summarizer LLM calls; the
                                # summarized part is stored + searchable)
deep_research:                  # optional: run the deep-research pipeline on
  question: Headphones under 7 000 Kč   # this fixed plan instead of a chat
  context: Runs outside, rides the tram # turn (docs/features/deep-research-ops.md#evals);
  sub_questions: [Fit when running?, ANC on a tram?]  # gets the run timeout
memory_review: true             # optional: run the background memory review
                                # over `history` + `user` instead of a turn;
                                # its applied ops are graded as one
                                # manage_memory call (memory-and-context.md)
documents:                      # optional: saved documents seeded for the case
  - title: Equity waterfall     # (memory-and-context.md#saved-documents-document-memory);
    summary: Option value by exit valuation   # file is relative to evals/
    use_for: Exit scenarios     # valid_until: optional YYYY-MM-DD.
    file: fixtures/equity_waterfall.pdf  # A case that seeds documents or grades
                                # manage_documents / open_document runs as its own
                                # fresh user, so libraries never leak between cases
artifacts:                      # optional: seeded in the case's conversation;
  - title: Tip calculator       # their ids replace {artifact_0}, {artifact_1}...
    html: <div class="mp-card">...</div>  # in `history` (e.g. metadata
                                # artifacts: "{artifact_0} v1 'Tip calculator'")
expect:
  rubric: >                     # required: what the judge grades against
    The answer gives a concrete price, acknowledges fluctuation, and cites
    at least one source.
  required_tools: [research, web_search]   # optional, any-of
  forbidden_tools: [delegate_task]         # optional
  max_tool_rounds: 4                       # optional, 0 = no limit
  gate_lookup: true                        # optional: the freshness gate's own
                                           # decision (true = it looked up first)
  forbidden_arg_patterns:                  # optional: regexes that must NOT
    create_artifact.html: ['https?://']    # match a tool argument ("tool.arg")
  required_arg_patterns:                   # optional: each regex must match the
    manage_memory.operations: ['valid_until']  # argument of some call to that tool
  required_actions:                        # optional: each regex must match an action
    garmin: ["^updated workout 'Sila A"]   # a fake recorded (todoist, garmin, calendar)
                                           # - the write a turn must make, judge-free
```

The judge sees the response text PLUS the list of tools actually called and
any formally cited sources — rubrics may reference tool actions ("persists
via kv_store", "cites a source") and the judge can verify them. It cannot see
generated file contents or tool arguments; phrase file-output rubrics as
"delivered via execute_code counts", and check arguments deterministically with
`forbidden_arg_patterns` (the [artifact](../features/artifacts.md) cases use it
for hex colours, fixed widths and URLs in `create_artifact.html`) and
`required_arg_patterns` (`memory_until`: the memory gets a `valid_until`).

Grounding verdicts are shown IN PLACE: `annotate_for_judge()` in
[run.py](../../evals/run.py) inserts each annotation right after its claim -
`claim [UNSOURCED: reason]`, `[PARTLY SOURCED: ...]`, `[CONTRADICTED BY SOURCE:
...]`, or `[source N]` on a supported claim - the way the UI underlines it.
An appended list of claims reproduced the Oct 2 end-note failure (the judge
read the text as fact). Grounding rubrics name those tags, not the old
`_(neověřeno)_` markers.

Authoring tips:
- Verify rubric numbers yourself first (the first harness run caught a wrong
  expected value in a rubric, not in the agent).
- `required_tools` is any-of — list all acceptable tools for the behavior.
- Keep failing cases that represent real improvement targets; the harness is
  a baseline tracker, not a green wall. Known-failing baselines (Aug 2026):
  `research_multi_source` (round overrun), `web_lookup_cited` (citation
  adherence).

Long-chat and cross-turn cases (Sep 2026):
- `cz_compaction_recall` — 30-message history with early specifics (booking
  code, price, allergy) compacted by the real segment pipeline; the answer
  must recall them exactly. Guards the segmented-summary + search fallback.
- `cz_tool_output_recall` — a follow-up about an earlier Garmin result must be
  answered from the `tool_outputs` digest with `garmin_connect` forbidden.
  Control check: with the digest stripped the model re-calls Garmin and the
  case fails, so it discriminates.
- `cz_batched_lookups` — four independent lookups with `max_tool_rounds: 3`;
  reproduces the one-search-per-round pattern behind most round-cap hits.

Integration cases (Sep 2026) - fake Todoist/Garmin backends, since the eval
environment has no credentials and those tools were the biggest error
sources in production. The fake Todoist validates filters like the real API
(natural-language filters are rejected with error_code 55); mutations are
listed to the judge as "integration changes":
- `cz_todoist_add_task` — verb-first task, due tomorrow, placed in the right
  project/section.
- `cz_todoist_work_today` — filtered read (project + today + priority).
- `cz_garmin_readiness` — advice grounded in a readiness snapshot.
- `cz_garmin_disconnected` — must say the EXISTING connection broke and point
  to Settings. Control: with the pre-fix "Garmin not connected" message it
  scores 1/5, with the current message 5/5.

Sweep cases (Oct 2026) - from the Sep 2026 conversation sweep. Rubrics expand
the same date placeholders as `integrations` (plus a `_weekday` suffix, e.g.
`{today_weekday}`), so date-relative expectations stay valid:
- `cz_photo_who` — a "who is this?" photo of an AI-generated, non-existent
  person ([person_speaker.jpg](../../evals/fixtures/person_speaker.jpg)); any
  name, even hedged, fails. Before the no-names-from-appearance rule it passed
  1/3 (named a guess, or spent 6-10 rounds searching the web); after, 5/5 with
  zero tool rounds.
- `cz_date_weekday`, `cz_date_recent_event` — weekday/day-count arithmetic
  from the supplied date, and a post-cutoff event treated as past. Both
  already passed 3/3 before the date-authority rule; they are regression
  guards, not reproductions of the sweep's date corrections.
- `cz_grounded_no_note` — precision guard for the
  [grounding check](../features/grounding.md): a fully sourced CNB-rate answer
  must carry no `[UNSOURCED]`, `[PARTLY SOURCED]` or `[CONTRADICTED BY SOURCE]`
  tag.
- `cz_trip_plan_precision` — the prod complaint shape: a Saturday trip plan
  with its own timeline. Fails on any such tag on a plan time or a well-known
  town, or on more than 2 of them. Under the Oct 2 in-place markers it went
  1/3 to 2/5 after a precision pass; the remaining failures were the COUNT of
  flags on cafés the model adds on its own, which the sources really don't
  mention (honesty vs noise).

With the Oct 3 annotations (two-list verifier, verdicts shown in place)
`skill_product_where_to_buy` passes 4/5 and the full suite 61/63 (baseline
before the change 60/62).

Skill cases (Sep 2026) - `skill_*` cases guard the
[skills](../features/agent-tools.md#skills) trigger gate. Should-trigger cases
(`skill_excel_totals`, `skill_czech_pdf`, `skill_trip_weekend`, ...) require
`load_skill`; should-not cases (`skill_not_*`) forbid it. A new or changed skill
needs at least 90% loads on its should-trigger runs, zero loads on should-not
runs, and an unchanged suite pass rate. `skill_product_where_to_buy` is an
honesty probe: the skill loads every time, but the answer mixed dealers and
prices from the model's own knowledge into verified results without labelling
them. The grounding directive did not help (1/5); with the
[grounding check](../features/grounding.md) flagging those specifics on the
claim itself it passes 4/5 (the rubric accepts a text label or a grounding
tag).

Note: each case runs under its own request id. Before Sep 29 2026 it did not,
which left the per-turn efficiency nudges (turn_usage) inert - round counts
from earlier runs were measured with every nudge off.

Shared synthetic chats (Nov 18 2026) - 95 of 120 cases had no earlier turns
while a production turn carries 15-23 recent messages, often a compaction
summary and program data: the long context where a weaker model loses
instructions. Four long, mostly Czech, deliberately rambling conversations
live in [evals/fixtures/chats/](../../evals/fixtures/chats/) -
`cycling_program` and `strength_program` (sports mode, Garmin data and saved
workouts edited along the way), `family_logistics` (Todoist + Calendar) and
`project_research` (research digests, an artifact, canned pages on fictional
sites). Synthetic people, places and numbers only - the repo is public. 25
`chat_*` cases add one turn each; about half answer from context, the rest
must make a write (`chat_strength_log_and_sync` is the Nov 13-17 production
failure: answer, but never save the session or update the watch).
- Each chat's older turns arrive as a **frozen summary** (`summary:`), seeded
  as production stores compaction state, so every run sees the same context
  and pays no summarizer calls. Regenerate it after editing a chat:
  `PYTHONPATH=. python evals/freeze_summary.py <chat>` (~$0.01 a chat, the real
  summarizer) - then READ it: a wrong fact there is wrong in every case.
  The live pipeline keeps its own cases (`compact_history: true`).
- Prose that names weekdays must use weekday placeholders: `family_logistics`
  first used `{in_2_days}` for "ve středu", and on a non-Monday the calendar
  and the chat disagreed (a model was failed for being right). It now anchors
  every date on `{monday_plus_N}`.

Canned web pages (Nov 18 2026) - for cases about real products, places and
routes the pages are the real ones, captured once with
[capture_web.py](../../evals/capture_web.py) (search, read the hits like the
research tool, write the `web:` block). From a laptop ddgs returned ads and
nothing, so the 15 captures ran on the production host against copies of
the cases: its search router used Exa (34 calls), counted in production's own
usage counters. Recapture a case when its pages go stale. Cases about TODAY's
facts (who holds an office, today's rate or opening hours, a recent event),
the browser and deep research stay `web: live` - their comment says why.

## Comparing a model

`--model <id>` swaps the turn's chat model only (`EVAL_CHAT_MODEL`, inherited by
the workers); delegate, deep-research subagents, the side models (freshness
gate, grounding, summarizer) and the judge stay as configured, because the
question is "can this model answer the turn". The id must have a
`MODEL_PRICING` entry, or its spend would be priced as another model's.
Each result records the freshness gate's verdict (`gate: {thinking, lookup}`);
routing would only move the turns it rates easy (`low`), so the report gives
the pass rate on those too. `--repeat N` runs the selection N times (results
carry `repeat`, the log `k/N` per case) - one run reads luck.

```bash
make eval-model MODEL=<id> ONLY='chat_*' REPEAT=2       # one model, repeated
make eval-ab MODEL_A=gemini-4-hydrogen MODEL_B=<id> ONLY='*' RUNS=2   # side by side
```

## Commands

```bash
make eval                                  # all cases, EVAL_WORKERS (4) in parallel
make eval-smoke                            # the ~$1 smoke subset (smoke: true)
.venv/bin/python evals/run.py --only code_exec   # one case
.venv/bin/python evals/run.py --only 'skill_*,code_exec' --workers 2   # ids/globs, comma-separated or repeated
make eval-ab BASE=main~1 ONLY='sports_*,cz_local_lookup' RUNS=2   # A/B: BASE vs the working tree
```

**A/B across two commits** ([evals/ab.py](../../evals/ab.py), Nov 14 2026): runs
the selected cases `RUNS` times on each side - the base in a temporary
worktree under `.claude/worktrees/eval-ab-<sha>`, the head the working tree
(uncommitted changes included) or `--head <ref>` - alternating sides so
provider drift hits both, then prints per case passes over judged runs, mean
judge score and tool rounds, marking a case whose pass rate moved by half or
whose score moved by a point (`<<`). Timeouts, crashes and `INFRA` results count as `infra`,
outside the pass rate (a search outage says nothing about the change). Use
it before trusting one run: on Nov 14 a ZWO case went 0/2 vs 2/2 on the
previous commit - a real regression a single run could not tell from noise.

Cases run on a pool of worker **processes** ([pool.py](../../evals/pool.py)),
not threads: `fake_integrations` patches module attributes process-wide, and
seeded memories and past conversations belong to the one eval user, so
cases sharing a process would see each other's state. Each worker owns an
isolated temp database and blob store and runs its cases one at a time; the results file
and the report stay in case order. A `--only` pattern that matches nothing
is an error. Keep the pool small: every case makes live Gemini and search
calls, and search-provider fallthrough ("Search provider failed, trying
next") gets more frequent under load.

## Key files

- [evals/run.py](../../evals/run.py) - runner, case loading, judge
- [evals/pool.py](../../evals/pool.py) - parallel worker processes
- [evals/chats.py](../../evals/chats.py), [evals/fixtures/chats/](../../evals/fixtures/chats/) - shared synthetic chats; [freeze_summary.py](../../evals/freeze_summary.py) freezes their summaries
- [evals/fakes.py](../../evals/fakes.py), [fake_web.py](../../evals/fake_web.py), [fake_calendar.py](../../evals/fake_calendar.py) - integration and web fakes; [capture_web.py](../../evals/capture_web.py) captures canned pages
- [evals/ab.py](../../evals/ab.py) - A/B across commits or models
- [evals/cases/](../../evals/cases/) - golden cases
- [tests/unit/test_eval_harness.py](../../tests/unit/test_eval_harness.py) - unit tests for the pure pieces
- [config.py](../../src/config.py) - `EVAL_JUDGE_MODEL`, `EVAL_CASE_TIMEOUT_SECONDS`, `EVAL_WORKERS`
