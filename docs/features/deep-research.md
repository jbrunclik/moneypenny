# Deep Research

The agent offers a deep research run next to its quick answer when a question
needs several options compared or several current facts checked. Accepted,
parallel subagents research the sub-questions while sharing a board, a Pro model
writes a report, and the [grounding check](grounding.md) numbers its claims to
the pages the run read. A report can lead to another round.

Design: [deep research spec](../superpowers/specs/2026-10-03-deep-research-design.md).
Where the code and the spec differ, the code wins; the differences are noted
below.

## How the user meets it

- **The offer.** The main chat agent calls `propose_deep_research(question,
  context, sub_questions, run_now=false)`
  ([tools/deep_research.py](../../src/agent/tools/deep_research.py), description
  in [prompt_texts/deep_research.py](../../src/agent/prompt_texts/deep_research.py))
  together with a short normal answer. The tool has no side effects: when the
  reply is saved, `extract_offer()` ([offer.py](../../src/agent/deep_research/offer.py))
  reads the last call's arguments off the turn and `build_offer()` validates
  them and stores the offer on that assistant message. An invalid plan stores
  nothing. It is bound for ordinary chats only (including anonymous ones), never
  for planner, sports or language programs or agent conversations, and not
  inside subagents. The [product-research skill](../../src/agent/skills/product-research/SKILL.md)
  step 2 tells the agent to offer it for a real multi-product comparison
  instead of researching a long list itself.
