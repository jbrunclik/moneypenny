# Regular Review

Moneypenny is used every day and changed mostly by agents. Nobody watches it
continuously, so problems surface only when someone looks: an error every
phone hits, an agent failing nightly, a cost creeping up, a baseline growing
again. The regular review is that look: a fixed checklist, run by an agent
(`/product-review`) and read by the maintainer.

**Cadence:** weekly (the quick pass, sections 1-4), monthly (all of it).
**Output:** a short dated report, most important finding first, each with a
proposed action: a fix to make now, a TODO entry, or "no action, here's why".
The review itself changes nothing in production and edits nothing but
`TODO.md`; fixes follow as their own work, after the maintainer agrees.

## Rules for the reviewer

- **Measure, don't guess.** Every finding cites a number from the data below
  (count, rate, trend) - code reading alone picked the wrong target before.
- **Production is read-only.** Logs and the database are read on the production
  host over SSH only with the maintainer's consent for that session; open the
  database read-only (`sqlite3 -readonly`, or `mode=ro` from Python).
- **Privacy.** Report names and numbers, never a conversation's content.
  Error messages and log excerpts can quote content: cut them to a line.
- **Compare with last time.** A number means little alone; the previous
  report (or the last 7 vs. the previous 30 days) gives the trend.
- **Public repo.** The report and any TODO entry say "the production host",
  never its name or address.

## 1. Errors users hit

