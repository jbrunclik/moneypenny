# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.
Audit-tagged items (S/A/C/X/F/Q/T) come from the June 2026 read-only codebase audits (two rounds); tags kept for traceability.

## Features

- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] **Conversation sharing** - Public links for sharing conversations
- [ ] **Keyboard shortcuts** - Add keyboard shortcuts for common actions
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **Oura integration** - Allow planner to have access to health data
- [ ] **Parallel tool execution** - Verify/ensure multi-tool calls execute in parallel through `create_tool_node()`, not sequentially
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls (e.g., same web search query within a conversation)

## Autonomous Agents

- [ ] **Multi-step workflows** - Allow agents to run multi-step workflows
- [ ] **Bound agent-trigger depth (S5)** - Low. Cycles ARE blocked (`trigger_agent.py:55` checks the whole chain), but chain depth for distinct agents is unbounded (self-inflicted cost only). Add a `MAX_TRIGGER_DEPTH` guard for defense-in-depth.

## Planner Dashboard

- [ ] **Two-column layout** - Desktop two-column layout (events left, tasks right), task completion via Todoist API, open-in-Calendar links
- [ ] **Summary + timeline** - AI-generated daily summary strip, timeline view with hour markers, quick-add task from dashboard

## Security

- [ ] **Server-side OAuth state validation (S7)** - High / Medium effort. `routes/todoist.py:50-56` and `routes/calendar.py` generate the OAuth `state` and hand it to the client to validate ("we return it and let the client store/validate it") — server never checks it on callback, defeating CSRF protection. Store state server-side (kv_store with TTL, keyed to user), validate + invalidate on callback.
- [ ] **Remove `--no-sandbox` from agent browser (S8)** - High / Low effort. `src/agent/tools/browser.py:83` launches Chromium with OS sandboxing disabled while browsing untrusted pages. Drop the flag, or containerize the browser if the host env requires it.
- [ ] **Drop Todoist `data:delete` scope (S9)** - High / Low effort. `src/auth/todoist_auth.py:39` requests delete permission; combined with the LLM consuming fetched web content, a prompt-injected page could delete tasks. Reduce to read/write; gate deletes behind the existing `request_approval` tool if needed.
- [ ] **Encrypt OAuth/Garmin tokens at rest (S3)** - High (hosted) / Medium effort. Todoist, Google Calendar (access + refresh), and Garmin tokens are stored plaintext in SQLite (`src/db/models/user.py`). Encrypt with Fernet keyed from env/secrets; encrypt-on-write / decrypt-on-read; migrate existing rows. Severity depends on deployment model.
- [ ] **Security headers + CORS policy (S10)** - Medium / Low effort. `src/app.py` sets no `X-Frame-Options`, `X-Content-Type-Options`, CSP, or HSTS, and no explicit CORS policy. Add an `@app.after_request` hook.
- [ ] **Magic-byte file upload validation (S11)** - Medium / Low effort. `src/api/schemas.py:67-74` validates the declared MIME type only; content is never sniffed. Verify magic bytes (`python-magic`) match the declared type, reject mismatches.
- [ ] **Verify code-sandbox network isolation (S4)** - Medium. `execute_code` relies on llm-sandbox's default `--network none` (`code_execution.py:425`) but never sets it explicitly and has no test. Pass network-disabled explicitly if the API allows; add a regression test that `socket.socket().connect(...)` fails inside the sandbox.
- [ ] **Rate limiting: proxy-aware client IP** - Limiter uses `request.remote_addr` which collapses to the load-balancer IP behind a reverse proxy. Add `ProxyFix` middleware and switch limiter key to honor `X-Forwarded-For`. Files: `app.py`, `rate_limiting.py`
- [ ] **Logout: clear all sensitive state** - `store.logout()` only clears token/user/currentConversation, leaving messages, pagination, activeRequests in memory. Add `resetStore()` that wipes all maps/sets on `auth:logout`. Files: `store.ts`, `init.ts`
- [ ] **Harden `blob_store.delete_by_prefixes` SQL (S6)** - Low. `db/blob_store.py:~189` builds the WHERE via f-string (params still bound, not injectable today, but fragile). Use a loop of parameterized deletes. Also consider raising `SLOW_QUERY_THRESHOLD_MS` / log level in prod to avoid schema leakage in logs.

## AI-Agent Best Practices

- [ ] **Structured tool errors (A1)** - Medium. `web.py`/`browser.py`/`code_execution.py` return errors as `json.dumps({"error": ...})` strings; the self-correction node string-matches `"error"`/`"Exception"` (`graph.py`) to detect failures — brittle. Standardize a typed result envelope (`ok`/`error`, `retriable`) and branch on it.
- [ ] **Bound long-term memory (A2)** - Medium. `validate_memory_operations` (`src/api/utils.py`) checks presence but not size; memory is injected every request → unbounded context growth + an injection-persistence vector. Cap per-entry and total memory size; add dedup/age-out; reject oversized writes.
- [ ] **Agent-behavior evals + observability (A3)** - Medium/Large. No regression evals for agent behavior; no metrics for tool success rate, token spend, latency, retries. Add a small eval harness (golden tasks) + structured per-turn metrics. This is what would catch regressions like the checkpointer/compaction bugs early. (The C1 `planning_classifier` log is a first step.)

