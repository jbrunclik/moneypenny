# Conversation Facts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-conversation list of settled facts that the agent maintains, that is sent verbatim with every turn of that conversation (outside compaction), and that the user can see read-only.

**Architecture:** A `conversation_facts` table keyed by `(conversation_id, fact_key)`, each row remembering the assistant message that last set it (a trigger drops a message's facts when the message is deleted, so regenerate replaces them). The agent edits the list with an extract-only tool, `record_conversation_facts`, applied when the reply is saved - no extra model round. The list rides in the per-request `[CONTEXT]` block the same way the conversation title does. A header chip with a popup, modelled on `CompactionIndicator.ts`, shows it.

**Tech Stack:** Python 3.14 / Flask / LangGraph, SQLite (yoyo migrations), TypeScript + Vite frontend, Playwright E2E.

**Spec:** [docs/superpowers/specs/2026-10-25-thorough-turns-and-conversation-facts-design.md](../specs/2026-10-25-thorough-turns-and-conversation-facts-design.md) - Part 1. Parts 2-3 get their own plans, in the spec's order: sandbox files + PDF library, turn budgets, thorough turns, compaction threshold.

## Global Constraints

- Behind `CONVERSATION_FACTS_ENABLED` (default `false`); switched on only after the retention eval passes and ordinary turns are shown not slower or noticeably more expensive.
- No extra model round on ordinary turns.
- Ordinary chats only: not planner, sports, language, agent or anonymous conversations.
- Visible, read-only; the user changes a fact by saying so in chat. Desktop and mobile (768px breakpoint).
- Cap: holds ~30 short facts. `CONVERSATION_FACTS_MAX_COUNT=30`, `CONVERSATION_FACTS_MAX_FACT_CHARS=200`.
- No backfill: existing conversations start empty.
- Batch mode must match streaming. New env vars go to `src/config.py`, `.env.example` and the feature doc. The repo is public. Report eval cost.
- Timestamps: write with `to_db(..., "utc", conn)` (the DB stores fixed-width UTC since migration 0072).

## Decisions this plan makes (spec left them to the builder)

- **Storage:** a table, not kv_store - the per-row `message_id` and the delete trigger need it. Precedent: `artifact_versions_message_delete` in `migrations/0065_add_artifacts.py`.
- **Tool shape:** one extract-only tool, `record_conversation_facts(set: list[{key, text}], remove: list[str])`. Keys are short slugs the agent picks (`partition-walls`); setting an existing key replaces it. Extract-only means the turn ends without another round when the model also wrote text, and edits apply at save time with the saved assistant message id - which is exactly the "facts follow the reply" rule.
- **Cap signal:** an extract-only tool returns nothing the model reads, so the cap is signalled where the model does read: the facts block says `N/30` and, when full, "list full - replace or remove a fact before adding". Edits past the cap are dropped and logged.
- **Guidance:** when to use facts versus `manage_memory` lives in the dynamic facts block (present whenever the feature is on, even with an empty list), so the cached static prefix does not change with the flag.

## Review Focus

1. Regenerating a turn: the client deletes the reply, then reruns; the facts that reply set must be gone before the rerun's context is built (Task 1 trigger test, Task 3 route test).
2. A turn that calls the tool without text (tool-only message): the graph executes it and goes another round; edits must still apply once, from all of the turn's calls, last write per key winning (Task 2).
3. An oversized edit: a 31st fact or a 500-character fact must not be stored, and the next turn must see the list as full (Tasks 1, 2).
4. Permanent conversation delete and trash purge must not leave facts behind (Task 1).
5. Batch mode saves through the same path as streaming, so facts apply in both (Task 3 batch test).

---

### Task 1: Storage

**Files:**
- Create: `migrations/0073_add_conversation_facts.py` (check the highest number on `main` right before committing)
- Create: `src/db/models/conversation_facts.py` (mixin, registered on `Database` like the other `src/db/models/*` mixins)
- Modify: `src/db/models/dataclasses.py` (add `ConversationFact`), `src/config.py`, `.env.example`
- Test: `tests/unit/test_conversation_facts_db.py`

**Interfaces:**
- Produces: `ConversationFact(key: str, text: str, message_id: str, updated_at: datetime)`; `Database.get_conversation_facts(conv_id: str) -> list[ConversationFact]` (ordered by `updated_at`); `Database.apply_conversation_facts(conv_id: str, user_id: str, message_id: str, set_facts: list[tuple[str, str]], remove_keys: list[str]) -> FactsApplyResult` where `FactsApplyResult(applied: int, rejected: int)`; `Config.CONVERSATION_FACTS_ENABLED`, `Config.CONVERSATION_FACTS_MAX_COUNT = 30`, `Config.CONVERSATION_FACTS_MAX_FACT_CHARS = 200`.

Table: `conversation_facts(conversation_id TEXT NOT NULL, user_id TEXT NOT NULL, fact_key TEXT NOT NULL, text TEXT NOT NULL, message_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (conversation_id, fact_key))`, an index on `message_id`, and two triggers: `AFTER DELETE ON messages` (delete rows with that `message_id`) and `AFTER DELETE ON conversations` (delete the conversation's rows). Rollback drops all three.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_conversation_facts_db.py` with the `test_database`, `test_user` fixtures:
  - `test_set_replace_and_remove`: set `("walls", "All partitions are reinforced concrete except one brick wall")`, then set `("walls", "...brick wall in room 2141.5")` from a second message, then remove `"walls"` - after each, `get_conversation_facts` returns the expected list and `message_id` is the latest setter.
  - `test_deleting_the_setting_message_drops_its_facts`: facts from message A and B; `db.delete_message_by_id(A)` leaves only B's.
  - `test_deleting_the_conversation_drops_its_facts`: permanent delete leaves zero rows for it.
  - `test_cap_rejects_past_the_count_and_long_facts`: 30 stored, a 31st new key is rejected (`rejected == 1`), replacing an existing key still works; a 201-character text is rejected.
  - `test_keys_are_normalized`: `" Partition Walls "` stores as `partition-walls` (lowercase, spaces to `-`, max 40 chars).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_conversation_facts_db.py -q` - expect failures (no table/methods).
- [ ] **Step 3: Implement** the migration, the mixin and the dataclass; one transaction per `apply_conversation_facts` call (removes first, then sets; count checked against the post-remove total).
- [ ] **Step 4: Run** the test file - PASS. Then `make lint` (exit code checked).
- [ ] **Step 5: Commit** `feat(db): conversation facts table` with the explicit paths.

### Task 2: The tool and its extraction

**Files:**
- Modify: `src/agent/tools/metadata.py` (tool + `EXTRACT_ONLY_TOOL_NAMES`), `src/agent/tools/__init__.py` (bound only when `CONVERSATION_FACTS_ENABLED`), `src/agent/tool_display.py` (`TOOL_METADATA`, `extract_tool_detail`, and `_CONDITIONAL_TOOLS` since it is not always bound) - follow `/new-tool`'s checklist for the rest: prompt-enhancer list, `AgentEditor.ts` only if agents may use it - they may not), `src/agent/content.py`
- Test: `tests/unit/test_conversation_facts_tool.py`

**Interfaces:**
- Consumes: Task 1's `apply_conversation_facts`.
- Produces: `record_conversation_facts(set: list[FactEdit] | None = None, remove: list[str] | None = None) -> str` where `FactEdit` is a Pydantic model `{key: str, text: str}` (every parameter concretely typed - see the schema guard in `test_garmin_workout_tool.py::TestToolSchema`); `extract_fact_edits(messages: list[BaseMessage]) -> tuple[list[tuple[str, str]], list[str]]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_tool_schema_has_concrete_types` (the schema guard).
  - `test_extract_collects_every_call_last_write_wins`: two AIMessages each calling the tool, the second resetting key `walls` and removing `blinds` → `([("walls", second_text)], ["blinds"])`.
  - `test_a_key_set_then_removed_in_one_turn_is_removed`.
  - `test_extract_ignores_other_tools`.
  - `test_the_tool_is_extract_only`: `"record_conversation_facts" in EXTRACT_ONLY_TOOL_NAMES`.
  - `test_bound_only_when_enabled` (flag false → not in `get_tools_for_request()` names).
- [ ] **Step 2: Run** - expect failures.
- [ ] **Step 3: Implement.** The tool's docstring is the model's description: "Record facts the user has settled in THIS conversation (corrections, decisions, constraints, things already done, identifiers and results worked out here). Not for facts about the user in general - those go to manage_memory. Replace a fact by setting its key again; remove facts that no longer hold."
- [ ] **Step 4: Run** - PASS; `make lint`.
- [ ] **Step 5: Commit** `feat(agent): record_conversation_facts tool`.

### Task 3: Apply on save, inject every turn

**Files:**
- Modify: `src/api/helpers/chat_save.py` (apply after the reply is saved, next to `resolve_title_update`, in its own try/except - a facts failure never fails the save), `src/api/helpers/chat_turn.py` (`TurnContext.conversation_facts`, loaded in `build_turn_context` for eligible conversations, passed in `agent_call_kwargs`), `src/agent/agent.py` (`chat_batch`, `stream_chat_events`, `_build_messages` take `conversation_facts`), `src/agent/prompts.py` (`get_dynamic_prompt_parts` and `get_system_prompt`), `src/agent/prompt_texts/core.py` (`CONVERSATION_FACTS_PROMPT`)
- Test: `tests/unit/test_prompts.py` (extend), `tests/integration/test_routes_chat.py` (new class `TestConversationFacts`)

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `format_conversation_facts(facts: list[ConversationFact]) -> str` in `src/agent/prompts.py`; the block starts `# Conversation facts (N/30)`.

The block (copy fixed here): a heading with the count; "Facts settled in this conversation. They are in force: never contradict them; if a request conflicts with one, say so. Keep them current with record_conversation_facts (replace a fact by its key, remove what no longer holds). Facts about the user in general go to manage_memory instead."; then one `- key: text` line per fact, or "No facts recorded yet."; and, at the cap, "The list is full - replace or remove a fact before adding one."

- [ ] **Step 1: Write the failing tests:**
  - prompts: `test_facts_block_lists_facts_with_count`, `test_facts_block_says_full_at_the_cap`, `test_no_facts_block_when_disabled_or_not_eligible` (planner, sports, language, agent, anonymous).
  - integration, streaming: a mocked turn whose `result_messages` carry a `record_conversation_facts` call with text → after the turn, `get_conversation_facts` holds the fact with the saved assistant message id; the next turn's `stream_chat_events` kwargs carry it.
  - integration, batch: the same through `/chat/batch`.
  - integration, regenerate: delete the reply, `rerun_mode=regenerate` → the rerun's `conversation_facts` kwarg no longer holds that reply's fact.
- [ ] **Step 2: Run** - expect failures.
- [ ] **Step 3: Implement** (mirror how `conversation_title` flows through the same four functions).
- [ ] **Step 4: Run** the files, then `make lint` and `make test`.
- [ ] **Step 5: Commit** `feat(chat): conversation facts reach every turn`.

### Task 4: API endpoint

**Files:** follow `/new-endpoint`: `src/api/schemas/conversations.py` (`ConversationFactsResponse`), `src/api/routes/conversations.py` (`GET /api/conversations/<conv_id>/facts`), `make openapi && make types`, `web/src/api/conversations.ts` (`getFacts`), `tests/integration/test_routes_conversations.py`

**Interfaces:**
- Produces: response `{conversation_id: str, facts: [{key, text, updated_at}], max_count: int, enabled: bool}`; 404 for another user's conversation.

- [ ] **Step 1: Write the failing tests:** facts listed in order; another user's conversation 404; `enabled: false` with an empty list when the flag is off.
- [ ] **Step 2: Run** - expect failures. **Step 3: Implement.** **Step 4: Run** - PASS; `make lint`.
- [ ] **Step 5: Commit** `feat(api): conversation facts endpoint`.

### Task 5: Header chip and popup

**Files:**
- Create: `web/src/components/FactsIndicator.ts` (modelled on `CompactionIndicator.ts`: chip ids `conversation-facts` / `conversation-facts-mobile`, popup id `facts-popup`, event `facts:open`), styles in the stylesheet that holds the compaction chip (component-prefixed classes `facts-*`)
- Modify: `web/src/components/ChatHeader.ts` and the mobile header (chip elements, hidden by default), `web/src/core/toolbar.ts` (`updateConversationCost` also calls `updateFactsIndicator(convId)` - same moments: conversation load, end of each turn), `web/src/utils/icons.ts` (a pin icon)
- Test: `web/tests/unit/FactsIndicator.test.ts`, `web/tests/e2e/conversation-facts.spec.ts` (mock server: add `GET /api/conversations/<id>/facts` to `tests/e2e_server/`), `web/tests/visual/` (chip + popup, desktop and mobile)

**Interfaces:**
- Consumes: Task 4's `getFacts`.
- Produces: `updateFactsIndicator(convId: string | null): Promise<void>`.

Chip: pin icon + count, hidden when the list is empty or `enabled` is false. Popup: title "Conversation facts", the list (key in bold, text), and a footer line "To change a fact, tell Moneypenny in the chat." Read-only - no edit controls.

- [ ] **Step 1: Write the failing tests:** unit - hidden at 0 and when disabled, count shown, popup lists facts, a stale response for a previous conversation is ignored (the compaction indicator's `statusForOpenConversation` rule); E2E - chip appears after a turn that recorded a fact and opens the popup, on desktop and at 375px.
- [ ] **Step 2: Run** - expect failures. **Step 3: Implement.**
- [ ] **Step 4:** `make build`, then `E2E_PORT=8011 make test-fe-e2e`; visual baselines (`/regen-baselines` for Linux); screenshots checked for vertical rhythm on desktop and mobile.
- [ ] **Step 5: Commit** `feat(web): conversation facts chip and popup`.

### Task 6: Evals, docs, rollout check

**Files:**
- Modify: `evals/run.py` (a case may seed `conversation_facts: [{key, text}]`; the harness enables the flag for such cases), `evals/cases/facts_record_correction.yaml`, `evals/cases/facts_retention_after_topic_change.yaml`
- Create: `docs/features/conversation-facts.md` (link it from `docs/README.md`); update `docs/features/agent-tools.md` (tools table) and `TODO.md` (Thorough turns item: Part 1 done, next plan)

Eval cases:
- `facts_record_correction`: history where the assistant assumed drywall partitions; user: "Ne, všechny příčky jsou železobeton, kromě jedné cihlové zdi v pokoji 2141.5." → `required_tools: [record_conversation_facts]`; rubric: acknowledges and records it.
- `facts_retention_after_topic_change`: seeded facts (walls, "blackout blinds already installed"), 30+ history messages on another topic, then "Navrhni, kam dát nové zásuvky a co ještě koupit do ložnice." → rubric fails if it proposes drilling into the concrete partitions as if they were drywall or suggests buying blackout blinds.
- [ ] **Step 1:** add the harness support with a unit test in `tests/unit/test_eval_*.py` (seeded facts reach the turn).
- [ ] **Step 2:** run `PYTHONPATH=. .venv/bin/python evals/run.py --only 'facts_*'` three times; report pass rate and USD cost.
- [ ] **Step 3:** latency/cost check for the rollout: run the `fresh_*` and a handful of plain cases with the flag on and off; compare median duration and cost per case.
- [ ] **Step 4:** docs; `make lint`, `make test-all`.
- [ ] **Step 5: Commit** `docs: conversation facts` (+ the eval cases). Leave the flag off; flipping it on prod is a separate, reported step.
