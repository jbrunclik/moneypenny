# Moneypenny - TODO

Actionable work only, grouped by area; **Next up** is the working order. Completed work lives in git history, design detail in [docs/superpowers/specs/](docs/superpowers/specs/). Items that wait on an external trigger live under **Parked**, each with the trigger that reopens it.

## Next up

1. **Skills: on-demand instruction packs** (Sep 30 2026 Desktop-parity review) - a `load_skill` tool that pulls a named instruction pack (e.g. "writing ZWO workouts", "report formatting") into the turn only when needed, instead of growing the always-on prompt in `prompt_texts/`. Design pending.
2. **Deep research mode** (Sep 30 2026 Desktop-parity review) - a long-running mode that plans, fans out subagents in parallel (`delegate_task` / `research` exist), and writes a report with inline citations tied to claims (today's source chips are per turn). Resumable streams + push notifications already cover "tell me when it's done". Design pending.
3. **Verify the tool-round work moved real traffic** (overdue since ~Sep 20 2026) - the Sep 2026 efficiency changes (result-attached nudges, composite Garmin/kv_store actions, 6d608bc) are a behavioral bet with only a baseline measured (14 days to Sep 6: 95.5% of rounds had one tool call, `web_search` solo in 99% of its rounds, 83 round-cap hits). Re-measure from production logs (`LLM requested tool calls` / `Tool round completed`, turns = rounds ≤90 s apart), and browser rounds per turn now that batching shipped. If single-call rounds haven't moved, go structural (e.g. reject a second single-query `web_search` in a turn with an error naming the batched call); if they have, record the numbers in docs/architecture/agent-graph.md "Tool Round Economics" and consider lowering `AGENT_MAX_TOOL_ROUNDS`. Eval rounds drifted up ~19% Sep 6-15 (single samples) - re-check with repeated `make eval` runs.
4. **Model 503 → fail fast + cross-tier fallback** (Aug 27 2026 incident) - during a capacity spike `gemini-3.7-flash` returned `503 UNAVAILABLE` on every call while the Pro tier stayed up. `with_retry` retried the dead model `AGENT_MAX_RETRIES` times, each on top of google-genai's own backoff, so turns sat on "Thinking" for minutes (`CHAT_TIMEOUT=600s` backstop), and nothing fell back to the working tier. Fix: on a model-unavailable 503 fail fast and retry the turn on the other `MODELS` tier (uncached - the context cache is keyed per (profile, model)); seam: `graph.py:chat_node` / `retry.py`. Operator mitigation meanwhile: switch the dropdown to Advanced, or flip `DEFAULT_MODEL` + restart.

## Agent & harness

- [ ] **MCP client (connectors)** (Sep 30 2026 Desktop-parity review) - every integration is a hand-written tool module; an MCP client in the tool layer would plug in Gmail/Drive/GitHub/Notion-style servers without new code per service. MCP tools must pass all three availability layers (binding, `check_tool_permission`, contextvar forwarding - docs/features/agent-tools.md) and default to *not* safe for autonomous agents (remote results are untrusted, same reasoning as `manage_memory`). Pairs with deferred tool loading - MCP servers expose dozens of tools.
- [ ] **Deferred tool loading** (Sep 30 2026 Desktop-parity review) - bind only core tools plus a `find_tools` / `load_tools` meta-tool; integration tools load on demand, for a smaller base prompt, better context-cache hits, and room for MCP. **Must ship with evals**: a `make eval` baseline before the change (tool-selection accuracy, rounds per turn, cost), new cases where the needed tool is not loaded yet (the model must discover it, not refuse or hallucinate a call), and a comparison after. Merge only if selection accuracy holds and the extra discovery round costs less than the prompt tokens it saves (docs/architecture/agent-graph.md "Tool Round Economics").
- [ ] **Artifacts** (Sep 30 2026 Desktop-parity review) - a `create_artifact` tool emitting HTML/SVG rendered live in a sandboxed iframe (`sandbox="allow-scripts"`, no same-origin, strict CSP) in a side panel; versions stored per message, reopenable from the conversation. `create_file` covers downloads; this covers "show me a working thing" (calculators, charts, mini-apps).
- [ ] **Knowledge base, then Projects** - (1) persistent user documents searchable across conversations: SQLite FTS5 over extracted text + the embeddings table (Aug 2026; its `kind` column extends to `document`) for keyword + semantic search. (2) Projects (Sep 30 2026 Desktop-parity review) on top: conversations grouped under a project with its own instructions and pinned documents, retrieval scoped per project.
- [ ] **Server-side Stop follow-ups** (Sep 30 2026 final review, shipped 9cbe63f; see docs/features/chat-and-streaming.md "Stop Streaming"):
  - Skip the "Your answer is ready" web push for a stopped reply (grace-fallback path: `_notify_response_ready` in `stream_producer.py` / `stream_finalize.py`)
  - Files from a tool that finishes after Stop get attached to the stopped message (`_collect_generated_files` pops all of the request's results) - decide: filter, or document as intended
  - `execute_code`'s pre-run `raise_if_cancelled()` sits inside the broad `try` and becomes an error JSON (harmless - the next checkpoint ends the turn - but misleading); re-raise `TurnCancelled`
  - The `/proc` kill misses children of user code whose argv lacks `/sandbox/`; `exec_run` has no explicit timeout and runs on the poller thread
  - `stop_reason` is written in a second UPDATE after the content commit - pass it through `_persist_assistant_message` so both land atomically
  - "Stopped before answering." goes into model history and first-turn title generation; consider display-only
  - A second Stop click gives no feedback for up to `STOP_DONE_GRACE_MS` - show "Stopping…" or make it a hard abort
  - The `stopping` event is not journaled, so a reload-resumed reader can still hit the grace fallback during a long tool
- [ ] **Browser a11y-tree snapshots** (Aug 2026 agent review; batching + element summaries shipped Sep 30 2026) - replace the CSS-selector summary (`PAGE_STATE_JS` in `browser_steps.py`) with accessibility-tree snapshots carrying stable element refs the model clicks by ref.
- [ ] **MSG_CONTEXT migration** (Aug 2026 agent review) - the multi-chunk echo-stripping state machine in `stream_events.py` exists because metadata is inlined into message content as HTML comments. If Gemini's API grows first-class per-message metadata, migrate and delete the stripping.

## Chat & UI

- [ ] **Branching on message edit** (Sep 30 2026 Desktop-parity review) - editing a sent message truncates the tail and resends (`web/src/components/messages/edit.ts`). Keep the old branch: store sibling versions of the edited turn and add a `< 2/3 >` switcher. Touches message storage (parent pointer or branch id), history loading, sync and search.
- [ ] **Mermaid diagrams in markdown** (Sep 30 2026 Desktop-parity review) - render ```` ```mermaid ```` blocks client-side, lazy-loaded as its own vendor chunk like KaTeX; fall back to the code block on parse errors; theme for light/dark.
- [ ] **Export conversation as Markdown** (Aug 2026 UX batch) - per-conversation action (action sheet / chat header) downloading the full history as .md: titles, roles, timestamps, code blocks preserved; attachments referenced by filename.
- [ ] **Conversation sharing** - public links for sharing conversations.
- [ ] **Keyboard shortcuts** for common actions.
- [ ] **Voice conversation mode** - speech-to-text in, text-to-speech out.
- [ ] **Video uploads follow-ups** (Jul 2026, docs/superpowers/specs/2026-07-19-video-upload-design.md):
  - Multipart streaming upload endpoint (approach B in the spec) - revisit if base64 JSON memory spikes or >100 MB clips become a real problem
  - Poster-frame thumbnails (needs ffmpeg on the server)
  - Dedupe repeated base64 decodes of upload payloads (validate_files → save_file_to_blob_store → extract_file_metadata → attach_gemini_file_uris each decode; ~400 MB transient for a 100 MB video)
  - Revoke video blob object URLs when message elements are removed (attachments.ts tap-to-load player; bounded leak)
  - Sweep scan: track the last-swept cutoff instead of rescanning all old messages daily (fine at current scale)

## Integrations & proactive nudges

- [ ] **Gmail integration** - read-only inbox triage via OAuth (reuse the Calendar OAuth pattern): what needs a reply, invoices, feed for briefings/agents. (An MCP client would cover this without a bespoke module - decide which first.)
- [ ] **Web Push Phase 3** (Phases 1-2 + Daily Briefing shipped Jun 2026; docs/features/push-notifications.md):
  - Planner event reminders (needs a small scheduler loop), program nudges (opt-in per program), budget alerts (threshold check in the cost-recording path)
  - Daily language review nudge ("5 words due today") - SRS itself shipped in the tutor prompt; ideally a system-managed agent like the Daily Briefing
  - Cross-device read-state suppression if stale notifications annoy: grace-delay sends ~30-60 s and skip when the message was viewed anywhere (agents have `last_viewed_at`; regular conversations would need a viewed ping + column)
- [ ] **Daily Briefing follow-ups** - evening review variant (second time slot); iterate the default prompt on real briefings.
- [ ] **Oura integration** for planner health data.
- [ ] **Traffic-aware car ETAs** (docs/superpowers/specs/2026-08-16-location-awareness-design.md) - swap `get_route(mode="car")` to HERE or TomTom free tier for live traffic; keep Mapy.com for POI search and other modes.

## Planner & programs

- [ ] **Planner dashboard v2** - two-column layout (events left, tasks right; complete tasks via the Todoist API; open-in-Calendar links); AI daily summary strip, hour-marker timeline, quick-add task; one-click AI time-blocking ("schedule my P1/P2 tasks into today's free slots", composing Todoist + Calendar tools).
- [ ] **Health/recovery coach program** - third program type on Garmin data; the shared program factory is in place.

## Code quality & tooling

- [ ] **File-size convention violations** - production files over 500 lines (Sep 30 2026 count): thumbnails.ts (1058), planner_data.py (1015), Sidebar.ts (997), graph.py (947), types/api.ts (925, hand-written - shrink toward generated-api.ts), SyncManager.ts (923), AgentEditor.ts (885), config.py (857, declarative), icons.ts (759, data), garmin.py (723), messages/render.ts (715), google_calendar.py (671), MessageInput.ts (664), init.ts (647), messages/streaming.ts (626), messages/pagination.ts (614), search_provider.py (609), code_execution.py (606), garmin_workout.py (604), tool_display.py (601), stream-recovery.ts (596), web.py (583), PlannerDashboard.ts (565), web config.ts (561), CommandCenter.ts (547), whatsapp.py (537), keyboard-viewport.ts (517), tools/__init__.py (514), agent.py (505), KVStorePage.ts (502). Largest tests: test_routes_chat.py (1645), sync-manager.test.ts (1638), conversation.spec.ts (1603), e2e-server.py (1497), test_agents.py (1493).
- [ ] **INEFFECTIVE_DYNAMIC_IMPORT build noise** - agents.ts's dynamic import of conversation.ts is a cycle-breaker that logs a warning at every build; untangle the cycle.

## Parked (reopen on the trigger)

- **Model routing / tiering by turn difficulty** - parked Aug 2026 ([spec](docs/superpowers/specs/2026-08-20-model-routing-design.md)): `gemini-3.5-flash-lite` matched Flash on the eval suite (26/30 vs 27/30) but ran ~20-30% slower with worse tail latency. *Trigger:* a current-generation lite tier ships, or the Jan 2027 Flash price doubling (savings estimate rises from ~15% to ~25-30%). Check: `DEFAULT_MODEL=<candidate> make eval` (quality + timing in one run). Design caveats (cache keyed per (profile, model), tool-calling quality on the cheap model) are in the spec.
- **Tool result caching** - ruled out for web search (Sep 15 2026: 1.1% duplicate rate across all conversations, ~20 calls/month saved; search capacity is a supply problem, hence the Linkup provider). *Trigger:* measured repeats in another tool family (`fetch_url` of the same page, Garmin/Todoist polling) - measure first.
- **Context-cache 403 blip** - seen once (Aug 19 2026, locally): a fresh Gemini cache returned PERMISSION_DENIED seconds after creation, fine minutes later; zero in prod logs. *Trigger:* a recurrence - then add a one-shot uncached retry when an invoke with `cached_content` 403s (`chat_node` / `create_chat_model`).
- **Re-upgrade TypeScript to 7.x** - pinned to ^6.0.3 (Jul 2026), Dependabot ignores `typescript >=7.0.0` ([.github/dependabot.yml](.github/dependabot.yml)). TS 7.0 ships no JS API, so typescript-eslint cannot load it ([#10940](https://github.com/typescript-eslint/typescript-eslint/issues/10940) locked "blocked by external API"; [#12518](https://github.com/typescript-eslint/typescript-eslint/issues/12518) closed not_planned). *Trigger:* TS 7.1's new API lands and a typescript-eslint major (v9) ports to it - realistically late 2026; weekly re-checks are wasted effort. Then bump both, drop the Dependabot ignore, verify `npm ci` + typecheck + lint. Optional interim for build speed only: Microsoft's side-by-side setup (`"typescript-7": "npm:typescript@^7.0.2"` for typecheck/build, TS 6 for eslint).
