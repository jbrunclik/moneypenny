# Agent Improvements — Design Spec (Aug 2026)

Outcome of a full agent-implementation review (loop, tools, memory, cost) benchmarked
against best-in-class agents (Claude, ChatGPT, Hermes). Six phases, each independently
shippable as commits to `main`, plus small fixes and TODO entries for deferred items.

## Phase 0 — Deferred items to TODO + small fixes

**TODO.md additions** (deferred, not implemented now):
- Browser action batching (`actions: []` per call) + richer post-action state.
- Cross-turn tool digests: persist a compact per-turn digest (URLs fetched, key facts)
  in message metadata, surface via `MSG_CONTEXT`.
- Mid-run steering: per-request cancel/interject flag checked between graph rounds.
- MSG_CONTEXT migration note: move inlined metadata to first-class API metadata if
  Gemini grows support (removes the echo-stripping state machine in `agent.py`).
- Model routing entry already exists — refresh the stale model name.

**Small fixes (implemented):**
- `src/agent/retry.py`: transient detection walks the exception `__cause__`/`__context__`
  chain for typed transient exceptions, and substring patterns only scan the first
  300 chars of the message (payload text embedded in exception strings false-positived).
- `src/agent/executor.py`: `AgentExecutor.run(message)` currently ignores `message`.
  Thread it through `execute_agent(..., extra_message=...)` and append it to the
  trigger message (`Message from triggering agent: ...`). Makes `trigger_agent`
  actually able to pass instructions between agents.

## Phase 1 — Persistent sandbox sessions

`execute_code` creates and tears down a Docker container per call. Reuse a per-conversation
`SandboxSession` instead (pattern mirrors `browser.py` session pool).

- New `src/agent/tools/sandbox_sessions.py`: pool keyed by `conversation_id`;
  LRU cap `CODE_SANDBOX_MAX_SESSIONS` (default 2), TTL
  `CODE_SANDBOX_SESSION_TTL_SECONDS` (default 900) with a 60s background cleanup
  thread; per-session lock serializes runs; unhealthy sessions (run raises) are
  closed and replaced.
