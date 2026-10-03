# Agent Behavior Evals

Golden-case eval harness for agent quality: run real conversations through
`ChatAgent`, check tool behavior deterministically, and score answers with an
LLM judge. Lives in [evals/](../../evals/).

## When to run

Run `make eval` **before and after** changing:
- the system prompt or tool descriptions ([prompts.py](../../src/agent/prompts.py) assembles; texts in [prompt_texts/](../../src/agent/prompt_texts/))
- the graph flow ([graph.py](../../src/agent/graph.py))
- tool registration/bindings
- the default model or thinking settings

Compare pass rates and per-case reasoning. The harness is **informational** —
it hits the live Gemini API (a few cents per run) and is deliberately NOT part
of CI or `make test`.

## How it works

1. Each YAML file in `evals/cases/` is one single-turn case.
2. `evals/run.py` creates an isolated temp database (migrations apply
   automatically) and an eval user, then runs each case through
   `ChatAgent.chat_batch` with the production `DEFAULT_MODEL`.
   Web search is `ddgs` only: the metered providers' keys are blanked
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
mode: sports                    # optional: run with a canned cycling program
program_kv:                     # optional (sports mode): stored program data
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
  garmin:                       # {yesterday}, {in_N_days}, {N_days_ago} expand.
    state: connected            # or disconnected (expired) / not_connected
    data: {get_hrv_data: {hrvSummary: {lastNightAvg: 41}}}
compact_history: true           # optional: compact `history` with the REAL
                                # pipeline first (summarizer LLM calls; the
                                # summarized part is stored + searchable)
deep_research:                  # optional: run the deep-research pipeline on
  question: Headphones under 7 000 Kč   # this fixed plan instead of a chat
  context: Runs outside, rides the tram # turn (docs/features/deep-research.md);
  sub_questions: [Fit when running?, ANC on a tram?]  # gets the run timeout
expect:
  rubric: >                     # required: what the judge grades against
    The answer gives a concrete price, acknowledges fluctuation, and cites
    at least one source.
  required_tools: [research, web_search]   # optional, any-of
  forbidden_tools: [delegate_task]         # optional
  max_tool_rounds: 4                       # optional, 0 = no limit
```

The judge sees the response text PLUS the list of tools actually called and
any formally cited sources — rubrics may reference tool actions ("persists
via kv_store", "cites a source") and the judge can verify them. It cannot see
generated file contents; phrase file-output rubrics as "delivered via
execute_code counts".

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

## Commands

```bash
make eval                                  # all cases, EVAL_WORKERS (4) in parallel
.venv/bin/python evals/run.py --only code_exec   # one case
.venv/bin/python evals/run.py --only 'skill_*,code_exec' --workers 2   # ids/globs, comma-separated or repeated
```

Cases run on a pool of worker **processes** ([pool.py](../../evals/pool.py)),
not threads: `fake_integrations` patches module attributes process-wide, and
seeded memories and past conversations belong to the one eval user, so
cases sharing a process would see each other's state. Each worker owns an
isolated temp database and runs its cases one at a time; the results file
and the report stay in case order. A `--only` pattern that matches nothing
is an error. Keep the pool small: every case makes live Gemini and search
calls, and search-provider fallthrough ("Search provider failed, trying
next") gets more frequent under load.

## Key files

- [evals/run.py](../../evals/run.py) - runner, case loading, judge
- [evals/pool.py](../../evals/pool.py) - parallel worker processes
- [evals/cases/](../../evals/cases/) - golden cases
- [tests/unit/test_eval_harness.py](../../tests/unit/test_eval_harness.py) - unit tests for the pure pieces
- [config.py](../../src/config.py) - `EVAL_JUDGE_MODEL`, `EVAL_CASE_TIMEOUT_SECONDS`, `EVAL_WORKERS`
