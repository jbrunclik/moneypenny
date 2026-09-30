# Moneypenny - TODO

Actionable work only. Tags (S/A/C/X/F/Q/T = June 2026 audit rounds 1-2, R = round 3) kept for traceability. Completed work lives in git history.

## Features

- [ ] **Export conversation as Markdown** (Aug 2026 UX batch, deferred) — per-conversation action (action sheet / chat header) that downloads the full history as a .md file: titles, roles, timestamps, code blocks preserved; attachments referenced by filename.

- [ ] **Video uploads — deferred follow-ups** (Jul 2026, see docs/superpowers/specs/2026-07-19-video-upload-design.md):
  - Multipart streaming upload endpoint (approach B in the spec) — revisit if base64 JSON memory spikes or >100MB clips become a real problem
  - Video poster-frame thumbnails (requires ffmpeg on the server)
  - Sweep scan optimization: track last-swept cutoff instead of rescanning all old messages daily (fine at current scale)
  - Dedupe repeated base64 decodes of upload payloads (validate_files → save_file_to_blob_store → extract_file_metadata → attach_gemini_file_uris each decode independently; ~400MB transient allocations for a 100MB video)
  - Revoke video blob object URLs when message elements are removed (attachments.ts tap-to-load player; bounded leak today)

- [ ] **Traffic-aware car ETAs** - Optional upgrade to location awareness (see docs/superpowers/specs/2026-08-16-location-awareness-design.md): swap `get_route(mode="car")` backend to HERE or TomTom free tier for live-traffic ETAs; keep Mapy.com for POI search and other modes.
- [ ] **Gmail integration** - Read-only inbox triage via OAuth (reuse the Calendar OAuth pattern): summarize what needs a reply, surface invoices, feed briefings/agents.
- [ ] **Web Push notifications, Phase 3** - Phases 1-2 + Daily Briefing shipped (Jun 2026; see [docs/features/push-notifications.md](docs/features/push-notifications.md)). Remaining:
  - Planner event reminders (needs a small scheduler loop), program nudges (opt-in per program), budget alerts (threshold check in the cost-recording path)
  - Cross-device read-state suppression if stale notifications annoy: grace-delay sends ~30-60s and skip when the message was viewed anywhere (agents have last_viewed_at; regular conversations would need a viewed ping + column)
