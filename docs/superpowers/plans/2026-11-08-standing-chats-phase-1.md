# Standing Chats Phase 1: One Turn Path - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Writing in an agent, sports or language chat runs the ordinary chat turn - full chat tools, conversation facts, freshness check, context cache, normal compaction - with the chat's standing instructions and domain context added; agent runs drop destructive compaction.

**Architecture:** A `StandingContext` (kind, name, instructions, data, kv namespace) is loaded once per turn for a standing chat and replaces the three per-mode contexts (`agent_context` + `AgentContext`, `sports_context`, `language_context`) in the interactive path. The ordinary prompt gains one "standing chat" section in its dynamic tail; tool selection, cache profile, freshness and facts stop branching on mode. Autonomous runs (`executor.py`, `item_runner.py`) keep their own path, but their history uses the regular chat compaction instead of deleting messages.

**Tech Stack:** Flask, LangGraph `ChatAgent`, Gemini context cache, SQLite kv store, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-08-standing-chats-design.md` (phase 1).

## Global Constraints

- Production daily driver (4 users); repo is public - no infra in docs/commits.
- The three production agents, the program chats, their kv state and histories survive.
- Planner (`is_planning`) is out of scope - unchanged.
- Autonomous runs keep their grants (`get_tools_for_agent`), approvals (`request_approval`), the tool node's autonomous split, `fresh_context`, `[SILENT]`.
- Full chat tools when the user writes in a standing chat (Jiri).
- Consolidate: remove mode branches and dead code with their tests and docs; never add a new per-mode branch.
- Gate before each commit: `make lint` + full suite (`E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit`, exit code checked); stage explicit paths; deploy after the last task.
- Evals: report USD cost.

## Review Focus

1. A language-program chat still answers a quiz request with a ```` ```quiz ```` block (quiz XOR conversation) and evaluates "My quiz answers: ..." - full tools must not tempt it into an artifact. Test: Task 2 `test_language_instructions_reach_the_prompt`; Task 6 eval `language_quiz_block`.
2. A sports session start (`[System: session-start]`) still reads readiness via `garmin_connect` and writes progress with `kv_store` under `sports` / `<program_id>:` keys. Test: Task 3 `test_kv_store_uses_the_standing_namespace`; existing `evals/cases/sports_*.yaml` pass in Task 6.
3. `kv_store` is bound only in standing chats and writes to their namespace (`agent:<id>`, `sports`, `language`); an ordinary chat still has no `kv_store`. Test: Task 3 `test_kv_store_only_in_standing_chats`.
4. A program reset leaves no stale compaction summary or conversation facts. Test: Task 5 `test_reset_clears_compaction_and_facts`.
5. An agent chat with a pending approval still refuses new messages (409), while a Todoist delete typed in an agent chat no longer asks for an approval the turn cannot request. Test: Task 4 `test_pending_approval_still_blocks` / `test_no_unattended_gate_in_agent_chat`.

---

### Task 1: `StandingContext` - what a standing chat adds to a turn

**Files:**
- Create: `src/api/helpers/standing_context.py`
- Test: `tests/unit/test_standing_context.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) StandingContext: kind: Literal["agent", "sports", "language"]; name: str; instructions: str; data: str | None; kv_namespace: str; agent_id: str | None = None`
  - `load_standing_context(conv: Conversation, user: User) -> StandingContext | None` - None for ordinary chats and the planner.
- Sources (existing, keep): `resolve_agent_system_prompt(agent)` (agent instructions), `SPORTS_TRAINER_SYSTEM_PROMPT` / `LANGUAGE_TUTOR_SYSTEM_PROMPT` formatted with the real program name and id plus `PROGRAM_STATIC_PREAMBLE` (program instructions; `{kv_data_section}` filled with a pointer to the data section), `load_sports_context` / `load_language_context` + `format_sports_kv_data` / `format_language_kv_data` (data). Namespaces: `agent:<agent_id>`, `sports`, `language` (as `kv_store` uses today, `agent_kv.py:100-106`).

