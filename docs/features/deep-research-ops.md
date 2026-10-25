# Deep Research Cost and Operations

Cost, configuration, telemetry, evals and pitfalls of
[deep research](deep-research.md).

## Cost

- **Writer**: the turn's own tokens. The usage carries `answer_model` (the
  writer, or its fallback); `save_message_to_db` prices with
  `model_fallback or answer_model or model`.
- **Subagents**: `usage_info["deep_research_usage"]`, one entry per started
  subagent (`Orchestrator.spent()`), priced per model by
  `calculate_deep_research_cost()` ([utils/costs.py](../../src/utils/costs.py))
  into `tool_llm_cost`. Every model call feeds a per-subagent usage sink as it
  happens (`collecting_model_usage` in [turn_usage.py](../../src/agent/turn_usage.py),
  fed by `graph._invoke_model`), so subagents cut by a deadline, Finish now or
  Stop, failed or abandoned ones are priced too - also when Stop ends the run.
- **Check**: `grounding_usage`, as for any [grounding check](grounding.md).
- **Follow-ups**: the extraction call's usage joins `deep_research_usage` at
  `DEEP_RESEARCH_SUBAGENT_MODEL`.
- **Estimate** (`estimate()`, never stated by the model): `minutes =
  ceil(BASE_MINUTES + waves * PER_WAVE_MINUTES)` with `waves = ceil(items /
  PARALLELISM)`; `cost_czk = BASE_USD + items * PER_ITEM_USD`, each converted
  to `COST_CURRENCY` (`estimate_rates()`) and rounded to the nearest unit. With
  the defaults 5 items are 7 min and $0.52. The server recomputes it on start.

**Push**: a report no connected client saw sends "Your research is ready"
(`push_title()` in stream_producer.py) with the report's first line; a run
that found nothing (`research_failed` in the usage) sends "Your research
could not finish"; never after Stop. See [Push Notifications](push-notifications.md).

