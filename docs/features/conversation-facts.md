# Conversation Facts

A short list of facts the user has settled in one conversation - corrections,
decisions, constraints, things already done, identifiers and results worked
out there - kept by the agent and sent with every turn of that conversation.
Part 1 of the [thorough turns design](../superpowers/specs/2026-10-25-thorough-turns-and-conversation-facts-design.md);
plan: [2026-11-01-conversation-facts.md](../superpowers/plans/2026-11-01-conversation-facts.md).

Behind `CONVERSATION_FACTS_ENABLED` (default `false`); switched on in
production on Nov 1 2026 (see the rollout status below).

## Why

Oct 2026: in a ~50-message chat the user corrected Moneypenny ("all
partitions are reinforced concrete except one brick wall", "the blinds are
already installed"), and a few turns later she proposed things that
contradicted it. Compaction had squeezed each correction into a line of a
250-word segment, and the model had saved them to the user's *global*
memory, where nothing tied them to this conversation.

## How it works

- **Storage** - `conversation_facts` (migration 0073): one row per
  `(conversation_id, fact_key)` with the assistant message that last set it.
  Triggers drop a reply's facts when the reply is deleted (regenerate deletes
  it first, so the rerun records its own) and a conversation's with it.
  `src/db/models/conversation_facts.py`.
- **Recording** - `record_conversation_facts(set=[{key, text}], remove=[key])`,
  an extract-only tool (`src/agent/tools/metadata.py`): when the model also
  wrote text the turn ends without another round. The turn's edits
  (`extract_fact_edits`, last write per key wins) are applied when the reply
  is saved, with the saved reply's id (`record_turn_facts` in
  `src/api/helpers/conversation_facts.py`), in batch and streaming alike. A
  reply that is never saved records nothing.
- **Context** - ordinary chats get a `# Conversation facts (N/30)` block in the
  per-request dynamic context (`format_conversation_facts` in
  `src/agent/prompts.py`), outside compaction, so a summary can never squeeze
  it. The block also says when to use the tool versus `manage_memory`, so the
  cached static prefix does not change with the flag.
- **Caps** - 30 facts (`CONVERSATION_FACTS_MAX_COUNT`), 200 characters each
  (`CONVERSATION_FACTS_MAX_FACT_CHARS`), keys are lowercase slugs of up to 40
  characters. An extract-only tool returns nothing the model reads, so the
  count cap is signalled in the block: at 30 it says the list is full, and a
  new key past it is dropped (logged as "Conversation facts rejected at the
  caps"). A longer fact is clipped at a word with `…`, never dropped - a
  silently dropped fact left the agent believing it was recorded (review of
  Nov 1 2026).
- **Scope** - every non-anonymous chat but the planner: ordinary chats and
  standing chats (agent, sports and language conversations) alike
  (`facts_eligible()` in `src/api/helpers/conversation_facts.py`). Agent
  runs never record facts. The tool is bound only where facts are kept
  (`_ordinary_chat_tools` in `src/agent/tools/__init__.py`, next to
  `propose_deep_research`): bound elsewhere it would answer "recorded" while
  its edits were discarded.
- **UI** - a header chip with the count (desktop chat header and mobile
  header, hidden at 0) opens a read-only popup
  (`web/src/components/FactsIndicator.ts`, `GET /api/conversations/<id>/facts`).
  To change a fact the user says so in the chat. Refreshed with the cost and
  compaction chips (conversation load, end of each turn).

## Configuration

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `CONVERSATION_FACTS_ENABLED` | `false` | Feature switch |
| `CONVERSATION_FACTS_MAX_COUNT` | `30` | Facts per conversation |
| `CONVERSATION_FACTS_MAX_FACT_CHARS` | `200` | Characters per fact |

## Testing

- Unit: `tests/unit/test_conversation_facts_db.py` (storage, triggers, caps,
  keys), `tests/unit/test_conversation_facts_tool.py` (schema, extraction,
  binding), `tests/unit/test_prompts.py::TestConversationFacts`.
- Integration: `tests/integration/test_routes_chat.py::TestConversationFacts`
  (batch, streaming, regenerate, disabled, anonymous),
  `tests/integration/test_routes_conversations.py::TestConversationFacts`.
- Frontend: `web/tests/unit/facts-indicator.test.ts`,
  `web/tests/e2e/conversation-facts.spec.ts` (the E2E server enables the flag;
  `/test/seed` takes `facts: [{key, text}]`), visual baselines in
  `web/tests/visual/popups.visual.ts`.
- Evals: `facts_record_correction`, `facts_retention_after_topic_change` (a
  case opts in with `conversation_facts: [{key, text}]`; running the whole
  eval with `CONVERSATION_FACTS_ENABLED=true` gives every case the empty
  block, for the rollout cost/latency check).

## Rollout status (Nov 1 2026)

- `facts_record_correction` 3/3: the correction is recorded with the tool.
- `facts_retention_after_topic_change` 3/3 - **but a control without the
  facts list also passed 3/3**: with a single-topic detour, compaction's
  summary keeps the corrections. The case does not yet show the feature
  helps. The production failure mixed several topics and many corrections in
  one chat; a harder case built like that must fail without facts before
  the flag is flipped.
- Five plain cases, flag on vs off, two runs each: same pass results
  (`artifact_not_for_text_edit` failed in all four runs, unrelated) and the
  same cost ($0.09-0.10 per run). Wall time was noisier than the difference
  it could show (one 32 s outlier with the flag on); measure a larger sample
  before the flip.
- Eval spend for these runs: $0.69 (including the control).
- Same day, two harder tests (another $1.10):
  - `facts_retention_mixed_topics` - three corrections given in passing
    inside other topics, ~5,500 words of dense mixed-topic history past
    compaction: 3/3 with facts, but also 3/3 without them - the agent digs
    the corrections out with `search_conversations` (3-5 rounds, 43-55 s,
    $0.07-0.09 per run), while with facts 2 of 3 runs needed no tool (26-35 s,
    $0.05).
  - The Oct 25 production chat that motivated the feature, replayed locally
    up to the failing turn (the reply that called the planned Wi-Fi access
    points excessive despite the thick reinforced-concrete walls; not
    committed - the repo is public): today's agent got it right 3/3 without
    facts and 3/3 with them.
  - So no reproducible failure is fixed by the list today: compaction plus
    search recovery cover the cases tried. What it measurably buys is fewer
    search rounds on long chats, and the visible list.
- Switched on in production for its efficiency and visibility after a timing
  sample: 15 plain cases, 3 runs with the flag off and 3 on, interleaved -
  median per-case latency +4% (within run-to-run noise), cost $0.023 per case
  either way, 43 vs 42 of 45 passed (unrelated content misses), and no case
  recorded a fact in a chat where nothing was settled. Sample spend $2.09.
- Measure around Nov 15 2026 from the logs ("Conversation facts recorded")
  and the table: share of chats with facts, facts per chat, whether they read
  as settled facts or chatter, search rounds on long chats, plain-turn
  latency. Turn it off and remove it if the lists are noise.
