# AI Chatbot - TODO

Actionable work only. Tags (S/A/C/X/F/Q/T = June 2026 audit rounds 1-2, R = round 3) kept for traceability. Completed work lives in git history.

## Features

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
- [ ] **Personal knowledge base** - Persistent user documents searchable across conversations. SQLite FTS5 over extracted text is enough.
- [ ] **Thinking mode toggle** - Gemini thinking mode with configurable level, long-press UI like the voice-language selector.
- [ ] **Conversation sharing** - Public links for sharing conversations.
- [ ] **Keyboard shortcuts** for common actions.
- [ ] **Voice conversation mode** - Speech-to-text in, text-to-speech out.
- [ ] **Oura integration** for planner health data.
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls within a conversation.

## Autonomous Agents

- [ ] **Multi-step workflows** for agents.

## Planner Dashboard

- [ ] **Two-column layout** - Events left, tasks right; task completion via Todoist API; open-in-Calendar links.
- [ ] **Summary + timeline** - AI daily summary strip, hour-marker timeline, quick-add task.
- [ ] **AI time-blocking** - One-click "schedule my P1/P2 tasks into today's free slots" composing Todoist + Calendar tools.

## Programs (Sports / Language / future)

- [ ] **Daily language review nudge** - SRS itself shipped in the tutor prompt (Jun 2026: due-queue batch quiz, mastery/leech handling); remaining: a scheduled nudge ("5 words due today") via push, ideally a system-managed agent like the Daily Briefing.
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Q2 dedup done - shared program factory is in place.

## AI-Agent Best Practices

- [ ] **Agent-behavior observability (A3, remainder)** - Eval harness shipped Aug 2026 (`make eval`, see [docs/testing/evals.md](docs/testing/evals.md)); baseline 6/8 with two tracked findings: research round overruns and cite_sources adherence after web tools. Remaining: per-turn metrics for tool success/tokens/latency/retries, and grow the case set (delegate_task case, program-mode cases, memory-retrieval case).
- [ ] **Browser action batching** (Aug 2026 agent review) - `browser.py` allows one action per LLM round-trip, so "log in and check X" costs 6+ full model rounds. Accept an `actions: []` batch for mechanical sequences and return richer post-action state (URL + title + element summary) to cut observation rounds. Longer term: a11y-tree snapshots with stable element refs instead of text extraction.
- [ ] **Cross-turn tool digests** (Aug 2026 agent review) - history rebuilds assistant turns as plain text; prior turns' tool results are dropped (only `tools_used`/`tool_summary` survive), so "what did that article say?" forces a re-fetch. Persist a compact per-turn digest (~300 chars: URLs fetched + key facts) in message metadata and surface it via `MSG_CONTEXT`.
- [ ] **Mid-run steering** (Aug 2026 agent review) - no way to redirect a running multi-round turn ("stop, wrong ticker"). Cheap approximation: per-request cancel/interject flag checked between graph rounds (`check_tool_results` is the natural seam), injecting the user's interjection as guidance. Needs a small frontend affordance next to the stop button.
- [ ] **MSG_CONTEXT migration** (Aug 2026 agent review) - the ~60-line multi-chunk echo-stripping state machine in `agent.py:stream_chat_events` exists because metadata is inlined into message content as HTML comments. If Gemini's API grows first-class per-message metadata, migrate and delete the stripping.

## Performance / Cost

(Cost tooling: `scripts/analyze_costs.py`. Context caching, token-based compaction, batched `web_search`, and a per-turn tool-round cap all shipped Jun 2026.)

- [ ] **Model routing / tiering by turn difficulty** - the biggest untapped cost lever, and a real-agent pattern in its own right. Everything currently runs on `gemini-3.7-flash` (rates in `Config.MODEL_PRICING`); a large share of turns are short and trivial (greetings, quick lookups, one-line follow-ups) yet pay frontier-flash rates. Route by predicted difficulty: cheap/small model for simple turns, the strong model reserved for genuinely hard requests (multi-step reasoning, tool orchestration, code). Two viable shapes: (a) a lightweight up-front classifier (a fast Flash call emitting a model tier — the removed `should_plan` classifier in git history shows the pattern); or (b) escalation — start on the cheap model and bump to the strong one when the turn needs tools / the classifier flags complexity / a retry is needed. Caveats to design around: the context cache is keyed per `(profile, model)` (`context_cache.py`), so mixing models fragments cache hits — weigh cheaper tokens vs lost cache; and the cheap model must hold tool-calling quality (validate against the agent graph, not just chat). Add a `MODELS`/pricing tier table in `config.py` and measure the blended cost/msg via `scripts/analyze_costs.py` (already groups BY MODEL) before/after.