## Performance / Cost

- [ ] **Right-size the planning classifier (follow-up to C1)** - After observing the new `planning_classifier` telemetry (fire-rate + latency), decide whether to gate tighter, fold the decision into the main call, or disable by default. `graph.py::should_plan`, `AGENT_PLANNING_*`.
- [ ] **Compaction summarization is on the request path** - Medium. `build_compacted_history` calls the summarizer synchronously when the threshold trips, so a slow/hung Gemini call adds latency to that user turn (correctness is safe — it falls back to full history). Bound it with a timeout and/or move summarization off the request path (background/precompute). `src/agent/conversation_compaction.py`, `src/agent/compaction.py`.
- [ ] **Context-cache hit-rate telemetry (C2)** - Low/Medium. `context_cache.py` has no logging of cache hit/create/rebuild rates; silent cache misses or tool-list drift could quietly cost input tokens. Add per-profile cache instrumentation; assert cached tool set matches the active set.
- [ ] **N+1 queries in agent listing (Q1)** - Medium. `routes/agents.py:139-145` runs `has_pending_approval` + `get_agent_unread_count` + `get_last_execution_status` per agent in a loop. Batch into a single query keyed by agent_id.

## Reliability

- [ ] **Harden streaming save on crash/timeout (X1)** - Medium, needs verification first. In `src/api/helpers/chat_streaming.py`: (a) a placeholder `update_message_content()` returning `None` is treated as "user deleted it" — a real UPDATE error is indistinguishable and can orphan the expected message id; (b) if `stream_chat_events` raises before the "final" event, `final_results["ready"]` stays False and the save is skipped → generated content lost on crash/timeout. **Observed in prod (Jun 2026): gunicorn worker timeout on a long stream raised `SystemExit`, the `finally` deleted the placeholder, and the streamed content was lost.** The CHAT_TIMEOUT deadline path now persists partial content on timeout (see Done), but the broader case (arbitrary crash/`BaseException`, not just the deadline) is still open. Distinguish deleted-vs-failed; persist whatever content was produced in the `finally` path.
- [ ] **Remaining lazy-init races under gthread (low)** - Low. Non-critical singletons still race on first concurrent access (idempotent → at most redundant work / a stray daemon thread, no data corruption): browser `_worker` shutdown + `_browser_available` flag (`browser.py`), `_docker_available` (`code_execution.py`), and the `_start_cleanup_thread()` guards in `browser.py` / `tool_results.py`. Add double-checked locking when convenient.
- [ ] **Align prod Python version with `requires-python`** - `pyproject.toml` declares `requires-python>=3.14` but prod runs 3.13. Either bump prod to 3.14 or relax the constraint to match reality.
- [ ] **SyncManager.start() error handling** - Unhandled rejection silently disables background sync if `start()` throws. Await inside try/catch, log failures, allow retry. Files: `init.ts`, `SyncManager.ts`

## Code Quality

