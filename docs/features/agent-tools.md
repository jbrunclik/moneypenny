# Agent Tools

Which tools the agent can use, how availability and permissions are decided, and the tool-specific subsystems (search provider chain, K/V store, browser). Applies to interactive chat and autonomous agents; the agent loop that calls them is in [Agent Graph](../architecture/agent-graph.md).

## Tools for Autonomous Agents

Interactive chat binds every available tool (`get_tools_for_request()`); autonomous agents
get `get_tools_for_agent()`, filtered by the agent's `tool_permissions`. Two lists matter:

- **Always bound** for every agent: `web_search`, `fetch_url`, `research`, `retrieve_file`,
  `create_file`, `load_skill`, `request_approval`, `kv_store`.
- **`ALWAYS_SAFE_TOOLS`** ([permissions.py](../../src/agent/permissions.py)) skip the
  call-time permission check: every always-bound tool, plus the read-only places tools
  `search_places`, `get_route`, `list_places`.

Every always-bound tool must also be in `ALWAYS_SAFE_TOOLS` — a bound tool the gate refuses
just wastes a model round on an error (`test_every_bound_tool_passes_the_permission_gate`).
`trigger_agent` is a granted capability (it hands text to another agent's run): bound for
unrestricted agents (`tool_permissions=null`) or when listed explicitly.

| Tool | Description | Availability |
|------|-------------|--------------|
| `web_search` | Web search queries; a repeat single-query call in a turn runs as `research` | Always available |
| `research` | Composite search + fetch top pages in one round | Always available |
| `fetch_url` | Fetch content from URLs | Always available |
| `browser` | Full browser automation (JS rendering, clicks, forms, screenshots) | Requires `BROWSER_ENABLED` + Playwright |
| `retrieve_file` | Retrieve files from conversations | Always available |
| `create_file` | Attach an LLM-authored text file (ZWO/CSV/ICS/GPX/…) for download — no code execution | Always available |
| `load_skill` | Return a built-in skill's instructions ([Skills](#skills)) | Always available |
| `request_approval` | Request user approval | Always available |
| `trigger_agent` | Trigger another agent | Unrestricted agents, or when granted ("Other agents" in the agent editor) |
| `kv_store` | Per-user key-value storage | Always available |
| `generate_image` | AI image generation | Requires `GEMINI_API_KEY` |
| `execute_code` | Code execution in sandbox | Requires `CODE_SANDBOX_ENABLED` |
| `todoist` | Todoist task management | Requires user integration |
| `google_calendar` | Calendar events | Requires user integration |
| `garmin_connect` | Read-only Garmin health/activity data | Requires user integration |
| `garmin_workout` | Read/write Garmin saved workouts (edit sets/reps/weight/rest, swap/add/remove exercises) | Requires user integration |
| `rouvy_workout` | CRUD over the user's Rouvy cycling workouts (upload ZWO, list, get, delete; update = delete+create) | Requires browser + user Rouvy connect |
| `whatsapp` | WhatsApp notifications | Requires app config + user phone |
| `manage_memory` | Write to the user's long-term memory | **Must be granted** |
| `search_memory` | Search stored memories (keyword + semantic) | Requires grant |
| `search_conversations` | Search the user's past conversations | Requires grant |
| `read_conversation` | Read one past conversation | Requires grant |
| `delegate_task` | Context-isolated research subagent (spends tokens) | **Must be granted** |

`web_search` and `research` route through a **quota-aware provider chain** ([search_provider.py](../../src/utils/search_provider.py)): Brave → Tavily → Exa → Linkup → DuckDuckGo (unmetered fallback), skipping providers with no API key or an exhausted quota (`SEARCH_QUOTA_*_MONTHLY`). Quotas reset per **billing period** (`SEARCH_BILLING_DAY_*`, default calendar month — which all four metered providers use as of Sep 2026). Usage counters persist in `kv_store` under a `__system__` sentinel user, one key per provider+period, incremented atomically on successful (billed) calls only.

A provider that reports **terminal exhaustion** - out of credits for the billing period, not merely busy - is benched immediately and not probed again until the period rolls over. The providers signal this differently and the adapters map each one: Brave `402` (`Usage limit exceeded`), Tavily `432` (plan limit), Exa `402` (out of credits); their `429`s all mean ordinary rate limiting and stay transient. Linkup is the exception - it returns `429` for both and exposes nothing to tell them apart, so it falls back to the threshold below. Conflating the two previously cost a daily half-open probe against an already-dry provider for the rest of the month, each probe charging a real search a failed round-trip before falling through.

Short of that, a provider that fails `SEARCH_BREAKER_THRESHOLD` times in a row trips a per-provider **circuit breaker** and is skipped until a half-open probe window (`SEARCH_BREAKER_PROBE_SECONDS`) elapses. The failure count is an atomic `kv_increment` on an integer key (`breaker:<provider>:<period>`), with the last-failure timestamp in a separate `breaker-last:...` key — split out so the count stays a true atomic increment rather than a read-modify-write JSON blob, since production runs multiple gunicorn workers that can record failures concurrently.

**Search escalation.** The first `web_search` in a turn and every batched `queries=[...]` call behave normally. From the 2nd single-query call, `web_search` runs the query as `research` (reading the top `WEB_SEARCH_ESCALATE_MAX_SOURCES` pages, default 3) and returns research-shaped JSON with an `_escalated` note, so the pages count as read for source chips. It never refuses. Rationale and numbers: [Tool Round Economics](../architecture/agent-graph.md#tool-round-economics).

`is_degraded()` is the single definition of "serving from the fallback": true only when *every configured* metered provider is unavailable (quota spent, breaker tripped, or keyless). A single provider erroring and falling through to the next one is not degradation. The operator (first `ALLOWED_EMAILS` entry) gets a push notification only on genuine degradation, deduped to once per day — a transient provider blip no longer trips the alert or burns that day's dedupe slot. While degraded, `web_search` results carry a `_degraded` directive pointing the model at `research` instead of repeating a thin-snippet search, and `research`'s default source count rises to `Config.RESEARCH_DEGRADED_MAX_SOURCES` (fetched page content compensates for ddgs's weaker ranking and short snippets); an explicit `max_sources` from the caller still wins. Backfill/inspect usage with `python scripts/seed_search_usage.py [provider count]`.

**Permission settings:**
- `tool_permissions=null` (default): All available tools enabled
- `tool_permissions=[]`: Only the always-bound tools
- `tool_permissions=["todoist", ...]`: The specified tools (when available) + the always-bound tools

`manage_memory` is deliberately NOT "always available": an unattended run that reads the web
could otherwise persist attacker-controlled text into the user's long-term memory, which is
then injected into every later conversation. Agents that genuinely need it must list it (or
run unrestricted), and the tool re-checks the grant at call time via
`check_autonomous_permission`. See
[memory-and-context.md](memory-and-context.md#bounds-and-safety).

## Three layers decide tool availability

Whether a tool actually works for an agent depends on **three** independent layers that must
all agree — the first two are the obvious ones, the third is easy to miss:

1. **Binding** — `get_tools_for_request(..., is_agent=True)` / `get_tools_for_agent()` decide
   which tools the LLM is even offered.
2. **Enforcement** — the graph's tool node calls `check_tool_permission()`
   ([`src/agent/permissions.py`](../../src/agent/permissions.py)); tools not in the agent's
   explicit `tool_permissions` are blocked unless listed in `ALWAYS_SAFE_TOOLS`.
3. **Context propagation** — streaming turns run the graph in a **separate producer
   thread** (`stream_events()` in
   [`src/api/helpers/stream_producer.py`](../../src/api/helpers/stream_producer.py)). Python
   contextvars do **not** cross thread boundaries, so the producer calls
   `TurnContext.apply()` ([`chat_turn.py`](../../src/api/helpers/chat_turn.py)) to re-set
   every per-turn contextvar (request id, message files, conversation, location, planner
   dashboard, agent context, sports/language program). The batch path calls the same
   `apply()` in the request thread, and both call `clear()` when the turn ends. Any tool that
   reads a contextvar depends on this.

> **Pitfall — every new contextvar goes into `TurnContext.apply()` and `clear()`.** A
> contextvar a tool reads that is set anywhere else is silently `None` in the streaming
> producer thread (or leaks into the next request on a reused thread), and any guard or
> permission check keyed on it misbehaves without an error. Cover it with a test that runs
> `stream_events` in a fresh thread and captures the contextvar inside the tool. (Before the
> Sep 2026 turn-setup refactor the producer re-set a hand-picked subset, which is how this
> class of bug happened.)

## Tool Security

- **SSRF protection**: `fetch_url` and `browser` validate every URL through
  [`url_safety.validate_public_url`](../../src/agent/tools/url_safety.py) —
  rejecting non-http(s) schemes, localhost, and literal *or DNS-resolved*
  private/reserved/cloud-metadata addresses. `fetch_url` disables auto-redirect
  and re-validates each hop, plus re-checks the host at connect time via an
  SSRF-safe transport. Residual DNS-rebinding risk is narrowed but not
  eliminated; network-level egress filtering is the complete control.
- **Untrusted content**: text from `fetch_url`/`browser` is wrapped in
  `[UNTRUSTED WEB CONTENT ...]` markers and `web_search` carries a `_warning`
  field; the system prompt instructs the model to treat all such content
  (including page titles/URLs) as data, never instructions, and to be cautious
  about high-impact actions driven solely by fetched content. This is a
  mitigation, not a guarantee.
- **Grounding directive**: `GROUNDING_DIRECTIVE` in
  [web.py](../../src/agent/tools/web.py) ("only state specifics that appear in
  these results; say you could not verify the rest") rides on the results
  themselves: a `_grounding` field on `web_search` (single and batched) and
  `research`, and a trusted `[...]` note appended after the untrusted-content
  markers of `fetch_url` HTML/text results. The always-on "Evidence Honesty"
  section of [core.py](../../src/agent/prompt_texts/core.py) adds the same rule
  (unread prices, stock, hours, dates are unverified). Measured effect: none
  (`skill_product_where_to_buy` stayed at 1/5; the model still mixed dealers
  and prices from its own knowledge into verified results). The
  [grounding check](#grounding-check) below is what fixed it. Tests:
  [test_grounding_directive.py](../../tests/unit/test_grounding_directive.py).

## Grounding Check

Because prompt rules did not work, a check runs after the answer, outside the
model ([grounding_check.py](../../src/agent/grounding_check.py), design:
[spec](../superpowers/specs/2026-10-02-grounding-check-design.md)).

- **Trigger**: `apply_grounding()` is called by `ChatAgent` at the end of
  `chat_batch` and on the `final` event of `stream_chat_events`
  ([agent.py](../../src/agent/agent.py)), so evals see what users see. It runs
  only when the turn has a web tool result (`WEB_TOOL_NAMES`: `research`,
  `web_search`, `fetch_url`, `browser`), the answer is non-empty, and the turn
  was not stopped. Every other turn skips it at zero cost.
- **Verifier**: one structured call (`GroundingVerdict`, temperature 0) to
  `GROUNDING_CHECK_MODEL`, prompt in
  [grounding.py](../../src/agent/prompt_texts/grounding.py). Inputs: the
  turn's web results, newest first, up to the source cap, plus known facts
  (today's date and the user's message) that always count as supported. It
  returns unsupported claims about specific businesses, events and services
  (kinds `business | event | price | hours_or_date | contact | other`) and false
  claims (sentences saying it verified something the sources do not support).
  It must never flag the answer's own plan or schedule (suggested times,
  durations) or well-known places (towns, hills, regions) - both were the bulk
  of the noise in the first prod week (Oct 2026). Only items found literally in
  the answer, at most `GROUNDING_CHECK_MAX_ITEM_CHARS` long (names and prices,
  not descriptions), are kept; if 3+ kept items are bare times or time ranges
  they are the answer's own timeline and are dropped (Lite flags them despite
  the prompt).
- **Annotations**: [grounding_annotations.py](../../src/agent/grounding_annotations.py) (claim validation), [source_pages.py](../../src/agent/source_pages.py) (numbered pages)
  deterministically inserts `_(neověřeno)_` (Czech) or `_(unverified)_` (any
  other language) after each item at every occurrence, after closing emphasis,
  inside table cells, and at the end of each false-claim sentence. Link
  targets, bare URLs and autolinks, inline code and fenced code blocks are
  never touched, and an item already followed by a marker is not marked again.
  The marked text arrives in `done.content` about 1-3 s after streaming ends;
  the client re-renders the bubble when `done.content` differs from the
  streamed text (`doneContentToRender` in `web/src/core/stream-done.ts`), and
  it is saved as the message content. The web renderer turns the marker into
  a small amber badge (`.grounding-unverified`, tooltip "Nenalezeno ve
  zdrojích...") via a `marked` `em` override in
  [markdown.ts](../../web/src/utils/markdown.ts); copy turns the badge back
  into `(neověřeno)`.
- **Scope**: skipped inside `delegate_task` subagents (the parent's answer is
  the one users see). This turn's non-web tool results (calendar, Garmin,
  memory...) count as known facts, so stating them is never flagged.
- **Cost**: about $0.004 per web turn. Verifier usage goes into
  `usage_info["grounding_usage"]` and is priced at the verifier's rates by
  `calculate_grounding_cost()` ([utils.py](../../src/api/utils.py)) into
  `message_costs`.
- **Fail-open**: on timeout, API or schema error it logs "Grounding check
  failed" and returns the answer unchanged.
- **Telemetry**: one "Grounding check" log line per check with
  `flagged_count`, `false_claim_count`, `kinds`, `source_chars`,
  `duration_ms`, `parsed`.

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `GROUNDING_CHECK_ENABLED` | `true` | Kill switch |
| `GROUNDING_CHECK_MODEL` | `gemini-3.5-flash-lite` | Verifier model (priced only, not user-selectable) |
| `GROUNDING_CHECK_MAX_SOURCE_CHARS` | `60000` | Source text cap, most recent kept |
| `GROUNDING_CHECK_MAX_ITEMS` | `8` | Max flagged items |
| `GROUNDING_CHECK_MAX_FALSE_CLAIMS` | `3` | Max flagged false-claim sentences |
| `GROUNDING_CHECK_MAX_ITEM_CHARS` | `40` | Longer items are dropped as descriptions or mis-filed sentences (only false claims may be sentences) |
| `GROUNDING_CHECK_TIMEOUT_SECONDS` | `10` | Floored at `GEMINI_MIN_REQUEST_DEADLINE_SECONDS` (10) |

Pitfalls learned:
- An end-of-answer note listing the items was measured not to work: the eval
  judge still read the main text and tables as fact, and the answer's own
  "Verified: ..." sentences contradicted the note. Hence in-place markers and
  the false-claims list.
- The Gemini API rejects deadlines under 10 s, so a shorter timeout made every
  check fail open (silently, apart from the warning).
- Without known facts the verifier flagged today's date (which the model gets
  from the system prompt) under a fully sourced answer.

Tests: [test_grounding_check.py](../../tests/unit/test_grounding_check.py),
[test_grounding_annotations.py](../../tests/unit/test_grounding_annotations.py),
[test_grounding_hooks.py](../../tests/unit/test_grounding_hooks.py),
[test_grounding_cost.py](../../tests/unit/test_grounding_cost.py).

## Skills

Recipe-level instructions the agent loads on demand instead of carrying them in
every prompt. Each skill is `src/agent/skills/<name>/SKILL.md` with frontmatter
`name` (lowercase-hyphenated, equal to the directory) and `description`; the
loader in [skills/__init__.py](../../src/agent/skills/__init__.py) parses
and validates every file at import (limits `SKILL_MAX_DESCRIPTION_CHARS` and
`SKILL_MAX_BODY_CHARS` in [constants.py](../../src/constants.py)), so a broken
skill fails CI, not a chat turn. Design:
[skills spec](../superpowers/specs/2026-09-30-skills-design.md).

- **Index**: `skills_index_prompt()` (one line per description) is appended
  right after `TOOLS_SYSTEM_PROMPT_BASE` in both prompt paths
  (`get_static_prompt_for_profile()` and `get_system_prompt()` in
  [prompts.py](../../src/agent/prompts.py)). It is byte-stable, so it is part
  of the cached prefix.
- **Body**: reaches the model only as the result of `load_skill(name)`
  ([tools/skills.py](../../src/agent/tools/skills.py)), i.e. after the cached
  prefix, so loading never breaks the context cache. The tool is always bound
  (chat and autonomous agents) and in `ALWAYS_SAFE_TOOLS`; an unknown name
  returns the list of valid ones.
- **Built-in skills**: `office-documents`, `pdf-documents`, `browser-tactics`,
  `weekly-planning` (recipes moved out of the always-on prompt; one-line
  `load_skill(...)` pointers remain there and in the `execute_code`/`browser`
  docstrings), plus `trip-itinerary` and `product-research` (new, from a
  conversation sweep).

**Adding a skill:**

1. Create `src/agent/skills/<name>/SKILL.md`; write the description as a
   directive ("Load BEFORE ...") naming the tasks that should trigger it.
2. Add the name to `EXPECTED` in [test_skills.py](../../tests/unit/test_skills.py).
3. Add should-trigger eval cases (`required_tools: [load_skill]`) and
   should-not cases (`forbidden_tools: [load_skill]`) under `evals/cases/skill_*`.
4. Meet the gate: at least 90% load rate on should-trigger runs, no loads on
   should-not runs, and the full eval suite holds. Evidence at launch: the
   moved recipes loaded 25/25, should-not 0/20, suite 48/50 twice vs a 49/47
   baseline.

## Adding a New Tool

When adding a new tool for autonomous agents, update these locations:

**Backend (required):**

1. **`src/agent/tools/<tool_name>.py`** - Tool implementation with `@tool` decorator
2. **`src/agent/tools/__init__.py`** - Register in `get_tools_for_request()`, add `is_<tool>_available()` function
3. **`src/agent/tool_display.py`** - Add to `TOOL_METADATA` (icon, present/past labels) **and** a branch in `extract_tool_detail()` so the pill says *what* the tool did, not just that it ran. A tool with no metadata renders as a raw `Used <function_name>` with a generic brain icon; `validate_tool_names()` logs a warning at import for any bindable tool that is missing an entry, and `tests/unit/test_tool_display.py` fails the build. Tools bound only in specific contexts (planner, programs, autonomous agents) must also be listed in `_CONDITIONAL_TOOLS`.
4. **`src/api/routes/agent_assist.py`** - Add to `_PROMPT_TOOL_DESCRIPTIONS` dict for prompt enhancer

**Frontend (required):**

5. **`web/src/components/AgentEditor.ts`** - Add to `BASE_TOOLS` array for permissions UI
6. **`web/src/utils/icons.ts`** - Add icon if needed (referenced by `TOOL_METADATA`)

**Configuration (if needed):**

7. **`src/config.py`** - Add configuration variables
8. **`.env.example`** - Document new config variables

**For integration tools requiring user connection:**

9. **`src/api/routes/agent_assist.py`** - Add `_is_<tool>_connected_for_user(user)` function that checks both app config AND user connection status

**Documentation:**

10. **`docs/features/agent-tools.md`** - Update the tools table above
11. **`docs/features/<integration>.md`** - A page for an external-service tool, linked from the table in `docs/features/integrations.md`; use `not_connected_result()` for users without a working connection

**Tests:**

12. **`tests/unit/test_<tool>.py`** - Unit tests for the tool
13. **`web/tests/visual/agents.visual.ts`** - Update visual snapshots if UI changed

> **Pitfall — type every tool parameter concretely.** A parameter typed `Any`
> (or otherwise producing a schema with no `type`/`anyOf`) can break when
> `langchain_google_genai` converts the tool to a Gemini function declaration —
> and since tools are bound on *every* request, that breaks all chat, not just
> the feature. Prefer scalar types; pass variable/nested arguments as a JSON
> **string** parameter and decode it inside the tool. `.invoke()`-based unit
> tests do **not** exercise this schema conversion, so add a guard that asserts
> each parameter has a concrete type (see
> `tests/unit/test_garmin_workout_tool.py::TestToolSchema`).

## K/V Store

Autonomous agents have access to a per-user key-value store for persisting data between executions. This allows agents to remember state, cache results, and share data across runs without requiring a full database.

### How it works

1. Agents call the `kv_store` tool with an `action` and a `key` (and optionally a `value`)
2. Keys are automatically namespaced so each context has its own isolated storage:
   - Autonomous agents: `agent:<agent_id>`
   - Sports conversations: namespace `sports`, keys `<program_id>:<suffix>` (goals, preferences, routine, progress, last_session); language conversations likewise under `language`
3. The namespace is injected by the tool at runtime - agents/programs never need to specify it explicitly
4. Data is stored in the `kv_store` SQLite table and scoped per user

### Usage (from an agent's perspective)

```
# Store a value
kv_store(action="set", key="last_checked_at", value="2026-02-26T09:00:00Z")

# Retrieve a value
kv_store(action="get", key="last_checked_at")

# Deep-merge into a stored JSON value server-side (replaces get-then-set)
kv_store(action="merge", key="state", value='{"last_price": 101.2}')

# List all keys in the agent's namespace
kv_store(action="list")

# Delete a key
kv_store(action="delete", key="last_checked_at")
```

### Limits

| Limit | Value |
|-------|-------|
| Max key length | 256 characters |
| Max value size | 64 KB |
| Max keys per namespace | 1,000 |

### Management

Users can view and manage all K/V entries via the **Storage** page at `#/storage` in the frontend. The REST API is available at `/api/kv` (6 endpoints in `kv_store.py`).

### Key files

- [src/agent/tools/agent_kv.py](../../src/agent/tools/agent_kv.py) - Tool implementation
- [src/api/routes/kv_store.py](../../src/api/routes/kv_store.py) - REST API endpoints (6 routes)

## Browser Tool

The `browser` tool gives the LangGraph agent full browser automation capabilities using Playwright (headless Chromium). Unlike `fetch_url` which does simple HTTP requests, the browser renders JavaScript, maintains session state, and can interact with dynamic web pages.

### How it works

All Playwright operations run on a dedicated daemon thread (`BrowserWorker` in [browser_worker.py](../../src/agent/tools/browser_worker.py)) because Playwright's sync API is greenlet-based and cannot be used from arbitrary threads (including Flask/Gunicorn worker threads). The tool function dispatches commands to the worker via a `queue.Queue` and blocks until the result is returned.

1. On first use per process, `get_worker()` lazily creates the `BrowserWorker`, which starts a daemon thread, initialises `sync_playwright`, and launches a headless Chromium instance
2. Subsequent tool calls dispatch `_WorkerCommand` objects to the worker's queue; the calling thread blocks on `result_event` until the worker signals completion
3. Each conversation gets its own `BrowserContext` (isolated cookies, JS state, history)
4. A separate `browser-session-cleanup` daemon thread runs every 60 s, evicting sessions idle beyond `BROWSER_SESSION_TTL_SECONDS`
5. If `BROWSER_MAX_CONCURRENT_SESSIONS` is reached, the oldest session is evicted before creating a new one
6. All URLs are validated against an SSRF blocklist before any navigation (every step of a batch, before the batch starts)
7. `atexit` registers `_shutdown_worker()` to gracefully close the browser on process exit

### Actions

| Action | Required params | Description |
|--------|----------------|-------------|
| `navigate` | `url` | Go to a URL; returns page title, URL and `elements` |
| `click` | `selector` | Click an element by CSS selector |
| `type` | `selector`, `text` | Fill a form field |
| `screenshot` | — | Take a JPEG screenshot (returns multimodal image content) |
| `extract` | — | Extract all visible text from the current page |
| `scroll` | — | Scroll down the page; optional `selector` to scroll to an element |
| `back` | — | Go back in browser history |
| `close` | — | Close the session for the current conversation and free resources |

Any action accepts `screenshot=True` to append a screenshot to the result.

### Batches

The tool takes **either** `action` (one action, the params above) **or**
`actions: list[BrowserStep]` (a batch); passing both or neither is an error.
A batch runs a known sequence (navigate -> type -> click) in one tool call
instead of one [tool round](../architecture/agent-graph.md#tool-round-economics)
per step. The logic lives in [browser_steps.py](../../src/agent/tools/browser_steps.py):

- Batchable actions: `navigate`, `click`, `type`, `scroll`, `back`, `extract`.
  `screenshot` and `close` are not - use `screenshot=True` on the call instead
  (one screenshot after the last step), and call `close` on its own.
- `validate_batch()` checks the whole batch before anything runs: at most
  `BROWSER_MAX_BATCH_ACTIONS` steps, each passing the same `validate_action()`
  (required params, SSRF check) as a single call.
- `run_batch()` runs the steps in order on the worker (`worker_kwargs()` builds
  each command) and stops at the first failing step. The result carries
  `completed`, per-step `steps`, and on failure `failed_step`, `error` and a
  `hint` not to re-run the steps that already ran; plus the last page's
  `title`, `url` and `elements`.
- A wall-clock budget (`BROWSER_BATCH_TIMEOUT_SECONDS`) is checked before each
  step; a step already running is bounded by its own page timeout.
- The tool trace shows a batch as `navigate: <url> → type → click`
  (`extract_tool_detail()` in [tool_display.py](../../src/agent/tool_display.py)).
- The autonomous-agent permission check sees `action="batch"` with the list of
  step URLs.

### Page state

`navigate`, `click`, `type`, `scroll` and `back` return `elements`: up to
`BROWSER_PAGE_STATE_MAX_ELEMENTS` visible interactive elements (links, buttons,
inputs, selects, textareas, ARIA buttons/links, contenteditable), each as
`{role, label, selector}` with a selector Playwright accepts (`#id`,
`[name=...]`, `[aria-label=...]` or `:has-text(...)`). A selector that would match several elements (radio groups sharing a `name`, repeated "Learn more" buttons) becomes `:nth-match(<selector>, N)`, so every emitted selector resolves to exactly one element under Playwright's strict mode. It is collected by
`PAGE_STATE_JS` via `BrowserWorker._page_state()`, which is best effort (a
failure yields `[]`, never a failed action). Input values are never read, since
they may hold passwords. `frame_page_text()` wraps the element list, like
extracted `content`, as untrusted web content. It lets the model act on a new
page without a screenshot or `extract` round. Batch results carry `elements`
only for the final page, not per step.

### Screenshot sharing

Screenshots have two independent modes controlled by separate parameters:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `screenshot=True` | `False` | Takes a JPEG screenshot **for the LLM only** (multimodal content injected into the model context). The user does not see it. Useful for navigation — finding selectors, understanding page layout. |
| `share_screenshot=True` | `False` | In addition to the LLM view, saves the screenshot as a **file attachment** visible to the user in the chat, via `store_tool_result()`. Use only when the visual result is relevant to the user (e.g., final page, answer to a visual question). |

Both parameters can be combined: `screenshot=True, share_screenshot=True` gives the LLM the image and also shares it with the user.

When screenshots are included in the response, the tool returns a `list[dict]` (multimodal content); otherwise it returns a JSON string. This matches the return-type pattern used by `generate_image` and `fetch_url`.

### SSRF Protection

All URLs are validated before navigation. Blocked ranges include loopback (`127.0.0.0/8`), all RFC-1918 private ranges, link-local addresses (`169.254.0.0/16`), and their IPv6 equivalents. `localhost` and `localhost.localdomain` are also blocked.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_ENABLED` | `true` | Enable or disable the browser tool globally |
| `BROWSER_NO_SANDBOX` | `false` | Opt out of Chromium's OS sandbox (only for environments that cannot run it, e.g. root in a container without user namespaces) |
| `BROWSER_SESSION_TTL_SECONDS` | `300` | Seconds of inactivity before a session is closed |
| `BROWSER_MAX_CONCURRENT_SESSIONS` | `3` | Maximum simultaneous browser sessions |
| `BROWSER_PAGE_TIMEOUT_MS` | `30000` | Default Playwright timeout per action (ms) |
| `BROWSER_MAX_BATCH_ACTIONS` | `10` | Maximum steps in one `actions` batch |
| `BROWSER_BATCH_TIMEOUT_SECONDS` | `60` | Wall-clock budget for a batch, checked before each step |
| `BROWSER_PAGE_STATE_MAX_ELEMENTS` | `40` | Maximum `elements` returned after a page-changing action |

### Setup

```bash
make browser-setup  # installs playwright Python package + Chromium browser
```

If Playwright or Chromium is not installed, the tool returns a graceful error message with the install hint — it does not crash the server.

### Key files

- [src/agent/tools/browser.py](../../src/agent/tools/browser.py) - The `browser` tool: availability probe, argument validation dispatch, single vs batch paths, screenshot modes, error results
- [src/agent/tools/browser_worker.py](../../src/agent/tools/browser_worker.py) - `BrowserWorker` daemon thread, `BrowserSession` dataclass, queue-based dispatch, action handlers, session cleanup
- [src/agent/tools/browser_steps.py](../../src/agent/tools/browser_steps.py) - `BrowserStep` model, `validate_action()`, `validate_batch()`, `worker_kwargs()`, `run_batch()`, `frame_page_text()`, `PAGE_STATE_JS`
- [src/config.py](../../src/config.py) - `BROWSER_*` settings (table above)
- [src/agent/tools/__init__.py](../../src/agent/tools/__init__.py) - `is_browser_available()` registration
- [src/agent/tool_display.py](../../src/agent/tool_display.py) - UI metadata (icon, label) and the trace detail for single actions and batches

### Testing

- Unit tests: [tests/unit/test_browser.py](../../tests/unit/test_browser.py), [tests/unit/test_browser_batch.py](../../tests/unit/test_browser_batch.py) (batch validation and execution against a mocked worker)
- Integration: [tests/integration/test_browser_page_state.py](../../tests/integration/test_browser_page_state.py) runs `PAGE_STATE_JS` in real Chromium (skips without it): visible elements only, no input values, the element cap, and every emitted selector resolving to exactly one element

## Key Files

- [tools/__init__.py](../../src/agent/tools/__init__.py) - `get_available_tools()`, `get_tools_for_request()`, `get_tools_for_agent()`
- [permissions.py](../../src/agent/permissions.py) - `ALWAYS_SAFE_TOOLS`, `check_tool_permission()`
- [skills/](../../src/agent/skills/) - `SKILL.md` files, loader, `skills_index_prompt()`
- [tool_display.py](../../src/agent/tool_display.py) - `TOOL_METADATA`, `_CONDITIONAL_TOOLS`
- [search_provider.py](../../src/utils/search_provider.py) - quota-aware search chain and breakers
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - `TurnContext.apply()` / `clear()`

## See Also

- [Autonomous Agents](agents.md) - scheduling, approvals, Command Center
- [Agent Graph](../architecture/agent-graph.md) - tool node, self-correction, tool rounds
- [Integrations](integrations.md) - integration tools and not-connected results
- [File Handling](file-handling.md) - `generate_image`, `execute_code`, `retrieve_file`