## Reliability

- [ ] **Align prod Python with `requires-python`** - pyproject says >=3.14, prod runs 3.13.

## Code Quality

- [ ] **File-size convention violations (Q3, remainder)** - First pass done (chat_streaming.py -> 4 modules; client.ts -> http/sse/client). Remaining over-cap: chat_streaming.py (1147, producer/consumer engine split next), client.ts (1017, domain-module split touches every importer), messaging.ts (1639), prompts.py/schemas.py (declarative), agent.py, models/agent.py, SettingsPopup.ts, routes/agents.py, planner_data.py, todoist.py, thumbnails.ts.

## Tests & Tooling

- [ ] **Re-upgrade TypeScript to 7.x** - Blocked upstream on TypeScript itself, not on typescript-eslint's peer range. `typescript` stays pinned to ^6.0.3 (Jul 2026); Dependabot ignores `typescript >=7.0.0` in [.github/dependabot.yml](.github/dependabot.yml). Originally hit as an `npm ci` failure in the dependency-audit workflow after Dependabot merged the TS 7.0.2 bump (#182).
  - **Real blocker**: TS 7.0 ships *no JS API* at all - `require("typescript")` exposes only `version`/`versionMajorMinor`, so eslint crashes in `typescript-estree` reaching for `ts.Extension.Cjs`. The `<6.1.0` peer cap is a symptom, not the gate. Microsoft's TS 7.0 announcement expects **TS 7.1** to ship a new *and different* API, and names typescript-eslint as the reason TS 7 can run side-by-side with TS 6.0.
  - **Watch signal**: TS 7.1's API landing (API work is active in `microsoft/typescript-go`), *not* typescript-eslint releases. Their tracking issue [#10940](https://github.com/typescript-eslint/typescript-eslint/issues/10940) is labelled "blocked by external API" and was locked Jul 9 2026 ("nothing we can do... no stable JS API"); a TS 7.0.2 support report matching this repo's exact versions was closed `not_planned` ([#12518](https://github.com/typescript-eslint/typescript-eslint/issues/12518)). Expect a typescript-eslint major (v9) for the port, not a peer bump - realistically late 2026 at the earliest. Re-checking weekly is wasted effort.
  - **Optional interim** (build speed only, adds a second toolchain): Microsoft's blessed side-by-side setup - keep `typescript@^6.0.3` as eslint's peer, add TS 7 as an alias (`"typescript-7": "npm:typescript@^7.0.2"`), point `typecheck`/`build` at it while eslint stays on TS 6.
  - When it does land: bump both together, remove the Dependabot ignore rule, verify `npm ci` + typecheck + lint pass.

- [ ] **Webkit search-spec flake under full-suite load** - 2 occurrences (Jun 2026), still unexplained after a deep hunt (Jun 12):
  - The "stray version banner" clue was a red herring: `.version-banner` hides via `transform: translateY(-100%)` so it is ALWAYS in the accessibility tree and appears in every failure snapshot.
  - Real failure state: `isSearchActive=true` + `store.searchQuery=''` + empty input after `fill()`. Only in-app paths producing that are Escape-on-input or the clear button - neither happens in the specs.
  - Not reproducible: ~430 additional executions (288 webkit repeats under a parallel heavy-spec load generator + 2 more full-suite runs with `--trace=retain-on-failure`) all passed.
  - Forensics now in place: `SearchResults.ts` logs a warning when the hint renders while the DOM input has text (distinguishes lost-input-event vs cleared-input); CI retries record traces incl. console, so the next natural occurrence is diagnosable.
  - Local-env hazard found en route (likely unrelated but nasty): a leaked/manual server on 8001 + `reuseExistingServer` + a rebuild = the old in-memory Vite manifest points at deleted hashed assets -> mass spec failures. If a weird local E2E failure wave appears, check `lsof -iTCP:8001` first.


