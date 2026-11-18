# Realistic, Cheaper Evals - Design

Nov 18 2026. Status: approved Nov 18 2026 (synthetic shared chats, canned web; Garmin writes + Calendar fakes in scope).

## Intent

Make `make eval` predict how a model would do on the family's ordinary chats,
and make a full run cheaper than today's ~$8. The trigger is the expected
Flash-Lite tier of Gemini 4 ("Helix", unreleased as of Nov 18 2026): 3.5
Flash-Lite failed the suite, and we want to know - quickly, cheaply and
believably - whether a Lite model can take the easy share of chat turns
(routed by the freshness gate) while Hydrogen keeps the rest.

## What is wrong today (measured Nov 18 2026)

- **Context does not look like production.** 95 of 120 cases have no earlier
  turns; 90% have under 200 characters of history (max 31k). A production
  chat sends 15-23 recent messages (17-35k characters), often a compaction
  summary (13-16k characters), and in program chats the stored program data
  and tool digests: a sports turn's first call carries a median 54k input
  tokens, an ordinary chat's ~27k. Lite models fail precisely on long
  context (lost instructions, forgotten program data) - the suite cannot see it.
- **The tool mix does not look like production.** 14 cases require web tools
  and they dominate cost; only 7 cases are sports chats, 3 use the Garmin
  fake, 7 the Todoist fake. Production's most-used integrations are
  `garmin_connect`, `kv_store`, `todoist`, `google_calendar`. Nothing checks
  that a sports turn saves its log (`kv_store` write) and the workout
  (`garmin_workout`) - the failure seen in production on Nov 13-17.
- **Cost sits in live web cases.** Last week's 65 distinct cases: $4.18, judge
  $0.24 (6%). The 10 priciest (mostly multi-round web research, up to 9
  rounds and 250k input tokens) are 44% of spend, the top 20 are 61%; the
  median case is $0.04. Those cases are also the noisiest (ddgs throttles
  the laptop; results change daily).
- **One run is noise.** The Nov 17 smoke run scored 20/26; the two failures
  rerun alone passed. Comparing two models on one run each reads luck.

## Goals

1. Long, realistic context in a meaningful share of cases (target: at least
   25 cases on a shared long chat), with program chats checked for the writes
   they must make.
2. Web cases deterministic and cheap: canned results by default, a small
   live-web set kept on purpose.
3. A model comparison that reports per-case flips over repeated runs, not a
   single pass rate.
4. A full Hydrogen run measurably cheaper than ~$8 (expected ~$5-6 with the
   added context; measured, not promised), and a cheap way to run the suite
   on another model (`--model`), e.g. ~$1-1.50 for a Lite model.

## Non-goals

- No production conversations, in the repo or on the laptop (decided Nov 18
  2026: synthetic only). Replaying real turns is a later, separate decision.
- No Flex or Batch for the judge (6% of cost; see cost-tracking.md, Flex tier).
- Not part of CI or `make test`; stays informational.
- No model routing change - that comes after Helix ships and passes.

## Anti-goals (would make this a failure even if it works)

- **A greener suite that predicts less.** Canned pages so short or so
  on-the-nose that research behaviour (choosing sources, reading past the
  first result, admitting a gap) is no longer tested. Canned pages must look
  like real pages: boilerplate, partial answers, one source that disagrees.
- **Synthetic chats that read like test fixtures** (tidy, short, English,
  one topic). They must look like the family's: mostly Czech, rambling
  follow-ups, earlier tool digests, program data, a compaction summary.
- **Real family data in a public repo.** Synthetic people, places and numbers
  only; no names, addresses or health data of real household members.
- **Losing comparability silently.** The run log must say which cases ran on
  canned vs live web and the repeat count, so runs before and after this
  change are not compared as equals.

## Approaches considered

**Realistic context**

- **A. Shared synthetic chats (chosen).** 4-5 long conversations written once
  under `evals/fixtures/chats/` and referenced by cases (`history_from:`),
  each case adding only its final turn (and optionally a few turns of its
  own). Cheap to write, consistent, one place to keep realistic.
