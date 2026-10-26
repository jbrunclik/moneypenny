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
- **Server errors** - `ERROR` lines in the app's journal over the window,
  grouped by logger and message. The journal keeps only a few days, so the
  weekly cadence matters; anything recurring goes in the report.
- **Failed turns** - assistant messages with a `stop_reason` other than a
  normal finish, and turns with `tool_errors > 0` in `message_costs` (the
  admin page shows the rate). A rising rate or one tool dominating is a
  finding.

## 2. Agents and integrations

- Failed `agent_executions` per agent over the window (admin page "Agents");
  an agent failing on every run is broken, not flaky.
- Approvals pending for days (`agent_approval_requests`).
- Integration tokens that expired (Calendar, Garmin, Todoist "disconnected"
  results in the journal) - the person may not know.

## 3. Cost and speed

- Spend per day and per feature against the previous period (admin page
  "Spend"); any day past `SPEND_WARNING_DAILY_USD`; the share of spend in
  deleted chats.
- Model mix: a cheaper model doing well enough is a saving to propose.
- Response time: median and 95th percentile (admin page "Responses"); a
  slower p95 usually means a tool or the model provider, so name which.
- Web-search quotas (admin page "Web search"): a provider exhausted early in
  the period, or search falling back to the free provider.

## 4. Answer quality

- Grounding verdict mix: the `Grounding check` journal lines
  (`verdict_counts`) or the `grounding` column on messages - the share of
  answers with unsupported claims, against the last review.
- Deep research: runs, cost per run, runs stopped early (`research` column).
- When a change to the agent is pending or quality looks worse: `make eval`
  (costs money - report the cost; the full suite is about $1.40).

## 5. Code health (monthly)

Every baseline only shrinks. Report each count and its change:

| Baseline | Count with |
|---|---|
| ruff `# noqa` | `grep -rn "# noqa: [A-Z0-9, ]*$" src \| wc -l` |
| ESLint suppressions | the `count`s in `web/eslint-suppressions.json` |
| import cycles | entries in `web/tests/unit/import-cycles.baseline.json` |
| module-level state | the counts in `web/tests/unit/module-state.baseline.json` |
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