- [ ] **Step 1: Write the failing tests** (`test_database`, `test_user`):
  - `test_ordinary_chat_has_none` / `test_planner_has_none`
  - `test_agent_chat` - an agent with goals "Watch VWCE" → kind `agent`, `name` = agent name, `instructions` contains "Watch VWCE" and the agent's schedule, `kv_namespace == f"agent:{agent.id}"`, `agent_id` set
  - `test_system_briefing_uses_the_stock_prompt` - a `system_type="daily_briefing"` agent with NULL prompt → instructions = `resolve_agent_system_prompt` text
  - `test_sports_program` - a sports conversation with kv `cycling:goals` → kind `sports`, instructions contain the trainer text with the real program id (no `<program_id>` placeholder left), `data` contains the goals value, `kv_namespace == "sports"`
  - `test_language_program` - likewise, instructions contain the quiz-format rules (```` ```quiz ````)
- [ ] **Step 2: Run** `.venv/bin/python -m pytest -q -n0 tests/unit/test_standing_context.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `standing_context.py`. The agent instructions block names the agent, its schedule (described via `describe_cron` when cron-like, else raw) and says its scheduled reports appear in this chat.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(chat): a standing chat's instructions and context, loaded once`.

### Task 2: The prompt - one standing-chat section, no program cache profiles

**Files:**
- Modify: `src/agent/prompts.py` (`get_dynamic_prompt_parts`, `get_system_prompt`, `get_static_prompt_for_profile`, `_program_prompts`, `_conversation_parts`), `src/agent/prompt_programs.py`, `src/agent/context_cache.py` (`CacheProfile`), `src/agent/graph_cache.py` (`_MAX_CACHE_NAMES_PER_SIGNATURE` comment/value), `src/agent/prompt_texts/core.py` if a section template lives there
- Create: `src/agent/prompt_texts/standing.py` (`STANDING_CHAT_SECTION`)
- Test: `tests/unit/test_context_cache.py`, `tests/unit/test_prompts.py`, `tests/unit/test_prompt_snapshots.py` + fixtures

**Interfaces:**
- Consumes: Task 1 `StandingContext`.
- Produces: `get_dynamic_prompt_parts(..., standing: StandingContext | None = None)` and `get_system_prompt(..., standing: StandingContext | None = None)` render `STANDING_CHAT_SECTION` (name, instructions, data); the `is_sports` / `is_language` / `sports_context` / `language_context` parameters are removed; `CacheProfile` keeps STANDARD, ANONYMOUS, PLANNING.

- [ ] **Step 1: Write the failing tests:**
  - `test_standing_section_in_dynamic_parts` - `get_dynamic_prompt_parts(..., standing=StandingContext("agent", "VWCE Watcher", "Watch VWCE weekly", None, "agent:a1"))` contains "VWCE Watcher" and "Watch VWCE weekly"
  - `test_language_instructions_reach_the_prompt` - a language `StandingContext` from Task 1's loader → the dynamic parts contain the ```` ```quiz ```` format rules and the kv data
  - `test_standing_section_in_the_uncached_prompt` - same via `get_system_prompt`
  - `test_no_program_cache_profiles` - `{p.name for p in CacheProfile} == {"STANDARD", "ANONYMOUS", "PLANNING"}`
  - Replace the program-profile tests in `test_context_cache.py` (`:82-83`, `:122-148`, `:218-248`) and `test_prompts.py:74-90` with the above.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** Remove the SPORTS/LANGUAGE branches of `get_static_prompt_for_profile` and `_program_prompts`; `PROGRAM_STATIC_PREAMBLE` / `format_program_dynamic_context` become part of Task 1's instructions/data or go if unused. Keep the title-nudge suppression for programs (their titles are fixed) by deciding it from `standing.kind` in one place.
- [ ] **Step 4: Run** the prompt and cache tests → PASS; `make prompt-snapshots` and check the diff only drops `static-sports.txt` / `static-language.txt` and their sizes.
- [ ] **Step 5: Commit** `refactor(prompts): one standing-chat section instead of program profiles` (Ruling to ledger: program instructions move from the cached static prompt to the per-turn tail - about 3k uncached tokens per program turn, under $1/month at current volume - the price of removing two cache profiles).

### Task 3: ChatAgent and tools - full tools, freshness, facts for standing chats

**Files:**
- Modify: `src/agent/agent.py` (constructor, `_get_cache_profile`, `freshness_gate`, `_build_messages`, `chat_batch`, `stream_chat_events`), `src/agent/tools/__init__.py` (`get_tools_for_request`, remove `_SPORTS_EXCLUDED_TOOLS`, `_LANGUAGE_EXCLUDED_TOOLS`, the interactive agent permission branch; update `_ordinary_chat_tools` docstring), `src/agent/tools/agent_kv.py` (namespace from the standing context), `src/api/helpers/conversation_facts.py` (`facts_eligible`)
- Test: `tests/unit/test_tools.py`, `tests/unit/test_artifact_tools.py`, `tests/unit/test_deep_research_offer.py`, `tests/unit/test_schedule_tool.py`, `tests/unit/test_conversation_facts_tool.py`, `tests/unit/test_agent_setup.py`, `tests/unit/test_kv_store.py`

**Interfaces:**
- Consumes: Task 1, Task 2.
- Produces:
  - `ChatAgent(..., standing: StandingContext | None = None)`; `is_sports` / `sports_context` / `is_language` / `language_context` removed; `is_autonomous` + `agent_context` stay for runs only.
  - `get_tools_for_request(anonymous_mode=False, is_planning=False, standing=False)` - ordinary tools + `_ordinary_chat_tools` for every non-planner chat; `kv_store` added only when `standing`.
  - `set_standing_kv_namespace(namespace: str | None)` / `get_standing_kv_namespace()` in `agent_kv.py`; `kv_store` resolves its namespace from the run's agent context (runs) or this (standing chats), else refuses as today.
  - `facts_eligible` drops the agent / sports / language exclusions.

- [ ] **Step 1: Write the failing tests:**
  - `test_standing_chat_gets_the_full_chat_tools` - `get_tools_for_request(standing=True)` includes `schedule`, `record_conversation_facts`, `google_calendar`, `todoist`, `manage_memory`, `create_artifact`, `kv_store`
  - `test_kv_store_only_in_standing_chats` - `get_tools_for_request()` has no `kv_store`
  - `test_kv_store_uses_the_standing_namespace` - with `set_standing_kv_namespace("sports")`, `kv_store(action="set", key="cycling:goals", ...)` writes namespace `sports`
  - `test_freshness_gate_on_in_standing_chats` - a ChatAgent with `standing=...` and research bound has `freshness_gate` True
  - `test_standing_chat_uses_the_standard_cache_profile`
  - `test_facts_eligible_in_agent_and_program_chats`
  - Replace the pinned exclusions (`test_tools.py:115-175`, `test_artifact_tools.py:132-133`, `test_deep_research_offer.py:76-77`, `test_schedule_tool.py:448`, `test_conversation_facts_tool.py:84-101`, `test_agent_setup.py:37-66`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Grep every caller of the removed parameters (`grep -rn "is_sports\|is_language\|agent_tool_permissions\|sports_context\|language_context" src/ evals/ tests/`) and update them in this task, except `chat_turn.py` (Task 4) and `evals/run.py` / `tests/e2e_server/llm_fakes.py` (Task 6).
- [ ] **Step 4: Run** the changed tests and `tests/unit/test_graph.py` (autonomous tool node unchanged) → PASS.
- [ ] **Step 5: Commit** `refactor(agent): standing chats get the ordinary chat tools and checks`.

### Task 4: The turn - one path for every chat

**Files:**
- Modify: `src/api/helpers/chat_turn.py` (`TurnContext`, `apply`/`clear`, `create_agent`, `agent_call_kwargs`, prepare, remove `_attach_agent_context` and `is_autonomous`), `src/api/routes/costs.py` (compaction status for agent conversations), `src/api/helpers/stream_producer.py` / `chat_streaming.py` (remove the interactive approval branch only if it is unreachable - check `request_approval` is never bound in interactive turns)
- Test: `tests/integration/test_routes_chat_turn.py`, `tests/unit/test_chat_streaming_timeout.py`, `tests/integration/test_routes_chat.py` (facts cases)

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `TurnContext.standing: StandingContext | None`; `apply()` sets the standing kv namespace (Task 3) and clears it in `clear()`; every turn goes through `build_compacted_history`.

- [ ] **Step 1: Write the failing tests** (patch `ChatAgent` as the existing chat-turn tests do):
  - `test_agent_chat_runs_as_an_ordinary_turn` - batch in an agent conversation → ChatAgent built with `standing.kind == "agent"`, `is_autonomous` False, tools include `schedule`; `get_agent_context()` is None during `chat_batch`
  - `test_sports_chat_runs_as_an_ordinary_turn` - same for a sports conversation, `standing.kv_namespace == "sports"`
  - `test_agent_chat_history_is_compacted_like_any_chat` - long agent conversation → `build_compacted_history` called with its id
  - `test_pending_approval_still_blocks` - an agent with a pending approval → 409 (existing behavior, `chat_turn.py:185`)
  - `test_no_unattended_gate_in_agent_chat` - a todoist `delete` in an agent chat is not refused for a missing approval
  - `test_standing_context_cleared_after_a_failed_turn` (replaces `test_batch_clears_request_context_when_the_agent_raises`)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; update `test_chat_streaming_timeout.py:76-119` and the costs route.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q tests/unit tests/integration` → PASS.
- [ ] **Step 5: Commit** `refactor(chat): agent and program chats take the ordinary turn path`.

### Task 5: One compaction - agent runs and program resets

**Files:**
- Modify: `src/agent/executor.py` (`_run_history`, `_load_run_conversation`), `src/db/models/programs.py` (`reset_program_conversation`), `src/agent/compaction_segments.py` (take over `SUMMARY_FOCUS`, `SUMMARY_MESSAGE_MAX_CHARS`)
- Delete: `src/agent/compaction.py`, `tests/unit/test_agent_compaction.py`, `db.compact_agent_conversation` (`src/db/models/agent_conversation.py`) if nothing else uses it, `AGENT_COMPACTION_THRESHOLD` / `AGENT_COMPACTION_KEEP_RECENT` (config, `.env.example`, docs)
- Test: `tests/unit/test_executor.py`, `tests/unit/test_programs*.py` (or a new `tests/integration/test_program_reset.py`)

**Interfaces:**
- Produces: `_run_history(agent, conversation_id) -> list[dict]` = `[]` for fresh-context agents, else `build_compacted_history(agent.user_id, conversation_id, enrich_history(messages[:-1]))`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_history_uses_chat_compaction_and_keeps_messages` - a non-fresh agent with 60 messages: the run's history comes from `build_compacted_history`, and all 60 messages still exist afterwards
  - `test_fresh_context_run_has_no_history`
  - `test_reset_clears_compaction_and_facts` - a program conversation with `conv_compaction` kv state and conversation facts → after `reset_program_conversation` both are gone
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; remove the destructive path with its config and docs (`docs/architecture/conversation-context.md#autonomous-agent-compaction`).
- [ ] **Step 4: Run** the executor, program and compaction tests → PASS.
- [ ] **Step 5: Commit** `refactor(agents): one non-destructive compaction for runs and chats`.

### Task 6: Evals, e2e fake, UI chip, docs, gate, deploy

**Files:**
- Modify: `evals/run.py` (`mode: sports` builds a `StandingContext` instead of `is_sports`/`sports_context`), `tests/unit/test_eval_harness.py:688-689`, `tests/e2e_server/llm_fakes.py:228-247` (accept `standing`), `web/src/components/AgentConversationHeader.ts` and the program chat headers (the `conversation-schedules` chip, as in `ChatHeader.ts`), docs (`docs/architecture/conversation-context.md`, `docs/architecture/agent-graph.md`, `docs/features/agents.md`, `docs/features/language-learning.md`, `docs/features/freshness.md`, `docs/features/agent-tools.md`, `docs/features/artifacts.md`, `docs/features/conversation-facts.md`, `docs/README.md`), `TODO.md`
- Create: `evals/cases/language_quiz_block.yaml` (needs `mode: language` in the harness - add it alongside `sports`), `evals/cases/agent_chat_remind_me.yaml` (an agent chat: "remind me tomorrow at 9" → `schedule` preview)
- Test: `web/tests/e2e/` (schedule chip in an agent chat header; desktop + mobile)

- [ ] **Step 1: Harness + fake + chip** - tests first: `test_eval_harness` for the language mode; an E2E asserting the chip in an agent chat header on desktop and mobile.
- [ ] **Step 2: Evals** - `PYTHONPATH=. nice -n 10 .venv/bin/python evals/run.py --only sports_*,language_quiz_block,agent_chat_remind_me` twice → all pass (report USD cost).
- [ ] **Step 3: Docs + TODO**, removing every description of the per-mode tool trims, program cache profiles, interactive agent permissions and destructive agent compaction.
- [ ] **Step 4: Gate** - `make pre-commit` exit 0; count the removed branches (`git diff --stat` + `grep -c "is_sports\|is_language" src/` before/after) for the final message.
- [ ] **Step 5: Commit** `test(evals)/docs: standing chats phase 1`; push; deploy; health-check; then watch production for an hour: the next agent run and any agent or program chat turns log `Chat turn completed` / `Agent execution successful` without errors (no test messages are sent into family chats).