- Semantics (honest about what llm-sandbox gives us): each `run()` is a fresh Python
  process — **variables do not persist**; the **container and its filesystem do**.
  Wrapper creates a persistent `/work` directory advertised in the tool docstring
  ("save intermediate files to /work — they survive across execute_code calls in
  this conversation"). `/output` is cleared at the start of every run so per-run
  file extraction stays correct.
- No conversation context (e.g. eval/unit contexts) → ephemeral session, current behavior.
- Same security envelope: `network_disabled`, mem/cpu limits, `init: True`.

## Phase 2 — Remove planning subsystem, adopt thinking-level plumbing

Planning (`should_plan` classifier + `plan_node`) is disabled by default and predates
usable native reasoning. Remove it entirely; rely on Gemini thinking.

- Delete from `graph.py`: `should_plan`, `plan_node`, `PLANNING_PROMPT`,
  `PLANNING_DECISION_PROMPT`, `plan` state field, plan injection in `chat_node`,
  plan graph edges. Entry point becomes `chat` directly.
- Delete config: `AGENT_PLANNING_ENABLED`, `AGENT_PLANNING_MIN_LENGTH`; update
  `.env.example`, tests, docs.
- Thinking: `MODELS` entries gain optional `"thinking_level"` (langchain-google-genai
  4.3.2 `thinking_level` param, Gemini 3+). `create_chat_model` passes it when set.
  Default: unset (API default). UI toggle stays a TODO.

## Phase 3 — Composite research tool + pluggable search provider

Round-multiplication (each tool round re-bills accumulated context) is the dominant
cost driver. Collapse the common search→fetch loop into one round, and make the
search backend upgradable.

- New `src/utils/search_provider.py`: `search_web(query, num_results) -> list[SearchResult]`.
  Brave Search API when `BRAVE_SEARCH_API_KEY` is set (better relevance), DDGS
  fallback otherwise. `web_search` tool refactored onto it (JSON contract unchanged).
- Refactor `web.py`: extract `fetch_page_text(url, max_chars) -> tuple[str | None, str | None]`
  (text, error) from `fetch_url`'s HTML path for reuse (SSRF checks included).
- New `src/agent/tools/research.py`: `research(question, queries?, max_sources?)` —
  one tool call that (1) runs batched provider searches, (2) picks top unique URLs
  across queries (cap `RESEARCH_MAX_SOURCES`, default 5), (3) fetches them concurrently
  (ThreadPoolExecutor, 4 workers), (4) returns per-source extracted text trimmed to
  `RESEARCH_PER_SOURCE_MAX_CHARS` (default 4000), wrapped as untrusted content, plus
  the search snippets for uncrawlable sources. Deterministic — no nested LLM call.
- Registered for all modes incl. anonymous (read-only web); added to autonomous
  baselines next to `web_search`/`fetch_url`; prompt guidance: prefer `research`
  when a question needs multiple sources.

## Phase 4 — Delegate/subagent tool

Context isolation: a scoped sub-agent does the multi-round digging; only its digest
enters the main conversation.

- New `src/agent/tools/delegate.py`: `delegate_task(task, expected_output?)` — runs a
  fresh `ChatAgent` (model `DELEGATE_MODEL`, default = `DEFAULT_MODEL`) with tools
  `[research, web_search, fetch_url]`, no history, focused system prompt
  (`DELEGATE_SYSTEM_PROMPT` in prompts.py), `chat_batch` synchronously inside the
  tool call. Returns JSON `{result, sources, usage}`.
- Recursion guard: sub-agent's toolset never includes `delegate_task`; a contextvar
  refuses nested delegation defensively.
- Context-cache interaction: `ChatAgent` gains `enable_context_cache: bool = True`;
  delegate passes `False` (a per-call cache create for a custom tool subset would
  churn cache entries).
- Cost: sub-run usage rides in the tool result (`usage` at top level of the tool
  JSON); `calculate_and_save_message_cost` adds delegate token cost into `cost_usd`
  via a new `tool_llm_cost` component (no schema change).
- Autonomous agents: available via `_TOOL_MAP` grant only (it spends money), enforced
  by `check_autonomous_permission`.
- Interactive chats: always available (incl. anonymous — read-only web tools inside).
- `TOOL_METADATA` entry so the frontend shows a sensible "Delegating…" chip.

## Phase 5 — Tiered memory injection + embeddings retrieval

- **Tiering** (`prompts.py`): when memory count ≤ `MEMORY_INJECT_FULL_MAX` (default 60),
  inject all (current behavior). Above it: inject all `protected` + `preference` +
  `goal` entries plus the `MEMORY_INJECT_RECENT_COUNT` (default 15) most recently
  updated others, with a note telling the model that N more exist and to use
  `search_memory`.
- New `search_memory(query)` tool (`memory.py`): case-insensitive substring match over
  the user's memories (bank ≤ 200 entries — no index needed), upgraded to hybrid
  cosine + substring once embeddings exist. Registered wherever `manage_memory` is.
- **Embeddings**: migration `0049_add_embeddings.py` — table
  `embeddings(id, user_id, kind, ref_id, model, dim, vector BLOB, created_at)`,
  `UNIQUE(kind, ref_id)`. `src/utils/embeddings.py` wraps the google-genai embed API
  (`EMBEDDING_MODEL = "gemini-embedding-001"`, `EMBEDDING_DIM = 768`, vectors packed
  with `struct`); cosine search is brute-force in Python (family-scale data).
- Write paths (background daemon threads, same pattern as title generation):
  memory add/update → embed; message save → embed user/assistant text.
  `scripts/backfill_embeddings.py` for existing rows.
- Read paths: `search_memory` hybrid; `search_conversations` gains semantic results
  merged with FTS (labelled `match_type`), FTS-only fallback when the embed call fails.

## Phase 6 — Eval harness

- `evals/cases/*.yaml`: `id`, `description`, `user` (single-turn to start), optional
  `requires` (e.g. `code_sandbox`), `expect`: rubric text + optional `required_tools`
  / `forbidden_tools` / `max_tool_rounds`.
- `evals/run.py`: runs each case through `ChatAgent.chat_batch` against an isolated
  temp DB (`DATABASE_PATH` env override, run as its own process), records response +
  tool telemetry, scores with an LLM judge (`EVAL_JUDGE_MODEL`, default
  `gemini-3.1-pro-preview`) → score 1–5 + pass + reasoning. Writes JSON + markdown
  summary to `evals/results/` (gitignored). Informational — no CI gate.
- `make eval` target; ~10 seed cases (no-tool answer, web lookup + citation, memory
  write, multi-step research, code exec, Czech-language, title setting, …).
- Replaces the A3 TODO entry.

## Non-goals

- Model routing/tiering (stays in TODO — needs cost measurement first).
- Browser batching, cross-turn digests, mid-run steering (TODO).
- True persistent Python kernel in the sandbox (would need Jupyter-in-container).
- Vector index (sqlite-vec) — brute force is fine at this scale.