- B. A long `history` inline in each case: precise per case but heavy to
  write and maintain, and inconsistent across cases. Rejected.
- C. LLM-generated histories at run time: non-deterministic and costs money
  every run. Rejected.

**Web cases**

- **A. Canned web per case (chosen).** A fake behind the search and fetch
  seams, like the Garmin/Todoist fakes: every search returns the case's
  canned result list, a fetch of a canned URL returns its canned page, any
  other URL a realistic "page unavailable" error. Deterministic and cheap; a
  case keeps `web: live` to test real searching (about 5 cases).
- B. Record a live run and replay it: breaks whenever the model words a query
  differently (it does, run to run), so it falls back to live or fails.
  Rejected.

## Design

### Shared synthetic chats

`evals/fixtures/chats/<name>.yaml` - same message shape as a case's
`history` (role, content, optional `metadata` such as `tool_outputs` digests
and artifacts), plus optional `mode`, `program_kv`, `integrations` and
`compact_history` defaults that a case inherits and may override.

The set (builder may adjust names; the coverage matters):

1. `cycling_program` - sports mode, cycling program: ~20 turns of Czech
   coaching over two weeks, Garmin digests in history, `program_kv` with the
   plan and a progress log, fake Garmin with recent activities and HRV.
2. `strength_program` - sports mode, strength program with Garmin workouts
   edited in earlier turns (`garmin_workout` digests).
3. `family_logistics` - ordinary chat, Czech, mixed topics over a week
   (school pickup, shopping, a trip, Todoist and Calendar use), long enough
   that `compact_history: true` produces a summary.
4. `project_research` - ordinary chat, a multi-day home-project discussion
   with earlier research turns, sources and an artifact.
5. `language_program` (optional) - language mode, if a case needs it.

Size target: each chat's rendered history roughly the production median for
its kind (program chats ~20-35k characters plus summary; ordinary ~15-25k).

**Compaction summaries are frozen in the fixture** (a `summary:` block next
to the messages, seeded as the conversation's stored summary): written once
- generated by the real summarizer when the chat is authored, then reviewed
and committed - so every run and repeat sees the same context and the long
cases cost no summarizer calls. The four existing `compact_history: true`
cases keep testing the live pipeline. The builder confirms the seeding path
works for sports mode, where `_program_conversation` today stores only user
turns.

### Cases on the shared chats

At least 25 cases use `history_from:`. Mix to roughly mirror production
(58% of turns use no tool): about half answer from context (recall the plan,
follow an earlier instruction, keep the tone and language), the rest use
integrations. Program-chat cases include the write checks:

- logging a finished workout must call `kv_store` (write) and, where the
  program says so, `garmin_workout`. Add an `expect.required_actions` check
  (deterministic, not judged) naming the mutating call and, optionally, a key
  or field pattern. `kv_store` writes go to the case's real temp database, so
  the check reads the tool calls' arguments (or the database), not a fake's
  `actions`; Todoist's fake already records `actions`. (`FakeGarmin` is
  read-only today - see Fakes below.)

Existing cases are not rewritten wholesale; a handful whose request reads
oddly without context move onto a shared chat.

### Fakes (decided Nov 18 2026: Garmin writes and Calendar both in scope)

- **`FakeGarmin` becomes stateful for workouts**: fixture workouts
  (`garmin.workouts:`) that `garmin_workout` can read, and every create /
  update / schedule recorded in `actions` with its payload - so
  `required_actions` can check that a sports turn saved the workout, and the
  judge sees what changed. Unknown calls keep failing loudly as today.
- **New `FakeCalendar`** behind the Google Calendar client seam (same rule:
  replace the HTTP/client seam, not the tool): fixture calendars and events
  with `{today}`-style dates, reads filtered by the requested range, and
  create / update / delete recorded in `actions`; `state: connected /
  not_connected` like Garmin. `family_logistics` and its cases use it.

### Canned web

- `evals/fakes.py` gains a `FakeWeb` behind the search seam
  (`src/services/search_provider.search_web` / `search_web_detailed`) and the
  page-fetch seam (`src/agent/tools/web.fetch_page_text`, plus whatever
  `fetch_url` and the freshness gate's lookup use - the builder confirms
  every live path, `browser` included).
