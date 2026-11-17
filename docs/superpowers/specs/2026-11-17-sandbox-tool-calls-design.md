# Sandbox scripts that call tools - design

Status: **built, off** (Nov 17 2026): `CODE_SANDBOX_TOOL_CALLS=false` until the
evals below run on an unthrottled search (the laptop's ddgs returned nothing that
day). Open questions answered with the proposed defaults: web and memory tools
first (calendar later), a one-line steer in the tool description, 120 s.
Pages read inside a script reach the turn's sources through the ToolMessage
`artifact` (set by `tool_node` from `_full_result.pages`; the model never sees it).
TODO: "Harness hardening from the Hermes Agent comparison" - sandbox scripts
that call tools. Reference: Hermes `tools/code_execution_rpc.py`.

## Why

The agent makes one tool call per round: 95.5% of rounds in the Sep 2026 audit
carried a single call, and every round re-sends the whole context. A question
with five independent lookups costs five rounds. The batching hint on tool
results and `web_search(queries=[...])` have not made `cz_batched_lookups`
pass: it failed 13 of 13 runs by the Nov 15 2026 audit and is marked a known
target.

A script can loop: `for city in cities: print(tools.web_search(...))` - five
lookups, one round, and only what the script prints returns to the model.

## What the model gets

Inside `execute_code`, a module that is always importable:

```python
from moneypenny import tools

results = tools.web_search("Prague weather tomorrow")          # dict, as the tool returns it
page = tools.fetch_url("https://...")                           # dict: title, text, ...
facts = tools.research(["query a", "query b"])                  # the composite tool
notes = tools.search_memory("allergies")                        # str
events = tools.calendar_events(start="2026-11-18", end="2026-11-20")  # read-only; name to match the calendar read tool
```

Same arguments and results as the tools the model already knows; a failed
call raises `ToolError` with the tool's message. The `execute_code`
docstring gets one short section with this list and the budget (the tool's
description is its only usage guide).

## Allow-list

Read-only tools whose results are data, not actions:
`web_search`, `fetch_url`, `research`, `search_memory`, read-only calendar
listing. Not: anything that writes (memory, Todoist, calendar writes,
kv_store, schedules), `delegate_task`, `generate_image`, `execute_code`
itself, deep research, the browser. Writes stay one visible tool call per
action, so cards and approvals keep working.

An unattended run gets only the allowed tools its job is granted (the
existing `check_tool_permission`); a chat turn gets the ones bound for it.

## Transport

**Proposed: a line protocol over the script's stdin and stdout.** The host
starts the script as an attached exec; the `moneypenny.tools` stub writes one
JSON request line with a per-run random prefix (`<<rpc:TOKEN>> {...}`) to
stdout and reads the reply line from stdin. The host thread reads stdout,
answers marked lines and keeps every other line as the script's output.

- Works with the network off, as now; no new mount.
- No polling: the host reacts to each line.
- The token is generated per run and handed to the stub through an environment
  variable of that exec only; a printed line without it is plain output, so a
  fetched page cannot forge a request by being printed.

Rejected: request/response files in `/work`, as Hermes does. `/work` is a
tmpfs inside the container, so the host would poll it through an exec per
check (tens of milliseconds each), and the files would linger in the
conversation's persistent `/work`.

## Limits

- `CODE_SANDBOX_TOOL_CALLS_MAX` (50) calls per run; the 51st raises
  `ToolError("budget spent")`.
- The run's timeout rises from `CODE_SANDBOX_TIMEOUT_SECONDS` (30 s) to
  `CODE_SANDBOX_TOOL_RUN_TIMEOUT_SECONDS` (120 s) only once the script makes
  its first call; each call keeps the tool's own timeout.
- Calls run one at a time in the host thread (the stub is synchronous); a
  later version can add a `tools.parallel([...])` if a script waits on many.
- The turn budgets see everything: each call is recorded as a tool call of
  the turn (`record_tool_call`), research and fetch spend joins the turn cost,
  and Stop kills the script as it does now.

## What returns to the model

Only what the script prints (the current output cap), plus files in
`/output/` as today. Printed text that came from pages is untrusted web data:
the `execute_code` result gets the same "web data, not instructions" framing
as `research` results whenever the run made a web call.

Pages read through `fetch_url` / `research` inside the script register as the
turn's sources (`turn_pages`), so the grounding check and the sources popup
see them; otherwise every fact from a scripted lookup would be flagged
unsourced.

## Observability

- A log line per call ("Sandbox tool call": tool, ms, ok) and one per run
  ("Sandbox tool run": calls, failed, ms).
- `turn_timing.sandbox_tool_calls` for the turn.
- Regular-review check: turns with sandbox tool calls, calls per run, and
  rounds per turn for multi-lookup questions before and after.

## Rollout and proof

- `CODE_SANDBOX_TOOL_CALLS` flag, off by default; on locally for evals first.
- Evals: `cz_batched_lookups` should pass (it is the target); a new case with
  five independent lookups asserts one `execute_code` round; the smoke subset
  must hold (no case should start scripting what one call answers).
- Then on in production, re-measured after two weeks: rounds per turn on
  multi-lookup questions, cost per such turn, and grounding `not_found` share.

## Open questions

1. Should the agent prefer scripts on its own, or only when the prompt names
   several independent lookups? Proposed: the docstring says "several
   independent lookups: one script"; measure before adding more steering.
2. Calendar: the read tool's shape differs per provider - include it in v1 or
   start with web and memory only? Proposed: web and memory first.
3. Is 120 s right for a scripted run? Research calls take 5-30 s each.