- [ ] **Daily Briefing follow-ups** - Core shipped (Jun 2026: opt-in toggle + delivery time in Settings, backed by a system-managed agent). Remaining ideas: evening review variant (second time slot), richer default prompt iteration based on real briefings.
- [ ] **Personal knowledge base** - Persistent user documents searchable across conversations. SQLite FTS5 over extracted text + the embeddings table (shipped Aug 2026, `kind` column extends naturally to `document`) covers both keyword and semantic search.
- [ ] **MCP client (connectors)** (Sep 30 2026 Desktop-parity review) - every integration is a hand-written tool module; an MCP client in the tool layer would plug in Gmail/Drive/GitHub/Notion-style servers without new code per service. MCP tools must go through all three availability layers (binding, `check_tool_permission`, contextvar forwarding - see docs/features/agent-tools.md) and default to *not* safe for autonomous agents (remote tool results are untrusted input, same reasoning as `manage_memory`). Pairs with deferred tool loading below - MCP servers can expose dozens of tools.
- [ ] **Deferred tool loading** (Sep 30 2026 Desktop-parity review) - bind only core tools plus a `find_tools` / `load_tools` meta-tool; integration tools load on demand. Goal: smaller base prompt, better context-cache hit rate, room for MCP. **Must ship with evals**: record a `make eval` baseline before the change (tool-selection accuracy, rounds per turn, cost), add cases where the needed tool is not loaded yet (the model must discover it, not refuse or hallucinate a call), and compare after. Only merge if selection accuracy holds and the extra discovery round is cheaper than the prompt tokens it saves (measure; see docs/architecture/agent-graph.md "Tool Round Economics").
- [ ] **Artifacts** (Sep 30 2026 Desktop-parity review) - a `create_artifact` tool emitting HTML/SVG rendered live in a sandboxed iframe (`sandbox="allow-scripts"`, no same-origin, strict CSP) in a side panel; versions stored per message, reopenable from the conversation. `create_file` covers downloads; this covers "show me a working thing" (calculators, charts, mini-apps).
- [ ] **Projects** (Sep 30 2026 Desktop-parity review) - group conversations under a project with its own instructions and pinned documents, searched per project. Builds on the Personal knowledge base item above (same storage + retrieval); projects are the scoping/UI layer on top.
- [ ] **Branching on message edit** (Sep 30 2026 Desktop-parity review) - editing a sent message currently truncates the tail and resends (`web/src/components/messages/edit.ts`). Keep the old branch instead: store sibling versions of the edited turn and add a `< 2/3 >` switcher. Touches message storage (parent pointer or branch id), history loading, sync and search.
- [ ] **Mermaid diagrams in markdown** (Sep 30 2026 Desktop-parity review) - render ```` ```mermaid ```` blocks client-side, lazy-loaded as its own vendor chunk like KaTeX; fall back to the code block on parse errors; theme for light/dark.
- [ ] **Conversation sharing** - Public links for sharing conversations.
- [ ] **Keyboard shortcuts** for common actions.
- [ ] **Voice conversation mode** - Speech-to-text in, text-to-speech out.
- [ ] **Oura integration** for planner health data.
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls within a conversation. **Mostly ruled out for web search (measured Sep 15 2026):** of 2,018 web searches logged in Sep, 1,996 were unique — a 1.1% duplicate rate, and that is across ALL conversations; scoped within one conversation it is smaller still. Top repeat was a single query at 5 hits. A search cache would save ~20 calls/month, so search capacity is a supply problem, not a dedup problem (hence the Linkup provider, commit 4e16fc0). Only worth revisiting for other tool families (repeated `fetch_url` of the same page, Garmin/Todoist polling) — re-measure that family first before building anything.

## Planner Dashboard

- [ ] **Two-column layout** - Events left, tasks right; task completion via Todoist API; open-in-Calendar links.
- [ ] **Summary + timeline** - AI daily summary strip, hour-marker timeline, quick-add task.
- [ ] **AI time-blocking** - One-click "schedule my P1/P2 tasks into today's free slots" composing Todoist + Calendar tools.

## Programs (Sports / Language / future)

- [ ] **Daily language review nudge** - SRS itself shipped in the tutor prompt (Jun 2026: due-queue batch quiz, mastery/leech handling); remaining: a scheduled nudge ("5 words due today") via push, ideally a system-managed agent like the Daily Briefing.
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Q2 dedup done - shared program factory is in place.

## AI-Agent Best Practices

- [ ] **Browser a11y-tree snapshots** (Aug 2026 agent review; batching + element summaries shipped Sep 30 2026) - replace the CSS-selector element summary (`PAGE_STATE_JS` in `browser_steps.py`) with accessibility-tree snapshots carrying stable element refs the model can click by ref. Also re-measure browser rounds per turn from production logs to confirm batching is actually used (same caveat as the `web_search` batch parameter, which went unused for months).
- [ ] **MSG_CONTEXT migration** (Aug 2026 agent review) - the ~60-line multi-chunk echo-stripping state machine in `agent.py:stream_chat_events` exists because metadata is inlined into message content as HTML comments. If Gemini's API grows first-class per-message metadata, migrate and delete the stripping.

## Performance / Cost

(Cost tooling: `scripts/analyze_costs.py`. Context caching, token-based compaction, batched `web_search`, and a per-turn tool-round cap all shipped Jun 2026 — but see the verification item below: the batch parameter went essentially unused for three months.)

- [ ] **Verify the tool-round work moved real traffic** (overdue since ~Sep 20 2026) - the Sep 2026 efficiency changes (result-attached nudges, composite Garmin/kv_store actions, commit 6d608bc) were a behavioral bet; only the baseline is measured (14 days to Sep 6: 95.5% of rounds had one tool call, `web_search` solo in 99% of its rounds, 83 round-cap hits). Re-measure from production logs (`LLM requested tool calls` / `Tool round completed` lines, turns = rounds ≤90s apart). If single-call rounds haven't moved, go structural (e.g. reject a second single-query `web_search` in a turn with an error naming the batched call); if they have, record the numbers in docs/architecture/agent-graph.md "Tool Round Economics" and consider lowering `AGENT_MAX_TOOL_ROUNDS`. Eval rounds also drifted up ~19% Sep 6-15 (single samples, noisy) - re-check with repeated `make eval` runs, now that evals carry request ids (cb03128) so the nudges are live in them.

- [ ] **Model routing / tiering by turn difficulty** - PARKED Aug 2026 after a data-driven suitability check (see [docs/superpowers/specs/2026-08-20-model-routing-design.md](docs/superpowers/specs/2026-08-20-model-routing-design.md)): `gemini-3.5-flash-lite` matched Flash on the 30-case eval suite (26/30 vs 27/30, same failures) but ran ~20-30% SLOWER with worse tail latency, failing the "faster, not slower" requirement. Re-check when a current-generation lite tier ships: quality gate + timed comparison are both one command (`DEFAULT_MODEL=<candidate> make eval`). Original sizing: 60% of turns use zero tools; savings would be ~15% now / ~25-30% after the Jan 2027 Flash price doubling. Everything currently runs on `gemini-3.8-flash` (rates in `Config.MODEL_PRICING`); a large share of turns are short and trivial (greetings, quick lookups, one-line follow-ups) yet pay frontier-flash rates. Route by predicted difficulty: cheap/small model for simple turns, the strong model reserved for genuinely hard requests (multi-step reasoning, tool orchestration, code). Two viable shapes: (a) a lightweight up-front classifier (a fast Flash call emitting a model tier — the removed `should_plan` classifier in git history shows the pattern); or (b) escalation — start on the cheap model and bump to the strong one when the turn needs tools / the classifier flags complexity / a retry is needed. Caveats to design around: the context cache is keyed per `(profile, model)` (`context_cache.py`), so mixing models fragments cache hits — weigh cheaper tokens vs lost cache; and the cheap model must hold tool-calling quality (validate against the agent graph, not just chat). Add a `MODELS`/pricing tier table in `config.py` and measure the blended cost/msg via `scripts/analyze_costs.py` (already groups BY MODEL) before/after.

- [ ] **INEFFECTIVE_DYNAMIC_IMPORT build noise** - agents.ts's dynamic import of conversation.ts is a cycle-breaker that logs a warning at every build; untangle the cycle properly. (The vendor chunk split itself shipped: vendor-katex/hljs/markdown/mediabunny groups in vite.config.ts `advancedChunks`.)

## Reliability

- [ ] **Model 503 = 10-minute hang, no fallback** (Aug 27 2026 incident) - during a Google capacity spike, `gemini-3.7-flash` returned `503 UNAVAILABLE` on every call while `gemini-3.1-pro-preview` stayed up. Two problems: (1) `with_retry` treats 503 as transient and retries the *same* dead model up to `AGENT_MAX_RETRIES=3`, each re-triggering google-genai's own internal backoff retries, with `CHAT_TIMEOUT=600s` as the backstop - so a turn sits on "Thinking" for minutes before failing (looks stuck; it does eventually reset). (2) No cross-model fallback, so a single-tier outage takes the whole app down even though the other tier works. Fix: on a model-unavailable 503, **fail fast** (don't burn 3×N retries on a broadly-down model) and **fall back to the other MODELS tier** for that turn (mind: context cache is keyed per (profile, model), so the fallback invoke is uncached - `graph.py:chat_node` / `retry.py` is the seam). Immediate operator mitigation during an outage: switch the model dropdown to Advanced, or flip `DEFAULT_MODEL` env + restart.

- [ ] **Context-cache 403 blip** - observed once (Aug 19 2026, locally): a freshly created Gemini context cache returned PERMISSION_DENIED when used seconds after creation, then worked minutes later; prod logs show zero occurrences over 3 days of hourly rotations. If it recurs: add a one-shot uncached-fallback retry when an invoke with `cached_content` 403s (`chat_node`/`create_chat_model` seam).

## Code Quality

- [ ] **File-size convention violations (remainder)** - Sep 30 2026 pass split chat routes/streaming, messaging.ts, store.ts (slices), SettingsPopup.ts, client.ts, conversation.ts, schemas.py, models/agent|message|conversation|user.py, routes/agents|conversations.py, agent.py and the grab-bag test files. Still over 500 lines: thumbnails.ts (1058), planner_data.py (1015), Sidebar.ts (997), SyncManager.ts (923), types/api.ts (920, hand-written types - shrink toward generated-api.ts), graph.py (906), AgentEditor.ts (884), config.py (847, declarative), icons.ts (759, data), garmin.py (723), messages/render.ts (715), google_calendar.py (671), MessageInput.ts (664), init.ts (647), plus a tail of 500-630-line tool and component modules; tests/unit/test_agents.py (1493) and test_graph.py (1069).

## Tests & Tooling

- [ ] **Re-upgrade TypeScript to 7.x** - Blocked upstream on TypeScript itself, not on typescript-eslint's peer range. `typescript` stays pinned to ^6.0.3 (Jul 2026); Dependabot ignores `typescript >=7.0.0` in [.github/dependabot.yml](.github/dependabot.yml). Originally hit as an `npm ci` failure in the dependency-audit workflow after Dependabot merged the TS 7.0.2 bump (#182).
  - **Real blocker**: TS 7.0 ships *no JS API* at all - `require("typescript")` exposes only `version`/`versionMajorMinor`, so eslint crashes in `typescript-estree` reaching for `ts.Extension.Cjs`. The `<6.1.0` peer cap is a symptom, not the gate. Microsoft's TS 7.0 announcement expects **TS 7.1** to ship a new *and different* API, and names typescript-eslint as the reason TS 7 can run side-by-side with TS 6.0.
  - **Watch signal**: TS 7.1's API landing (API work is active in `microsoft/typescript-go`), *not* typescript-eslint releases. Their tracking issue [#10940](https://github.com/typescript-eslint/typescript-eslint/issues/10940) is labelled "blocked by external API" and was locked Jul 9 2026 ("nothing we can do... no stable JS API"); a TS 7.0.2 support report matching this repo's exact versions was closed `not_planned` ([#12518](https://github.com/typescript-eslint/typescript-eslint/issues/12518)). Expect a typescript-eslint major (v9) for the port, not a peer bump - realistically late 2026 at the earliest. Re-checking weekly is wasted effort.
  - **Optional interim** (build speed only, adds a second toolchain): Microsoft's blessed side-by-side setup - keep `typescript@^6.0.3` as eslint's peer, add TS 7 as an alias (`"typescript-7": "npm:typescript@^7.0.2"`), point `typecheck`/`build` at it while eslint stays on TS 6.
  - When it does land: bump both together, remove the Dependabot ignore rule, verify `npm ci` + typecheck + lint pass.