- Case shape:

  ```yaml
  web:                      # default when absent: canned with no results
    results:                # returned for every search (first N per query)
      - {url: https://..., title: ..., snippet: ...}
    pages:                  # fetch returns this text (wrapped as usual)
      https://...: |
        ...realistic page text...
  ```

  `web: live` keeps today's ddgs path for that case.
- Pages are text, realistic in length for what the case tests (a product
  page ~3-6k characters with boilerplate, not a two-line answer).
- The ~14 web cases move to canned web, except about 5 kept live on purpose
  (one per behaviour: freshness/current events, price lookup, multi-source
  research, Czech query, deep-research end to end). Which ones is the
  builder's call, listed in the docs.
- With no `web:` block, a case that searches gets an empty result list
  (cheap, and visible in the judge's tool log) rather than going live.

### Repeats and model comparison

- **Build on `evals/ab.py`** (`make eval-ab`), which already runs cases
  several times per side, alternates sides and reports per case passes over
  runs, mean score, rounds and spend - today its two sides are two commits.
  Add a model side: the same code with the chat model swapped (e.g.
  `make eval-ab MODEL_A=gemini-4-hydrogen MODEL_B=<lite> ONLY=... RUNS=2`).
  `run.py` gains `--repeat N` for a single-side run (summary `k/N passed`).
- **`--model <id>` swaps the turn's chat model only** (what `DEFAULT_MODEL`
  picks for the conversation). Roles that merely default to `DEFAULT_MODEL`
  (`DELEGATE_MODEL`, `DEEP_RESEARCH_SUBAGENT_MODEL`, `AI_ASSIST_MODEL`,
  `PROGRAM_REVIEW_MODEL`) and the side models (gate, grounding, summarizer)
  stay as configured, and the judge stays Carbon. (Builder's-check answer:
  the question is "can this model answer the turn", not a whole-stack swap.)
- **Record the freshness gate's verdict per case** (thinking level and
  whether it looked up), in the results and the run log. The model
  comparison reports pass rates overall **and on the cases the gate rates
  easy (`low`)**, since the routing decision is about those turns only. The
  new cases must give that subset a usable sample (aim for 20+ `low` cases;
  count them after the first run and add cases if short).
- The run log line gains `repeat`, `model`, `web: {canned: n, live: m}` and
  per-case gate verdicts.

### Cost

- Report per-run cost as today, plus the share in live-web cases.
- First full run after the change sets the new baseline in
  `evals/history.jsonl` and `docs/testing/evals.md` (replacing "~$8 / 23
  minutes"), with the smoke subset's cost updated too.

## Instrumentation (rule A8)

- The run log carries canned vs live counts, repeat, cost and per-case
  `[pass, score]` (and `k/N` with repeats).
- `docs/testing/evals.md` records the new baseline (cost, minutes, pass rate
  on Hydrogen) and how to compare a model.
- TODO: "When Gemini 4 Helix ships: run the suite with `--model` and
  `--repeat 2` against Hydrogen; route easy turns only if it holds" - and a
  dated re-check of the suite's cost after a month of use.

## Constraints

- Public repo: synthetic content only; no hostnames.
- `.claude/rules/evals.md`: report cost for every run, commit
  `history.jsonl` with the change it measured, metered search keys stay
  blanked (canned web makes that moot for most cases, live cases still rely
  on it).
- Fakes replace the HTTP/client seam, not the tool, so tool formatting,
  untrusted-content wrapping and error envelopes stay real.
- Verification spend: authoring needs a few targeted `--only` runs; the
  baseline needs one full Hydrogen run (plus `--repeat 2` on the new cases).
  Estimate and report each before running.

## Left to the builder

- Exact chat names, contents and turn counts within the targets above.
- The precise `required_actions` syntax.
- Which ~5 web cases stay live.
- Whether `--compare` is a flag on `run.py` or a small script.
- How inheritance from a shared chat merges with case fields (case wins).