## Configuration

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `DEEP_RESEARCH_ENABLED` | `true` | Binds `propose_deep_research`; when off, starting an existing offer is refused (400 "Deep research is turned off"), though its card still shows |
| `DEEP_RESEARCH_WRITER_MODEL` | `gemini-3.1-pro-preview` | Report writer |
| `DEEP_RESEARCH_SUBAGENT_MODEL` | `DEFAULT_MODEL` | Subagents and follow-up extraction |
| `DEEP_RESEARCH_PARALLELISM` | `4` | Subagents at once per run; also the estimate's wave size |
| `DEEP_RESEARCH_MAX_SUB_QUESTIONS` | `8` | Plan size limit |
| `DEEP_RESEARCH_MAX_ITEM_CHARS` | `300` | Per sub-question |
| `DEEP_RESEARCH_MAX_CONTEXT_CHARS` | `600` | Context paragraph |
| `DEEP_RESEARCH_SUBAGENT_MAX_ROUNDS` | `4` | Tool rounds per subagent |
| `DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS` | `180` | Per-subagent deadline |
| `DEEP_RESEARCH_CUT_GRACE_SECONDS` | `10` | Wait for a cut subagent before abandoning it |
| `DEEP_RESEARCH_RUN_TIMEOUT_SECONDS` | `900` | Whole turn (producer, consumer, resume, eval case) |
| `DEEP_RESEARCH_MAX_CONCURRENT_SUBAGENTS` | `8` | Subagents at once per worker, across runs |
| `DEEP_RESEARCH_MAX_PAGES` | `40` | Merged pages |
| `DEEP_RESEARCH_PAGE_MAX_CHARS` | `6000` | Per merged page |
| `DEEP_RESEARCH_BOARD_MAX_ENTRIES` | `40` | Board size |
| `DEEP_RESEARCH_BOARD_ENTRY_CHARS` | `300` | Per board entry |
| `DEEP_RESEARCH_BOARD_INJECT_CHARS` | `2000` | Board block per tool result |
| `DEEP_RESEARCH_REPORT_MAX_WORDS` | `1500` | Report length (in the prompt) |
| `DEEP_RESEARCH_GROUNDING_MAX_SOURCE_CHARS` | `200000` | Check source text |
| `DEEP_RESEARCH_GROUNDING_MAX_CLAIMS` | `40` | Check annotations |
| `DEEP_RESEARCH_GROUNDING_TIMEOUT_SECONDS` | `45` | Check timeout (a chat turn's is `GROUNDING_CHECK_TIMEOUT_SECONDS`, 10) |
| `DEEP_RESEARCH_EST_BASE_USD` | `0.12` | Estimate: writer + check |
| `DEEP_RESEARCH_EST_PER_ITEM_USD` | `0.08` | Estimate: one subagent |
| `DEEP_RESEARCH_EST_BASE_MINUTES` | `2` | Estimate: fixed time |
| `DEEP_RESEARCH_EST_PER_WAVE_MINUTES` | `2.5` | Estimate: one wave of parallel subagents |

Client constants in [config.ts](../../web/src/config.ts):
`DEEP_RESEARCH_MAX_SUB_QUESTIONS` (8), `DEEP_RESEARCH_MAX_ITEM_CHARS` (300),
`DEEP_RESEARCH_MAX_CONTEXT_CHARS` (600), mirroring the server defaults, and
`DEEP_RESEARCH_AUTOSTART_SECONDS` (8), the autostart countdown.

## Telemetry

One line per decision, for the two-week review together with
`messages.research` (an ignored offer is not logged: it stays `offered`).

| Log line | Where | Fields |
|---|---|---|
| `Deep research offered` | chat_save.py | `user_id`, `conversation_id`, `sub_questions`, `estimate`, `kind`, `autostart` |
| `Deep research started` | plan.py | `conversation_id`, `offer_message_id`, `kind`, `items`, `added`, `removed`, `context_edited`, `decision_seconds`, `estimate` |
| `Deep research declined` | plan.py | `conversation_id`, `offer_message_id`, `kind`, `sub_questions`, `decision_seconds` |
| `Deep research superseded` | chat_save.py | `conversation_id`, `offer_message_id`, `kind`, `seconds_open` |
| `Deep research run` | chat_save.py (after pricing) | `message_id`, `round`, `items`, `failed`, `timed_out`, `skipped`, `pages_read`, `board_entries`, `cache_hits`, `duration_ms`, `finished_early`, `cost_usd`, `cost_czk`, `estimate` |

`added` / `removed` are set differences, so an item edited in place counts as
one of each. Warnings: "Deep research subagent failed", "Deep research
subagent stuck after its cut", "Deep research writer unavailable, falling
back", "Deep research follow-up extraction failed"; info "Deep research
finish-now requested".

## Evals

Three cases in [evals/cases/](../../evals/cases/) (see [Evals](../testing/evals.md)):

- `deep_research_offer_precision`: "Kolik je hodin v Tokiu?" gets a direct
  answer, `forbidden_tools: [propose_deep_research]`.
- `deep_research_offer_recall`: a headphone purchase under 7 000 Kč gets an
  answer and `required_tools: [propose_deep_research]`.
- `deep_research_end_to_end`: a case-level `deep_research:` block
  (`question`, `context`, `sub_questions`) makes `run_deep_research_turn()` in
  [run.py](../../evals/run.py) run the real pipeline on that fixed plan instead
  of a chat turn. The judge sees the merged pages as cited sources;
  `turn_cost()` prices the writer at `answer_model` plus the subagents and the
  check; `case_timeout()` gives it `DEEP_RESEARCH_RUN_TIMEOUT_SECONDS`. A case
  that times out or crashes is listed as unpriced instead of counting as $0.

```bash
.venv/bin/python evals/run.py --only 'deep_research_*'
```

Cost: the offer cases are ordinary chat turns ($0.01-0.11 each); the
end-to-end case is one real run, measured at $0.41-0.47 including the judge
(Oct 3 2026, about 2-3 minutes). Always report the USD cost the harness
prints. Baseline (Oct 3 2026): precision 4/4,
recall 4/6, end-to-end failing (see TODO).

## Pitfalls

- **Subagent graphs must not be memoized** (`ChatAgent(memoize_graph=False)`).
  The compiled-graph cache is keyed by tool names, and the subagents' tools are
  this run's board closures with the same names every run. Until Oct 11 2026
  every later run in a worker reused the first run's graphs: its pages and
  findings went to the first run's board (`pages_read 0`, `board_entries 0`,
  the verifier saw almost nothing and flagged most claims), and the board
  digest a subagent was shown could carry another run's (another user's)
  findings.
