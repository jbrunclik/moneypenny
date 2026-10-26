# Deep Research Storage, Events and Actions

What a [deep research](deep-research.md) run stores, the events it streams, and
the action messages it shares with the claim look-up.

## Storage

`messages.research` ([0059](../../migrations/0059_add_message_research.py),
nullable JSON), written by `save_message_to_db()` (`_research_for_turn()` in
[chat_save.py](../../src/api/helpers/chat_save.py)) and updated with
`db.set_message_research()`; `db.find_open_research_offers()` finds open
offers by `$.offer.status` or `$.run.followup.status`.

| Shape | On | Fields |
|---|---|---|
| `{"offer": {...}}` | The assistant message that offered | `question`, `context`, `sub_questions`, `estimate` (`minutes`, `cost_czk`), `rates`, `status` (`offered`, `started`, `declined`, `superseded`), `autostart`, `kind` (`initial`, `followup`), `round`, `created_at`; on a decision `decided_at`; on start `final_sub_questions`, `final_context`, `final_estimate` |
| `{"run": {...}}` | The report | `round`, `question`, `context`, `offered_sub_questions`, `sub_questions`, `items` (`status`, `pages`), `pages_read`, `board` (`agent`, `kind`, `text`, `urls`), `cache_hits`, `duration_ms`, `estimate`, `finished_early`, `followup` (an offer), `cost_usd` |

`run.cost_usd` is written after the message is priced (`save_message_to_db()`
updates the research once more); the cost is also in `message_costs` and the
"Deep research run" log line. The report's
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
| `research_tick` | - | Liveness: no other event for `TICK_SECONDS` (60) during research; the client ignores it |

Then `token`s, `grounding_started` and `done`. All six are in
`FORWARDED_EVENT_TYPES` ([chat_streaming.py](../../src/api/helpers/chat_streaming.py))
and `JOURNALED_EVENT_TYPES` ([stream_resume.py](../../src/api/helpers/stream_resume.py)),
so a reload mid-run replays the panel. `minutes` and `started_at` were added
to `research_plan` (not in the spec) so the elapsed clock survives a journal
replay.

**Always streamed.** A multi-minute run cannot live in one batch request
(client timeout, proxies) and only the stream has resume and push.
`dispatchSend()` ([messaging.ts](../../web/src/core/messaging.ts)) uses the
stream for a message with `deepResearch` even with streaming off; the outbox
entry carries `deepResearch` and `action`, so a retry resends the plan.

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
- **Forward links** ([message-links.ts](../../web/src/components/messages/message-links.ts)
  `findActionReply()`): the reply is the next assistant message after the
  latest action pointing at the source. The claim card shows "Looked up below
  ↓"; a started offer shows "Report below ↓" (on render, and via
  `refreshReportLinks()` when a live report arrives).
- **Migration 0060** converted earlier look-ups ("Dohledej a ověř: ..." and
  "Look up and verify: ...") into `verify_claim` actions, linked to the nearest
  earlier answer in the conversation whose annotation quote matches (markdown
  stripped); `source_message_id` and `claim_index` are null when none matches.
  The content stays as it was.