- **The card** ([research-offer.ts](../../web/src/components/messages/research-offer.ts))
  under the answer (after the grounding footer): "Research this in depth?"
  (or "Research further?" for a follow-up offer), the estimate
  ("~7 min · ~12 Kč"), the editable context line (✎), the sub-questions as
  textareas with ✕, "+ Add a question or topic", **Start** and **No thanks**.
  The estimate is recomputed live by `estimateFrom()` from the `rates` stored on
  the offer (the same formula as [estimate.py](../../src/agent/deep_research/estimate.py);
  the spec's config endpoint is not used). Start is disabled outside 1 to
  `DEEP_RESEARCH_MAX_SUB_QUESTIONS` items; the client limits in
  [config.ts](../../web/src/config.ts) mirror the server defaults and the server
  enforces them. The currency label is hardcoded "Kč" (`cost_czk` is in
  `COST_CURRENCY`).
- **Start** ([core/deep-research.ts](../../web/src/core/deep-research.ts)
  `startDeepResearch()`) sends the user message "Start deep research" with
  `deep_research: {offer_message_id, sub_questions, context}` and a
  `deep_research` action, through `sendUiMessage()` (refused with a toast
  while a reply in the conversation is still running). The card collapses to
  "Deep research started"; if the send fails the editor comes back.
- **No thanks** calls `PATCH /api/messages/<id>/research-offer` with
  `{"status": "declined"}` (the spec's `/conversations/<c>/messages/<m>/...`
  path became this one); the card collapses to "Deep research declined".
  A superseded offer renders nothing.
- **Autostart.** For an explicit request ("prozkoumej to důkladně", "deep
  research") the agent sets `run_now`; the offer is stored with
  `autostart: true` and the card shows "Starting…" and sends Start itself.
  Only for a reply that just arrived (stream `done` or batch reply,
  `live: true`), never from history, so a second device opening the chat does
  not start a second run. It waits (`whenIdle`) until the offer turn is no
  longer the conversation's active request.
- **Rounds.** A finished report carries a follow-up offer (2-4 open questions,
  `kind: "followup"`, round + 1) with the same editor. Its subagents and writer
  get the previous report. No cap on rounds; one open offer per conversation
  (a new offer, or a report with a follow-up, marks older open ones
  `superseded`).
- **Progress and the chip.** See [Progress UI](#progress-ui).

## The pipeline

A turn whose request carries `deep_research` runs the pipeline instead of the
agent loop:

1. **Start** ([chat_turn.py](../../src/api/helpers/chat_turn.py)):
   `prepare_turn()` calls `start_plan()` ([plan.py](../../src/agent/deep_research/plan.py))
   before saving the user message, so an unrunnable plan leaves nothing
   behind: `PlanError` → 400, `OfferNotFound` → 404, `OfferConflict` (already
   started, declined or superseded) → 409. It validates the plan (1-8 items,
   `DEEP_RESEARCH_MAX_ITEM_CHARS`, `DEEP_RESEARCH_MAX_CONTEXT_CHARS`),
   recomputes the estimate, marks the offer `started` and returns a
   `DeepResearchPlan`. The batch endpoint rejects `deep_research` (400).
2. **Producer** ([stream_producer.py](../../src/api/helpers/stream_producer.py)):
   `_turn_events()` returns `run_deep_research(plan, recent_turns, request_id,
   finish_requested)` ([pipeline.py](../../src/agent/deep_research/pipeline.py))
   instead of `stream_chat_events()`. The pipeline yields progress events and
   ends with a normal `final` event, so saving, resume, Stop and push work
   unchanged. The orchestrator runs on its own thread; its events (from many
   subagent threads) are relayed in order through a queue.
3. **Briefs** ([briefs.py](../../src/agent/deep_research/briefs.py)): each
   subagent starts with no history, so its brief carries today's date, the
   question, the context, the last 4 turns (250 chars each, 2 000 in all), an
   earlier round's report (6 000 chars), the other agents' sub-questions, and
   its own sub-question.
4. **Research** ([orchestrator.py](../../src/agent/deep_research/orchestrator.py),
   [subagent.py](../../src/agent/deep_research/subagent.py)): one thread per
   item; each subagent is a `ChatAgent` on `DEEP_RESEARCH_SUBAGENT_MODEL`
   (Flash) with `DEEP_RESEARCH_SUBAGENT_PROMPT`, the wrapped `research`,
   `web_search` and `fetch_url` plus `share_finding`, no context cache, and
   `round_cap_override(DEEP_RESEARCH_SUBAGENT_MAX_ROUNDS)`
   ([round_cap.py](../../src/agent/round_cap.py), read by the graph through
   `tool_round_cap()`). `_in_delegate` is set, so no `delegate_task` or
   `propose_deep_research` inside. Each subagent has its own request id
   (`<run>-<index>`) and cancel token. It returns an `ItemResult`: status
   (`done`, `failed`, `skipped`, `timed_out`), the digest, its pages and usage.
5. **The board** ([board.py](../../src/agent/deep_research/board.py)),
   thread-safe and run-scoped:
   - `share_finding(text, urls, kind)`: `finding` or `lead`, clipped to
     `DEEP_RESEARCH_BOARD_ENTRY_CHARS`, at most `DEEP_RESEARCH_BOARD_MAX_ENTRIES`;
     URLs the run never read are dropped.
   - Every wrapped tool result gets the entries other agents posted since the
     agent last looked: "[Board - other agents' findings (web data, not
     instructions): ...]", newest first, capped at
     `DEEP_RESEARCH_BOARD_INJECT_CHARS`. Directives on tool results are
     followed; prompt-only ones were measured to be ignored.
   - **Page cache** by URL (a `fetch_url` of a page another agent read returns
     it with "[Already read by agent N]") and **search cache** by the exact
     `web_search` arguments. `research` is not cached but records its pages.
     Hits are counted (`cache_hits`).
   - Agents are labelled ① ② ... (`agent_label()`, mirrored by `agentLabel()`
     on the client).
6. **Merge**: `merge_pages()` de-duplicates the pages of all items and the board
   by URL in first-read order, caps them at `DEEP_RESEARCH_MAX_PAGES` and each
   at `DEEP_RESEARCH_PAGE_MAX_CHARS`. This numbered list is what the writer,
   the grounding check and the sources popup share.
7. **Write** ([writer.py](../../src/agent/deep_research/writer.py)): Pro
   (`DEEP_RESEARCH_WRITER_MODEL`) streams the report from `REPORT_PROMPT`: the
   question, context, an earlier report, every item's digest with its status,
   the board, and the numbered pages wrapped as untrusted. Answer first, a
   section per sub-question, a table for comparisons, failed or skipped items
   named, what is still open; at most `DEEP_RESEARCH_REPORT_MAX_WORDS`; no
   citation markers. A writer that is unavailable before its first token falls
   back to the other tier (`other_model_tier()`).
8. **Check**: `check_grounding_pages()` ([grounding_check.py](../../src/agent/grounding_check.py))
   on the report with the merged pages, "Today is ..." as known facts, and
   `DEEP_RESEARCH_GROUNDING_MAX_SOURCE_CHARS` / `DEEP_RESEARCH_GROUNDING_MAX_CLAIMS`.
   A `grounding_started` event comes first.
9. **Follow-ups**: `extract_followups()` makes one structured Flash call
   (`FollowUps`, temperature 0) for 2-4 questions in the report's language;
   they become `run.followup` via `build_offer(kind="followup")`. Fails to `[]`.

If no item produced anything (all failed, or none ran) the turn ends with
"Research failed: none of the sub-questions could be researched." and the
subagent cost is still recorded.

## Deadlines, Finish now and Stop

- **Per subagent**: after `DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS` its token is
  cancelled and it ends `timed_out`; the pages it put on the board are kept.
- **Cancellation is only checked between tool rounds**, so a subagent stuck
  inside one call (a hanging fetch, search retries) does not stop. After
  `DEEP_RESEARCH_CUT_GRACE_SECONDS` the orchestrator abandons it ("Deep research
  subagent stuck after its cut"), releases its slots, keeps its board pages and
  moves on; the thread finishes on its own. Before this an eval run waited the
  full 900 s for one blocked subagent.
- **Finish now**: the progress panel's button calls
  `POST /api/conversations/<id>/chat/finish-now` with `{message_id}` (the
  turn's assistant message id, same body as Stop). The route writes a kv flag
  (namespace `deep_research_finish`, value = message id; cross-worker like
  Stop) and the pipeline's relay loop polls `finish_now_requested()` every
  0.2 s. `Orchestrator.finish_now()` cuts running items and skips queued ones
  (`skipped`); the report is written from what was gathered and the run is
  marked `finished_early`. The producer clears the flag when the turn ends.
- **Stop**: the existing Stop cancels the parent token, whose callback calls
  `Orchestrator.stop()`. During research the turn ends with "Research stopped."
  and `stop_reason: "user"`, no report. During writing the writer stops between
  chunks and the partial report is saved with `stop_reason: "user"`.
- **Whole run**: `TurnContext.timeout_seconds` is
  `DEEP_RESEARCH_RUN_TIMEOUT_SECONDS` for a deep-research turn (else
  `CHAT_TIMEOUT`); it drives the producer deadline and the consumer backstop.
  The resume endpoint waits `max()` of both.
- A deploy mid-run ends the run like any running stream.

## Concurrency

- **Per run**: a `BoundedSemaphore(DEEP_RESEARCH_PARALLELISM)`; items beyond it
  queue.
- **Per worker**: a module-level semaphore of
  `DEEP_RESEARCH_MAX_CONCURRENT_SUBAGENTS` shared by all runs in one gunicorn
  worker process (two family members at once). An item that has to wait for it
  emits `research_item` with status `waiting` (the panel shows "◷ waiting").
  `reset_slots()` replaces it in tests.

## Storage

`messages.research` ([0059](../../migrations/0059_add_message_research.py),
nullable JSON), written by `save_message_to_db()` (`_research_for_turn()` in
[chat_save.py](../../src/api/helpers/chat_save.py)) and updated with
`db.set_message_research()`; `db.find_open_research_offers()` finds open
offers by `$.offer.status` or `$.run.followup.status`.

| Shape | On | Fields |
|---|---|---|
| `{"offer": {...}}` | The assistant message that offered | `question`, `context`, `sub_questions`, `estimate` (`minutes`, `cost_czk`), `rates`, `status` (`offered`, `started`, `declined`, `superseded`), `autostart`, `kind` (`initial`, `followup`), `round`, `created_at`; on a decision `decided_at`; on start `final_sub_questions`, `final_context`, `final_estimate` |
| `{"run": {...}}` | The report | `round`, `question`, `context`, `offered_sub_questions`, `sub_questions`, `items` (`status`, `pages`), `pages_read`, `board` (`agent`, `kind`, `text`, `urls`), `cache_hits`, `duration_ms`, `estimate`, `finished_early`, `followup` (an offer) |

The run does not store its cost (the spec's `cost_usd`): cost is in
`message_costs` and in the "Deep research run" log line. The report's
`messages.sources` are the merged pages (`usage_info["research_sources"]`), so
claim source `[2]` is popup entry 2. `research` is returned on loaded messages,
the batch response and the stream `done` event (`add_research()` in
[api/utils.py](../../src/api/utils.py)). Later turns see a report as clean text
plus a `research` key in its `MSG_CONTEXT` ("deep research round N: q1; q2",
[history.py](../../src/agent/history.py)).

`messages.action` ([0060](../../migrations/0060_add_message_action.py)): see
[Action messages](#action-messages).

## SSE events

| Event | Fields | When |
|---|---|---|
| `research_plan` | `items`, `minutes`, `started_at` (server epoch ms) | Run start |
| `research_item` | `index`, `status` (`waiting`, `started`, `done`, `failed`, `skipped`, `timed_out`), `pages` (on finish) | Item changes |
| `research_finding` | `agent`, `text` | A board post |
| `research_sources` | `count` | Research done, merged page count |
| `research_writing` | - | The writer starts |

Then `token`s, `grounding_started` and `done`. All five are in
`FORWARDED_EVENT_TYPES` ([chat_streaming.py](../../src/api/helpers/chat_streaming.py))
and `_JOURNALED_EVENT_TYPES` ([stream_resume.py](../../src/api/helpers/stream_resume.py)),
so a reload mid-run replays the panel. `minutes` and `started_at` were added
to `research_plan` (not in the spec) so the elapsed clock survives a journal
replay.

**Always streamed.** A multi-minute run cannot live in one batch request
(client timeout, proxies) and only the stream has resume and push.
`dispatchSend()` ([messaging.ts](../../web/src/core/messaging.ts)) uses the
stream for a message with `deepResearch` even with streaming off; the outbox
entry carries `deepResearch` and `action`, so a retry resends the plan.

## Progress UI

[research-progress.ts](../../web/src/components/messages/research-progress.ts)
keeps a `ResearchProgress` model on the `StreamingState`
(`applyResearchEvent()`, wired in [research-stream.ts](../../web/src/core/research-stream.ts)
from [stream-events.ts](../../web/src/core/stream-events.ts)), so a
conversation switch that re-creates the bubble loses nothing. The panel at the
top of the streaming bubble lists the items (spinner, "✓ N pages", "◷ waiting",
"✕ failed", "– skipped", "⏱ timed out"), the last 5 findings ("② ..."), and a
footer "Elapsed 2:31 of ~5 min" with **Finish now** ("Finishing…" once
pressed), or "Writing the report from N sources…". A one-second tick updates
the clock only. On `done`, `finishResearchMessage()` replaces the panel with
the header chip, a `<details>` "Deep research · 5 questions · 34 pages · 6 min"
(plus "· finished early"), expandable to the items and the board, and renders
the follow-up offer. Styles in
[research.css](../../web/src/styles/components/research.css).

## Cost

- **Writer**: the turn's own tokens. The usage carries `answer_model` (the
  writer, or its fallback); `save_message_to_db` prices with
  `model_fallback or answer_model or model`.
- **Subagents**: `usage_info["deep_research_usage"]`, one entry per item with
  its model, priced per model by `calculate_deep_research_cost()`
  ([api/utils.py](../../src/api/utils.py)) into `tool_llm_cost`.
- **Check**: `grounding_usage`, as for any [grounding check](grounding.md).
- **Not counted**: tokens of a subagent cut by a deadline, Finish now or Stop
  (its `chat_batch` raised), the follow-up extraction call (under $0.001), and
  everything when Stop ends the run during research (the final event carries
  no usage).
- **Estimate** (`estimate()`, never stated by the model): `minutes =
  ceil(BASE_MINUTES + waves * PER_WAVE_MINUTES)` with `waves = ceil(items /
  PARALLELISM)`; `cost_czk = BASE_USD + items * PER_ITEM_USD`, each converted
  to `COST_CURRENCY` (`estimate_rates()`) and rounded to the nearest unit. With
  the defaults 5 items are 7 min and $0.52. The server recomputes it on start.

**Push**: a report no connected client saw sends "Your research is ready"
(`push_title()` in stream_producer.py) with the report's first line; never
after Stop. See [Push Notifications](push-notifications.md).

## Action messages

A user message the app sends for the user is an action, stored in
`messages.action` and rendered as a row instead of a typed bubble. The content
stays the plain instruction the model sees.

| Type | Sent by | Content | Fields |
|---|---|---|---|
| `verify_claim` | Look it up on a [claim card](grounding.md) | "Look up and verify: <quote>" | `source_message_id`, `claim_index`, `quote` |
| `deep_research` | Start on an offer | "Start deep research" | `offer_message_id`, `items`, `minutes` |

- **Request**: `ChatRequest.action` (`MessageAction`, a discriminated union in
  [schemas/chat.py](../../src/api/schemas/chat.py)). The server builds the
  `deep_research` action from the started plan (`_action()` in chat_turn.py),
  overriding what the client sent, so items and minutes match the run.
  Loaded messages carry `action` (`add_action()`).
- **Action row** ([action-row.ts](../../web/src/components/messages/action-row.ts),
  from `render.ts`): "Looking up “quote”" / "Deep research started · 5
  questions · ~7 min", plus "from the answer above ↑" / "from the offer above
  ↑", shown only when the source message is loaded. The link scrolls to the
  claim (`claim--flash`) or the message (`message--flash`). Rows keep the
  `message user` classes plus `message--action`, so send state, Retry and
  Discard work unchanged.
- **Forward links** ([message-links.ts](../../web/src/core/message-links.ts)
  `findActionReply()`): the reply is the next assistant message after the
  latest action pointing at the source. The claim card shows "Looked up below
  ↓"; a started offer shows "Report below ↓" (on render, and via
  `refreshReportLinks()` when a live report arrives).
- **Migration 0060** converted earlier look-ups ("Dohledej a ověř: ..." and
  "Look up and verify: ...") into `verify_claim` actions, linked to the nearest
  earlier answer in the conversation whose annotation quote matches (markdown
  stripped); `source_message_id` and `claim_index` are null when none matches.
  The content stays as it was.

## Configuration

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `DEEP_RESEARCH_ENABLED` | `true` | Binds `propose_deep_research` (existing offers can still be started) |
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
| `DEEP_RESEARCH_EST_BASE_USD` | `0.12` | Estimate: writer + check |
| `DEEP_RESEARCH_EST_PER_ITEM_USD` | `0.08` | Estimate: one subagent |
| `DEEP_RESEARCH_EST_BASE_MINUTES` | `2` | Estimate: fixed time |
| `DEEP_RESEARCH_EST_PER_WAVE_MINUTES` | `2.5` | Estimate: one wave of parallel subagents |

Client constants in [config.ts](../../web/src/config.ts):
`DEEP_RESEARCH_MAX_SUB_QUESTIONS` (8), `DEEP_RESEARCH_MAX_ITEM_CHARS` (300),
`DEEP_RESEARCH_MAX_CONTEXT_CHARS` (600), mirroring the server defaults.

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

- **A new SSE event type must join `_JOURNALED_EVENT_TYPES` and the consumer's
  `FORWARDED_EVENT_TYPES`**, or it is dropped live or missing after a reload.
- **The resume `done` must carry the same decorations as the live one**:
  `stream_resume_events()` calls `add_grounding()` and `add_research()`. Before
  this a reload mid-run lost the claims, the chip and the follow-up offer
  (and resumed answers had lost their grounding all along).
- **Autostart must wait for the offer turn to be idle.** The turn carrying the
  offer is still the conversation's active request while its `done` is
  handled, so an immediate Start was refused.
- **Cancellation is only checked between tool rounds**, inside subagents as in
  chat turns. Anything that cuts subagents must not wait on their futures; hence
  the cut grace.
- **Contextvars do not cross threads**: the orchestrator, item threads and
  relay run under `contextvars.copy_context()`, and each subagent sets its own
  request id.
- **Digests can carry specifics no page backs**: a sub-question finished
  `done` with 0 pages read yet its digest had 8 price ranges, all marked
  unsourced. Open in [TODO.md](../../TODO.md).
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

## See Also

- [Grounding Check](grounding.md) - claim annotations, the claim card
- [Chat and Streaming](chat-and-streaming.md) - stream turn, Stop, resume
- [Agent Tools](agent-tools.md) - `propose_deep_research`, skills
- [Cost Tracking](cost-tracking.md) - message costs
- [Evals](../testing/evals.md) - running and authoring cases