- **Shop pages lose their prices in main-content extraction.** `fetch_url`
  prepends the page markup's product line (JSON-LD `Product`/`Offer`, price
  meta tags; [product_data.py](../../src/agent/tools/product_data.py)) so the
  price survives extraction and every length cap.

- **A new SSE event type must join `_JOURNALED_EVENT_TYPES` and the consumer's
  `FORWARDED_EVENT_TYPES`**, or it is dropped live or missing after a reload.
- **The resume `done` must carry the same decorations as the live one**:
  `stream_resume_events()` calls `add_grounding()` and `add_research()`. Before
  this a reload mid-run lost the claims, the chip and the follow-up offer
  (and resumed answers had lost their grounding all along).
- **Autostart must wait for the offer turn to be idle.** The turn carrying the
  offer is still the conversation's active request while its `done` is
  handled, so an immediate Start was refused. Conversely, the offer turn's
  late stream cleanup must not tear down the started run's state (see
  [Concurrent Request Handling](chat-and-streaming.md#concurrent-request-handling)).
- **Never autostart on the model's word alone**: `run_now` is gated by
  `asks_for_deep_research()` on the user's message, and even then the user
  sees the plan for the countdown.
- **Cancellation is only checked between tool rounds**, inside subagents as in
  chat turns. Anything that cuts subagents must not wait on their futures; hence
  the cut grace.
- **Contextvars do not cross threads**: the orchestrator, item threads and
  relay run under `contextvars.copy_context()`, and each subagent sets its own
  request id.
- **Digests can carry specifics no page backs**: subagents put prices seen
  only in search snippets into digests (12 of 21 claims unsourced in one
  production report). Hence the `_note` on search results and the withheld
  page-less digests; one measured run went to 2 of 12 unsourced (was 4 of 7).
- **Keep JSON tool results JSON**: anything added to a `research` or
  `web_search` result (the board, the snippets note) goes in a field, or
  `turn_pages` can no longer parse it and the pages are lost.
- **The offer tool steers by its result**: "Offer recorded. Now give your
  brief answer"; offer recall rose only when the product-research skill told
  the agent to offer instead of researching itself.

Tests: [test_deep_research_estimate.py](../../tests/unit/test_deep_research_estimate.py),
[test_deep_research_offer.py](../../tests/unit/test_deep_research_offer.py),
[test_deep_research_board.py](../../tests/unit/test_deep_research_board.py),
[test_deep_research_orchestrator.py](../../tests/unit/test_deep_research_orchestrator.py),
[test_deep_research_writer.py](../../tests/unit/test_deep_research_writer.py),
[test_deep_research_pipeline.py](../../tests/unit/test_deep_research_pipeline.py),
[test_deep_research_save.py](../../tests/unit/test_deep_research_save.py),
[test_deep_research_wiring.py](../../tests/unit/test_deep_research_wiring.py),
[test_round_cap.py](../../tests/unit/test_round_cap.py),
[test_message_research_storage.py](../../tests/unit/test_message_research_storage.py),
[test_migration_message_action.py](../../tests/unit/test_migration_message_action.py),
[test_deep_research_start.py](../../tests/integration/test_deep_research_start.py),
[test_deep_research_stream.py](../../tests/integration/test_deep_research_stream.py),
[test_message_actions.py](../../tests/integration/test_message_actions.py),
[research-offer.test.ts](../../web/tests/component/research-offer.test.ts),
[research-progress.test.ts](../../web/tests/component/research-progress.test.ts),
[action-row.test.ts](../../web/tests/component/action-row.test.ts),
[deep-research-send.test.ts](../../web/tests/unit/deep-research-send.test.ts),
[message-links.test.ts](../../web/tests/unit/message-links.test.ts),
[deep-research.spec.ts](../../web/tests/e2e/deep-research.spec.ts) (canned
pipeline via the E2E server's `/test/set-deep-research`),
[deep-research.visual.ts](../../web/tests/visual/deep-research.visual.ts).
