# AI Chatbot - TODO

This file tracks planned features, improvements, and technical debt.

## Features
- [ ] **Thinking mode toggle** - Allow enabling Gemini thinking mode with configurable level (minimal/low/medium/high) using long-press UI similar to voice input language selector
- [ ] **Conversation sharing** - Public links for sharing conversations
- [ ] **Keyboard shortcuts** - Add keyboard shortcuts for common actions
- [ ] **Voice conversation mode** - Full voice-based conversation with speech-to-text input and text-to-speech output
- [ ] **Oura integration** - Allow planner to have access to health data
- [x] **Conversation compaction for regular chats** - DONE (Jun 2026). Non-destructive `build_compacted_history()` (running summary in `kv_store` + recent window) in `src/agent/conversation_compaction.py`, wired into batch + stream paths. Also removed the unused LangGraph checkpointer subsystem (it was duplicating history into every request) and stabilized the history prefix for Gemini implicit caching. See follow-up: *compaction summarization is on the request path*.
- [ ] **Parallel tool execution** - Verify/ensure multi-tool calls execute in parallel through `create_tool_node()`, not sequentially
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls (e.g., same web search query within a conversation)

## Autonomous Agents
- [ ] **Multi-step workflows** - Allow agents to run multi-step workflows

## Planner Dashboard
- [ ] **Two-column layout** - Desktop two-column layout (events left, tasks right), task completion via Todoist API, open-in-Calendar links
- [ ] **Summary + timeline** - AI-generated daily summary strip, timeline view with hour markers, quick-add task from dashboard

## Security
- [ ] **Rate limiting: proxy-aware client IP** - Limiter uses `request.remote_addr` which collapses to the load-balancer IP behind a reverse proxy. Add `ProxyFix` middleware and switch limiter key to honor `X-Forwarded-For`. Files: `app.py`, `rate_limiting.py`
- [ ] **Logout: clear all sensitive state** - `store.logout()` only clears token/user/currentConversation, leaving messages, pagination, activeRequests in memory. Add `resetStore()` that wipes all maps/sets on `auth:logout`. Files: `store.ts`, `init.ts`

## Reliability
- [ ] **Redeploy prod on pinned `langchain-google-genai>=4.1.2`** - The loose `>=2.0` floor (no lockfile) let prod drift to an old 2.x that returns proto/gapic `Tool` objects from `convert_to_genai_function_declarations`, while local resolved to 4.1.2 (returns `list[google.genai.types.Tool]`). Mismatched return shape/types broke `CreateCachedContentConfig` validation in prod (first a `list_type` error, then `TYPE_UNSPECIFIED`/infinite-`items` proto errors) — non-fatal (cache falls back to uncached path) but disables context caching + spams warnings. Floor now pinned to `4.1.2` in `pyproject.toml` + `requirements.txt`; **action remaining: redeploy prod to pull the new version.** Also note: `requires-python>=3.14` but prod runs 3.13 — align the Python version too, or relax the constraint to match.
- [ ] **SyncManager.start() error handling** - Unhandled rejection silently disables background sync if `start()` throws. Await inside try/catch, log failures, allow retry. Files: `init.ts`, `SyncManager.ts`

## Code Quality
- [ ] **Four independent scroll listeners on same container** - `#messages` has listeners from: (1) `thumbnails.ts` - image load scroll, (2) `Messages.ts` - streaming auto-scroll, (3) `ScrollToBottom.ts` - button visibility, (4) `Messages.ts` - pagination. Each has independent debouncing. **Future improvement**: Consider consolidating into a single scroll manager that dispatches to subsystems.

## Codebase Audit Follow-ups (June 2026)

From a read-only audit of the agent codebase (built with older models). Severity / effort noted; confidence is "confirmed by reading the code" unless stated. Items already shipped this round: SSRF fix on `fetch_url` (S1), untrusted-content guardrails (S2), planning-classifier telemetry (C1) — see git history.