- **Browser errors** - the admin page's "Browser errors" section, or the
  `client_errors` table: new fingerprints since last time, anything seen by
  more than one person, anything on the current build. Each needs a cause or
  a TODO entry. See [Browser errors](features/admin.md#browser-errors).
  Connection noise (`[messaging] Streaming failed: Fetch is aborted`,
  `Failed to send message: Network error`) is expected on phones; compare its
  `count` per `app_version` against the last review and look into it only if
  it grows faster than usage. Baseline (Nov 17 2026, 14 days, ~90 user messages
  a day): `Load failed` 60, `Fetch is aborted` 46 (~2 a day, all iPhone),
  `Failed to send message: Network error` 42 (~3 a day on the current build),
  `Stream read timed out` 26, `signal is aborted without reason` 19 - steady
  per-day rates spread over builds, no growth: phone backgrounding and networks. A timeout followed by "Message already received"
  at a deploy is the retry hitting the duplicate guard, which is harmless.
- **Layout checks** - the admin page's "Layout checks" section: a check the
  deployed build fails and the build before it didn't is an iOS layout
  regression. See [Layout checks](ui/mobile-and-pwa.md#layout-checks-field-telemetry).
- **Server errors** - `ERROR` lines in the app's journal over the window,
  grouped by logger and message. The journal keeps only a few days, so the
  weekly cadence matters; anything recurring goes in the report.
- **Failed turns** - assistant messages with a `stop_reason` other than a
  normal finish, and turns with `tool_errors > 0` in `message_costs` (the
  admin page shows the rate). A rising rate or one tool dominating is a
  finding.
- Model-call retries (from Nov 15 2026; [agent-graph.md](architecture/agent-graph.md#chat-node-and-transient-error-retries)):
  "Transient error, retrying" by error head (500/504/timeouts now retry) and "Model call
  failed after streaming text, not retried" - the latter are turns the user saw fail
  mid-reply; many of them argue for resuming the stream instead.

## 2. Agents and integrations

- Failed runs per job over the window (admin page "Agents"; `job_runs` with
  `status = 'failed'`, grouped by `item_id`); a job failing on every run is
  broken, not flaky.
- Runs waiting on their card (`proposals` with `origin = 'run'` and `state =
  'pending'`, by `job_id`), and run cards that expired unanswered (`state =
  'expired'`): an agent whose cards expire is asking for something nobody wants.
- Proposal cards (`proposals`, counts only; [proposals.md](features/proposals.md)): per
  `kind` the share approved / declined / expired / failed, `resolved_by` button vs typed,
  median seconds to an answer. Many expired = people answer in words the typed alias
  misses (look at nothing, only the counts - then widen the word list); many failed =
  apply refusals worth fixing at the source.
- Program self-tuning (from Nov 2026; [ui-composer.md](features/ui-composer.md#self-tuning)):
  "Setup suggestion resolved" per `source` (card / review) and `outcome` - a low
  accepted share means suggestions miss; "Setup change refused" by `reason` (many
  refusals for missing evidence mean the coach proposes on hunches); "Setup review"
  lines with `suggestions` 0 vs more and their `cost_usd`.
- Instructions self-tuning (from Nov 2026; [memory-and-context.md](features/memory-and-context.md#self-tuning)):
  "Instructions suggestion resolved" per `source` (card / review), `outcome` and
  `target` (instructions / memory / move) - a low accepted share means the
  suggestions miss; "Instructions change refused" by `reason` (evidence refusals
  = proposing on hunches); "Instructions review" with `suggestions` 0 vs more and
  `cost_usd` ("Instructions review unreadable" / "Setup review unreadable" should
  be rare; often = the structured output needs attention); from the DB (counts only) the `custom_instructions` length
  distribution against the 8000 limit, and how `custom_instructions` cards end.
- Run continuations and capped runs (from Nov 15 2026;
  [agents.md](features/agents.md)): "Run resumed after cards" per week and its
  `waited_s` (about a minute is expected); "Run continuation held" (logged about
  hourly, with `waited_s`) repeating for one item means a card or budget blocks it; "Run budget capped by the scheduler
  pass" `budget_s` against turns with `stopped_by = 'time'` from the scheduler -
  a run stopped on time where it used to be killed.
- Integration tokens that expired (Calendar, Garmin, Todoist "disconnected"
  results in the journal) - the person may not know.
- Cache use per model call (from Nov 15 2026; `message_costs.turn_timing` `calls`,
  one entry per call: `input`, `cached`, `output`, `ms`, `prefix`, `gap_s`,
  `same_user`): the cached share by `gap_s` bucket (<1 min, 1-5, 5-15, 15-60, >60
  min) - where Gemini's implicit cache stops paying; the share of first calls cached
  thanks to another user (`same_user` false) - what per-user tool sets would lose;
  first call vs later rounds. Decides per-user tools and keeping the prefix warm.
- Condensed memories (from Nov 15 2026; [memory-and-context.md](features/memory-and-context.md)):
  the share of chat turns with `turn_timing.memory_fetches` > 0 (they pay off while
  under ~1 in 4; an extra round costs ~$0.018), "Memory summaries written" per day,
  and memories still without a summary over 150 characters (should be ~0 after a
  pass).
- Memory end dates and undo (from Nov 17 2026; [memory-and-context.md](features/memory-and-context.md#end-dates-and-the-previous-text-nov-17-2026)):
  "Memory added via tool" / "Memory updated via tool" lines with a `valid_until`
  against all of them, "Memories expired" per night, and "Memory previous text
  restored" lines. Many restores mean writes lose details - read which writer
  (defrag, review, agent) changed those memories last.
- Flex memory review and defrag (from Nov 17 2026; [cost-tracking.md](features/cost-tracking.md#flex-tier-nov-17-2026)):
  `side_costs` `memory_review` and `memory_defrag` rows by `service_tier` ('flex' or NULL = fell back
  to standard) and "Flex call fell back" by `reason` - mostly fallbacks means Flex
  saves nothing; "Memory review pass" `model_ms` (a minute or two is expected).
- Side costs (from Nov 15 2026; [cost-tracking.md](features/cost-tracking.md)):
  `side_costs` per `feature` and `model` per week (sum of `cost_usd`, count) next to
  the chat turns' total; the nightly `memory_defrag` on Carbon from Dec 1 2026 (its
  price rises). `ai_assist` cost per call should sit well under its pre-Nov 16
  2026 level (low thinking since then); the two reviews run at high on purpose
  (cost-tracking.md, "Thinking level").
- Web reading (from Nov 15 2026; [agent-tools.md](features/agent-tools.md#tool-security)):
  the share of research page fetches that fail ("research completed"
  `fetch_failures` against `fetched_ok`; baseline 27%, 937 of 3,475 in the 30 days to
  Nov 15 2026), and "Page read via fallback" per week by `status` and `host` with the
  summed `cost_usd` (Exa extract spend; the fallback stops at 90% of Exa's quota).
  Hosts that keep failing there are candidates for their own reader.
- Rouvy (from Nov 15 2026; [rouvy.md](features/rouvy.md)): "Rouvy request via browser"
  count, `status` and median `elapsed_ms` (the in-page fetch Cloudflare lets
  through), against "Rouvy request met the Cloudflare challenge" and "Rouvy browser
  request failed" - any of those two means the user saw "Rouvy is blocking".

## 3. Cost and speed

- Spend per day and per feature against the previous period (admin page
  "Spend"); any day past `SPEND_WARNING_DAILY_USD`; the share of spend in
  deleted chats.
- Model mix: a cheaper model doing well enough is a saving to propose.
- Implicit cache hit rate (from Nov 2026, Gemini 4 has no explicit cache):
  `SUM(cached_input_tokens) / SUM(input_tokens)` in `message_costs` per model.
  Chats send the static prompt + tools as a stable prefix
  (`_static_prefix_profile` in `agent.py`), so a falling ratio means something
  volatile moved into that prefix.
- Response time: median and 95th percentile (admin page "Responses"); a
  slower p95 usually means a tool or the model provider, so name which.
- Where reply time goes (from Nov 15 2026; `message_costs.turn_timing`, JSON): median
  and p90 of `json_extract(turn_timing, '$.first_token_ms')` for streamed turns, and of
  `gate_ms`, `lookup_ms` (when `gate_lookup`), `model_ms` and `model_calls`, split by
  `thinking`; the gate's early start saves `gate_call_ms - gate_ms` (from Nov 16 2026:
  median and the share of turns where it saves over 0.3 s); `finish_reason` other than `STOP` (MAX_TOKENS, SAFETY) is a finding.
  `max_silence_ms` (from Nov 15 2026; streamed turns only): the longest stretch inside a
  model call with no chunk - it includes the model's thinking before its first thought
  summary, so judge outliers against `thinking`; silences far beyond the healthy turns'
  p99 are stalls (the watchdog item in TODO.md). The Reply speed items in TODO.md are
  judged against these.
- Title calls (from Nov 15 2026; "Conversation title generated" journal lines): median
  and p90 `elapsed_ms` (a new chat's `done` waits for it; Flash-Lite took ~0.6 s) and
  the share with `ok` false.
- Backup sizes: the nightly `Backup compressed` journal lines for chatbot.db
  (`plain_size_bytes`, `compressed_size_bytes`, `ratio`; 283 -> 160 MB, 0.57 on
  Nov 17 2026) and `Backup completed` for files.db (kept plain: it compressed
  to 0.97). The lines reach the journal only since Nov 17 2026 (the script did
  not set up logging). A ratio creeping towards 1, or sizes growing much faster
  than usage, is a finding; a `Backup compression failed` line means that
  night's copy stayed uncompressed. At most 3 copies per database, within 24 h.
- Web-search quotas (admin page "Web search"): a provider exhausted early in
  the period, or search falling back to the free provider.
- Turn budgets (from Nov 2026): the `Turn budget stop` journal lines and
  `message_costs.stopped_by` - the share of turns stopped and by which limit
  (cost, time, rounds, loop), and p90 turn cost and time. A limit that stops
  good turns, or one that never fires, is a value to retune in `src/config.py`.
  "Scheduled item over budget" lines (`item_id`, `kind`, `budget_usd`): any
  means a job or light item spent `UNATTENDED_DAILY_BUDGET_USD` (or its own
  budget) in a day - read what it ran before raising anything.
  "Scheduled item stopped after failures" lines by `error`: the same error on
  several items is a tool or integration to fix, not the items.
  "Turn final answer retried without tools" counts final rounds that only asked
  for tools (since Nov 11 2026 they get one retry on a model with no tools); a
  stopped reply that still ends in "I stopped before finishing" means the retry
  came back empty too - look at which job or chat it was.

- Thinking levels (from Nov 13 2026): the "Chat turn completed and saved"
  journal lines' `thinking` (low / medium / high; absent = the model's own, a
  failed gate or no gate) - the split per day, and cost and `duration_ms` per
  level by joining `message_id` to `message_costs`. A level that takes most
  turns, or `high` turns no slower or dearer than `medium` ones, is a prompt
  to retune the gate prompt.

## 4. Answer quality

- Grounding verdict mix: the `Grounding check` journal lines
  (`verdict_counts`) or the `grounding` column on messages - the share of
  answers with unsupported claims, against the last review.
- Deep research: runs, cost per run, runs stopped early (`research` column).
  Gap pass (from Nov 17 2026): "Deep research gap pass" lines against runs - how
  often it fires, its `reasons`, and `pages_after - pages_before` (near zero:
  the retries find nothing new, so drop it); "... skipped" lines mean the
  estimate leaves no room. "Deep research item reused" lines: retries that
  skipped the subagents an interrupted run had finished.
- Questions (step 5): "Question asked" lines per day against chat turns, and
  `question` cards by state and `resolved_by` - a card on many replies means
  it is being used as suggestion chips.
- Chat deletes (step 4): `chat_change` cards by state and `resolved_by`, and
  the "Chat change applied" lines' `failed` - do people approve them, and do
  stored calls fail (the item gone meanwhile)?
- Deep-research offers: the `deep_research` cards by state (started /
  declined / expired / superseded) and `resolved_by` (button vs typed) from
  `proposals`, and the "Deep research started" lines' edits - do people start
  what is offered, and does the next-message expiry close offers they wanted?
  The "Deep research reopened" lines by `reason`: many `retry` means runs
  are killed (deploys mid-run); many `regenerate` means reports disappoint.
- Artifact checklists: artifacts whose `state` has a non-empty `checklist`
  against all checklist artifacts, and the "Artifact read" lines with
  `checklist_items > 0` - do people tick items, and does the agent read them
  when asked what is left?
- Startup speed (Nov 16 2026): `client_boot_timings` - median and p90
  `ready_ms` by `standalone` x `viewport` (home-screen app vs tab, mobile vs
  desktop) over `hidden = 0` rows (a load backgrounded mid-start is flagged
  `hidden` and reports minutes), and which stage (`auth_ms` -> `data_ms` -> `route_ms`) grew.
- Agent files (Nov 16 2026): "office text extracted" lines - any `error`
  (a real document that could not be read is a bug), the `truncated` share
  and `ms`; "Failed to prepare media for Gemini" with an `audio/` type; and
  "conversation file: found" by `role` (assistant = the agent reopened its
  own output).
- Agent safety (Nov 16 2026): "kv write refused" lines (any from a scheduled
  agent or a coach is a bug - it should write only its own namespace),
  `work_bytes` on the "Code execution" lines against the 256 MB `/work` cap,
  and "Sandbox kill exec failed" (a fork bomb forced `docker kill`).
- Past-chat search: the "Conversation search via tool" lines - the share with
  `results` 0 (no keyword hit; 11 of 12 before the Nov 16 2026 fallback), the
  `mode` mix (`any` = the fallback found what strict matching missed) and the
  median `ms`.
- When a change to the agent is pending or quality looks worse: `make eval`
  (costs money - report the cost; the Nov 18 2026 suite is estimated at
  ~$5-6 on Hydrogen, so run the affected cases with `--only` first).
- Eval suite health (from `evals/history.jsonl`, Nov 18 2026): the cost of
  the last full run and its `live_web_usd` share (canned web should keep it
  small - a rising share means a case went live or a live case grew), the
  `web` canned/live counts (13 live on purpose), the `gate_low` count (20+ is
  what a Lite-model comparison needs), and `chat_*` cases that flip between
  runs (rerun with `--repeat 2` before calling one a regression).

## 5. Code health (monthly)

Every baseline only shrinks. Report each count and its change:

| Baseline | Count with |
|---|---|
| ruff `# noqa` | `grep -rn "# noqa: [A-Z0-9, ]*$" src \| wc -l` |
| ESLint suppressions | the `count`s in `web/eslint-suppressions.json` |
| import cycles | entries in `web/tests/unit/import-cycles.baseline.json` |
| module-level state (no baseline; review the marks) | `grep -rn "UI-local (F2)" web/src \| wc -l` - does each still hold? |
| import-linter | `ignore_imports` in `pyproject.toml` |
| test hygiene | the constants in `tests/unit/test_test_hygiene.py` |

Also: coverage against the floors (`make test-cov`, vitest thresholds), the
longest functions and most-fixed files (`git log --since=30.days` churn
against fix commits), and CI - run time and any reruns
(`gh run list --workflow Tests`).

## 6. Dependencies and parked work (monthly)

- `make audit`; open Dependabot PRs older than a week and why they're stuck.
- The **Parked** section of `TODO.md`: has any trigger fired (a price change,
  a new model, a library release)? A fired trigger moves the item up.
- `TODO.md` items with a "re-measure" or "review" date that has passed.
- [docs/conventions.md](conventions.md) rules marked "planned": still
  planned, or done and not marked?
- The [README](../README.md), the project's front page: does "What makes it
  different" and the feature list still match what shipped this month? A
  feature worth a line that is missing, one that was removed, a number that
  went stale (the test count). `tests/unit/test_readme.py` checks only the
  model names and the screenshots.

## Report template

```
# Review YYYY-MM-DD (weekly|monthly), window <from> - <to>

## Findings
1. <finding, with the number and the trend> - <proposed action>
...

## Numbers
<the counts above, this time vs. last time>

## No action
<things checked and fine, one line each>
```