- [ ] **Deduplicate sports/language program modules (Q2)** - Medium / High effort. `routes/sports.py` vs `routes/language.py` (and their model mixins) are near-identical CRUD differing only in namespace — CLAUDE.md already documents them as "the same architecture". Extract a shared program-routes factory before a third program feature lands.
- [ ] **File-size convention violations (Q3)** - Low / High effort. 9+ files are 2-3× over the repo's 500-line max: `prompts.py` (1469), `schemas.py` (1415), `chat_streaming.py` (1357), `db/models/agent.py` (1266), `routes/agents.py` (1119); frontend `api/client.ts` (1402), `SettingsPopup.ts` (1343), `utils/thumbnails.ts` (1000), `state/store.ts` (872). Split `chat_streaming.py` and `client.ts` first — highest churn.
- [ ] **Refactor `save_message_to_db` (X2)** - Low. ~214 lines (exceeds the repo's 100-line guideline), mixes save + title-gen + metadata + cost, and swallows title-gen errors. Extract sub-steps. `chat_streaming.py`. (Overlaps with the `chat_streaming.py` split in Q3.)
- [ ] **Tidy exception swallowing (X3)** - Low. Silent `except Exception: pass` sites: `connection_pool.py:~188` (rollback — can hide non-sqlite errors), `browser.py` (4× in the worker thread — can leak Playwright contexts), `chat_streaming.py:137-144`, `planner_data.py:25-29`; plus a couple of redundant context-clears in the stream path. Log at least at DEBUG.
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. Consider consolidating into a single scroll manager that dispatches to subsystems.

## Frontend

- [ ] **Sanitize rendered LLM output — XSS (F1)** - High / Low effort. LLM/API-sourced strings reach `innerHTML`: `components/messages/streaming.ts:274` (rendered markdown + cursor span), `utils/markdown.ts:167` (highlight.js output assigned raw), plus API-sourced renders in `core/agents.ts`, `core/language.ts:348`, `core/sports.ts:346`, `core/kv-store.ts:250`, `core/planner.ts:290`. Since the model re-renders untrusted web content, run all rendered markdown through DOMPurify — closes the whole class.
- [ ] **VoiceInput listener leak (F2)** - Medium. `components/VoiceInput.ts:413-425` adds mouse/touch listeners with no cleanup on re-mount. Export a cleanup fn or use the existing `addEventListenerWithCleanup` from `dom.ts`.
- [ ] **Sidebar full re-render (F3)** - Medium. `components/Sidebar.ts:610-674` rebuilds the whole list via `innerHTML` on every update — flicker + lost scroll/focus. Move to incremental DOM updates.

## Tests & Tooling

- [ ] **Replace `waitForTimeout` in E2E suite (T1)** - High. 60+ `page.waitForTimeout()` calls across `conversation`, `sync`, `stream-recovery`, `search`, `agents`, `pagination` specs — directly contradicts the repo's zero-tolerance flaky-test policy. Replace with `expect(...).toBeVisible()` / `waitForFunction`.
- [ ] **Unit tests for agent tools (T2)** - High / Medium effort. 13 tool modules in `src/agent/tools/` have zero unit tests (`code_execution`, `todoist`, `google_calendar`, `web`, `trigger_agent`, `garmin`, `image_generation`, …) — the highest-risk code paths in the app. Also missing integration tests for `routes/{files,kv_store,memory,system,todoist}.py`.
- [ ] **Tighten lint/coverage gates (T3)** - Low effort, one-liners. Add coverage `fail_under` to pyproject; enable ruff `S` (bandit) rules; bump `npm audit --audit-level` from `critical` to `high` in `.github/workflows/audit.yml`; replace the blanket mypy `ignore_missing_imports = true` with per-module overrides.

## Audit Notes

Verified non-issues (recorded so future audits don't re-flag them):
- `.env` is NOT committed — not tracked, not in git history, gitignored.
- Zustand persist `partialize` (`store.ts:863`) only persists token/streamingEnabled/draft — no Map-serialization/data-loss problem.

Shipped from audit round 1 (see git history): SSRF fix on `fetch_url` (S1), untrusted-content guardrails (S2), planning-classifier telemetry (C1).

## Done

- [x] **Conversation compaction for regular chats** - DONE (Jun 2026). Non-destructive `build_compacted_history()` (running summary in `kv_store` + recent window) in `src/agent/conversation_compaction.py`, wired into batch + stream paths. Also removed the unused LangGraph checkpointer subsystem (it was duplicating history into every request) and stabilized the history prefix for Gemini implicit caching. See follow-up: *compaction summarization is on the request path*.
- [x] **Pin `langchain-google-genai` to fix prod context cache** - DONE (Jun 2026). The loose `>=2.0` floor (no lockfile) had let prod drift to an old 2.x returning proto/gapic `Tool` objects from `convert_to_genai_function_declarations`, breaking `CreateCachedContentConfig` validation and silently disabling context caching. Pinned floor to `>=4.1.2`; prod redeployed on 4.2.4, cache errors gone.
- [x] **Streaming requests killed by gunicorn worker timeout** - DONE (Jun 2026). Sync workers suspend the master heartbeat for the whole request, so long SSE `chat/stream` responses exceeding `--timeout` were killed mid-stream (`WORKER TIMEOUT` → `SystemExit`, reproduced locally). Switched to `--worker-class gthread --threads ${GUNICORN_THREADS:-8}` in `systemd/ai-chatbot.service`; gthread heartbeats from its main loop while requests run in a thread pool, so long streams complete (verified). Added `GUNICORN_THREADS` to `config.py` + `.env.example`. Thread-safety prerequisite for the migration also fixed: double-checked locking on the `_blob_store` and thumbnail `_executor` lazy singletons (`blob_store.py`, `background_thumbnails.py`) with concurrency stress tests.
- [x] **App-level request deadline now load-bearing under gthread** - DONE (Jun 2026). gthread does not reap a quietly-working/streaming request thread, so the gunicorn timeout no longer bounds chat duration. Wired the previously-dead `CHAT_TIMEOUT` (default 300→600s) into the `chat/stream` path as a defense-in-depth deadline: the producer (`stream_events`) breaks the agent loop + `gen.close()` when the deadline passes (stops the agent), and the consumer (`_process_event_queue`) enforces a backstop deadline (`CHAT_TIMEOUT + SSE_KEEPALIVE_INTERVAL`) that frees the worker thread even if the producer is wedged. On timeout the partial streamed content is saved (with a `…(response timed out)` marker) via the existing save path and the client gets a `{"type":"timeout"}` SSE event. See `docs/superpowers/plans/2026-06-05-chat-stream-deadline.md`. Note: the broader X1 (persist partial content on arbitrary crash/`BaseException`, not just the deadline) is still open.