### Security
- [ ] **Encrypt OAuth/Garmin tokens at rest (S3)** - High (hosted) / Medium effort. Todoist, Google Calendar (access + refresh), and Garmin tokens are stored plaintext in SQLite (`src/db/models/user.py`). Encrypt with Fernet keyed from env/secrets; encrypt-on-write / decrypt-on-read; migrate existing rows. Severity depends on deployment model.
- [ ] **Verify code-sandbox network isolation (S4)** - Medium. `execute_code` relies on llm-sandbox's default `--network none` (`code_execution.py:425`) but never sets it explicitly and has no test. Pass network-disabled explicitly if the API allows; add a regression test that `socket.socket().connect(...)` fails inside the sandbox.
- [ ] **Bound agent-trigger depth (S5)** - Low. Cycles ARE blocked (`trigger_agent.py:55` checks the whole chain), but chain depth for distinct agents is unbounded (self-inflicted cost only). Add a `MAX_TRIGGER_DEPTH` guard for defense-in-depth.
- [ ] **Harden `blob_store.delete_by_prefixes` SQL (S6)** - Low. `db/blob_store.py:~189` builds the WHERE via f-string (params still bound, not injectable today, but fragile). Use a loop of parameterized deletes. Also consider raising `SLOW_QUERY_THRESHOLD_MS` / log level in prod to avoid schema leakage in logs.

### AI-Agent Best Practices
- [ ] **Structured tool errors (A1)** - Medium. `web.py`/`browser.py`/`code_execution.py` return errors as `json.dumps({"error": ...})` strings; the self-correction node string-matches `"error"`/`"Exception"` (`graph.py`) to detect failures — brittle. Standardize a typed result envelope (`ok`/`error`, `retriable`) and branch on it.
- [ ] **Bound long-term memory (A2)** - Medium. `validate_memory_operations` (`src/api/utils.py`) checks presence but not size; memory is injected every request → unbounded context growth + an injection-persistence vector. Cap per-entry and total memory size; add dedup/age-out; reject oversized writes.
- [ ] **Agent-behavior evals + observability (A3)** - Medium/Large. No regression evals for agent behavior; no metrics for tool success rate, token spend, latency, retries. Add a small eval harness (golden tasks) + structured per-turn metrics. This is what would catch regressions like the checkpointer/compaction bugs early. (The C1 `planning_classifier` log is a first step.)

### Performance / Cost
- [ ] **Right-size the planning classifier (follow-up to C1)** - After observing the new `planning_classifier` telemetry (fire-rate + latency), decide whether to gate tighter, fold the decision into the main call, or disable by default. `graph.py::should_plan`, `AGENT_PLANNING_*`.
- [ ] **Compaction summarization is on the request path** - Medium. `build_compacted_history` calls the summarizer synchronously when the threshold trips, so a slow/hung Gemini call adds latency to that user turn (correctness is safe — it falls back to full history). Bound it with a timeout and/or move summarization off the request path (background/precompute). `src/agent/conversation_compaction.py`, `src/agent/compaction.py`.
- [ ] **Context-cache hit-rate telemetry (C2)** - Low/Medium. `context_cache.py` has no logging of cache hit/create/rebuild rates; silent cache misses or tool-list drift could quietly cost input tokens. Add per-profile cache instrumentation; assert cached tool set matches the active set.

### Reliability
- [ ] **Harden streaming save on crash/timeout (X1)** - Medium, needs verification first. In `src/api/helpers/chat_streaming.py`: (a) a placeholder `update_message_content()` returning `None` is treated as "user deleted it" — a real UPDATE error is indistinguishable and can orphan the expected message id; (b) if `stream_chat_events` raises before the "final" event, `final_results["ready"]` stays False and the save is skipped → generated content lost on crash/timeout. Distinguish deleted-vs-failed; persist whatever content was produced in the `finally`/timeout path.
- [ ] **Refactor `save_message_to_db` (X2)** - Low. ~214 lines (exceeds the repo's 100-line guideline), mixes save + title-gen + metadata + cost, and swallows title-gen errors. Extract sub-steps. `chat_streaming.py`.
- [ ] **Tidy minor exception swallowing (X3)** - Low. `connection_pool.py:~188` `except Exception: pass` on rollback can hide non-sqlite errors; a couple of redundant context-clears in the stream path.
