# Agent Tools

Which tools the agent can use, how availability and permissions are decided, and the tool-specific subsystems (search provider chain, K/V store, browser). Applies to interactive chat and autonomous agents; the agent loop that calls them is in [Agent Graph](../architecture/agent-graph.md).

## Tools for Autonomous Agents

Interactive chat binds every available tool (`get_tools_for_request()`); autonomous agents
get `get_tools_for_agent()`, filtered by the agent's `tool_permissions`. Two lists matter:

- **Always bound** for every agent: `web_search`, `fetch_url`, `research`, `retrieve_file`,
  `create_file`, `request_approval`, `kv_store`.
- **`ALWAYS_SAFE_TOOLS`** ([permissions.py](../../src/agent/permissions.py)) skip the
  call-time permission check: every always-bound tool, plus the read-only places tools
  `search_places`, `get_route`, `list_places`.

Every always-bound tool must also be in `ALWAYS_SAFE_TOOLS` — a bound tool the gate refuses
just wastes a model round on an error (`test_every_bound_tool_passes_the_permission_gate`).
`trigger_agent` is a granted capability (it hands text to another agent's run): bound for
unrestricted agents (`tool_permissions=null`) or when listed explicitly.

| Tool | Description | Availability |
|------|-------------|--------------|
| `web_search` | Web search queries | Always available |
| `research` | Composite search + fetch top pages in one round | Always available |
| `fetch_url` | Fetch content from URLs | Always available |
| `browser` | Full browser automation (JS rendering, clicks, forms, screenshots) | Requires `BROWSER_ENABLED` + Playwright |
| `retrieve_file` | Retrieve files from conversations | Always available |
| `create_file` | Attach an LLM-authored text file (ZWO/CSV/ICS/GPX/…) for download — no code execution | Always available |
| `request_approval` | Request user approval | Always available |
| `trigger_agent` | Trigger another agent | Unrestricted agents, or when listed in `tool_permissions` |
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

All Playwright operations run on a dedicated daemon thread (`_BrowserWorker`) because Playwright's sync API is greenlet-based and cannot be used from arbitrary threads (including Flask/Gunicorn worker threads). The tool function dispatches commands to the worker via a `queue.Queue` and blocks until the result is returned.

1. On first use per process, `_get_worker()` lazily creates the `_BrowserWorker`, which starts a daemon thread, initialises `sync_playwright`, and launches a headless Chromium instance
2. Subsequent tool calls dispatch `_WorkerCommand` objects to the worker's queue; the calling thread blocks on `result_event` until the worker signals completion
3. Each conversation gets its own `BrowserContext` (isolated cookies, JS state, history)
4. A separate `browser-session-cleanup` daemon thread runs every 60 s, evicting sessions idle beyond `BROWSER_SESSION_TTL_SECONDS`
5. If `BROWSER_MAX_CONCURRENT_SESSIONS` is reached, the oldest session is evicted before creating a new one
6. All URLs are validated against an SSRF blocklist before any navigation
7. `atexit` registers `_shutdown_worker()` to gracefully close the browser on process exit

### Actions

| Action | Required params | Description |
|--------|----------------|-------------|
| `navigate` | `url` | Go to a URL; returns page title and URL |
| `click` | `selector` | Click an element by CSS selector |
| `type` | `selector`, `text` | Fill a form field |
| `screenshot` | — | Take a JPEG screenshot (returns multimodal image content) |
| `extract` | — | Extract all visible text from the current page |
| `scroll` | — | Scroll down the page; optional `selector` to scroll to an element |
| `back` | — | Go back in browser history |
| `close` | — | Close the session for the current conversation and free resources |

Any action accepts `screenshot=True` to append a screenshot to the result.

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

### Setup

```bash
make browser-setup  # installs playwright Python package + Chromium browser
```

If Playwright or Chromium is not installed, the tool returns a graceful error message with the install hint — it does not crash the server.

### Key files

- [src/agent/tools/browser.py](../../src/agent/tools/browser.py) - Full implementation: `_BrowserWorker` daemon thread, `BrowserSession` dataclass, queue-based dispatch, SSRF validation, screenshot modes, action handlers
- [src/config.py](../../src/config.py) - `BROWSER_ENABLED`, `BROWSER_SESSION_TTL_SECONDS`, `BROWSER_MAX_CONCURRENT_SESSIONS`, `BROWSER_PAGE_TIMEOUT_MS`
- [src/agent/tools/__init__.py](../../src/agent/tools/__init__.py) - `is_browser_available()` registration
- [src/agent/tool_display.py](../../src/agent/tool_display.py) - UI metadata (icon, label)

### Testing

- Unit tests: [tests/unit/test_browser.py](../../tests/unit/test_browser.py)

## Key Files

- [tools/__init__.py](../../src/agent/tools/__init__.py) - `get_available_tools()`, `get_tools_for_request()`, `get_tools_for_agent()`
- [permissions.py](../../src/agent/permissions.py) - `ALWAYS_SAFE_TOOLS`, `check_tool_permission()`
- [tool_display.py](../../src/agent/tool_display.py) - `TOOL_METADATA`, `_CONDITIONAL_TOOLS`
- [search_provider.py](../../src/utils/search_provider.py) - quota-aware search chain and breakers
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - `TurnContext.apply()` / `clear()`

## See Also

- [Autonomous Agents](agents.md) - scheduling, approvals, Command Center
- [Agent Graph](../architecture/agent-graph.md) - tool node, self-correction, tool rounds
- [Integrations](integrations.md) - integration tools and not-connected results
- [File Handling](file-handling.md) - `generate_image`, `execute_code`, `retrieve_file`
