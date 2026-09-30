# Chat and Streaming

How a chat turn runs end to end: request setup shared by batch and streaming, the SSE pipeline and its recovery paths (placeholder, resume, outbox), and the frontend send / re-run flows. The agent loop itself is in [Agent Graph](../architecture/agent-graph.md), what it sees of the past in [Conversation Context](../architecture/conversation-context.md), and the thinking trace and source chips in [Thinking Indicator and Source Chips](thinking-and-sources.md).

## Gemini API Integration

### Models
Defined in `Config.MODELS` in [config.py](../../src/config.py) (a fast default and an
advanced reasoning model; `DEFAULT_MODEL` picks the default). Each entry may set
`thinking_level` for Gemini native reasoning.

### Response Format
Gemini may return content in various formats:
- String: `"response text"`
- List: `[{'type': 'text', 'text': '...', 'extras': {...}}]`
- Dict: `{'type': 'text', 'text': '...'}`

Use `extract_text_content()` in [content.py](../../src/agent/content.py) to normalize.

### Parameters
- `thinking_level`: Controls reasoning (minimal/low/medium/high)
- Temperature: Keep at 1.0 (Gemini 3 default)

## Chat Turn Lifecycle

Chat endpoints ([routes/chat.py](../../src/api/routes/chat.py), all under `/api`):

| Endpoint | Purpose |
|----------|---------|
| `POST /conversations/<id>/chat/batch` | One request, one complete reply |
| `POST /conversations/<id>/chat/stream` | Same turn over SSE |
| `POST /conversations/<id>/chat/interject` | Mid-run steering: guidance for the turn that is running (see [Agent Graph](../architecture/agent-graph.md#self-correction-node)) |
| `GET /conversations/<id>/chat/stream/<message_id>/resume?after_seq=N` | Replay + tail an in-flight stream ([Resumable Streams](#resumable-streams)) |

Both chat modes share one turn setup in [chat_turn.py](../../src/api/helpers/chat_turn.py).
They used to carry separate copies that drifted (batch built agent goals without
`resolve_agent_system_prompt()`, never cleared contextvars when the turn raised, and the
streaming producer re-set a hand-picked subset of them):

1. **`prepare_turn(user, data, conv_id)`** → `PreparedTurn`: loads the conversation,
   ORs the persisted and requested anonymous-mode flags, validates files, dedupes
   `client_message_id` (409 on a repeat), saves the user message (or, for a re-run,
   resolves the anchor message - no new row), clears any stale interjection, and builds
   the enriched history.
2. **`build_turn_context(user, turn, request_id)`** → `TurnContext`: planner dashboard,
   sports/language program context, interactive-agent context, and the compacted history
   ([Conversation Context](../architecture/conversation-context.md)).
3. **`TurnContext.apply()` / `clear()`** own **every** per-turn contextvar (request id,
   message files, conversation, location, planner dashboard, agent context, sports /
   language program). Contextvars do not cross threads, so the streaming producer calls
   `apply()` again in its own thread. A new contextvar a tool reads must be added to
   both methods - see [Agent Tools](agent-tools.md#three-layers-decide-tool-availability).
4. `create_agent()` + `agent_call_kwargs()` build the `ChatAgent` and its arguments.

**Batch** (`chat_batch`): `apply()` → `ChatAgent.chat_batch()` → `save_message_to_db()`
([chat_save.py](../../src/api/helpers/chat_save.py)) → `build_chat_response()` →
`clear()` in `finally`.

**Streaming** (`chat_stream`): `create_stream_generator(user, turn, ctx)` returns the SSE
generator. The work is split three ways:

| Module | Role |
|--------|------|
| [stream_producer.py](../../src/api/helpers/stream_producer.py) | `stream_events()` runs the agent in a background thread (`turn.apply()`, then `stream_chat_events()`), journals and queues events; `cleanup_and_save()` saves the turn when the client-facing generator could not |
| [chat_streaming.py](../../src/api/helpers/chat_streaming.py) | Consumer: `_StreamContext`, the `user_message_saved` event + placeholder, queue relay with keepalives, timeout and error handling |
| [stream_finalize.py](../../src/api/helpers/stream_finalize.py) | `_finalize_stream()` saves the turn and sends `done`; `_finalize_approval_stream()` for agent turns paused for approval |

Both paths put `stopped_early` on the reply when the turn hit the tool-round cap
([Stopped-Early Replies](../architecture/agent-graph.md#stopped-early-replies)).


## Streaming Architecture

### Stop Streaming

Clicking the stop button ends the turn **on the server** within about a second, keeps the text produced so far, and bills no further work.

**How it works:**

1. **Button transformation**: When streaming starts for the current conversation, the send button transforms to a stop button (red square icon with `.btn-stop` class)
2. **Stop request**: once `user_message_saved` has arrived (the server has the turn), Stop sends `POST /api/conversations/<id>/chat/stop` and **keeps reading the stream** (`requestServerStop()` in [stream-session.ts](../../web/src/core/stream-session.ts), registered on the live stream and on the reload-resume reader via `setStopHandler()`). Before that ack there is nothing server-side to stop, so Stop aborts the reader as a failed send
3. **Cross-worker signal**: the route writes a kv flag (namespace `cancel`, key = conversation id) - it may land on a different gunicorn worker than the one running the turn. The producer thread owns a `CancelToken` registered by request id; a poller thread checks the flag every `CANCEL_POLL_INTERVAL_SECONDS` (0.5) and cancels the token ([cancellation.py](../../src/agent/cancellation.py)). The flag is cleared synchronously before the producer starts (a Stop sent after the previous turn ended cannot cancel this one) and again at turn end
4. **Checkpoints** end the turn - the token stream, `chat_node`, `check_tool_results`, `execute_code`, browser batches; see [Agent Graph - Stop Checkpoints](../architecture/agent-graph.md#stop-checkpoints)
5. **Save**: the `final` event carries `stop_reason: "user"`; the normal save path stores the partial reply (or "Stopped before answering." when nothing streamed yet) and records `messages.stop_reason`. Cost covers the tokens actually used
6. **UI**: the `done` event (and the resume endpoint's done, and loaded message lists) carries `stop_reason: "user"`; the reply shows the stopped-early note labelled "Stopped." with **Continue** (the existing `rerun_mode: "continue"`). A "Response stopped." toast confirms
7. **Fallback**: if no `done` arrives within `STOP_DONE_GRACE_MS` (5 s, [config.ts](../../web/src/config.ts)) the reader is aborted; the partial bubble stays (marked incomplete) and sync later loads the saved message

**Key files:**
- [store.ts](../../web/src/state/store.ts) - `streamingConversationId` state
- [api/chat.ts](../../web/src/api/chat.ts) - Abort handling
- [MessageInput.ts](../../web/src/components/MessageInput.ts) - Button transformation
- [active-requests.ts](../../web/src/core/active-requests.ts) - Abort flow (per-request AbortControllers, `swapAbortController`)

**Race conditions handled:**

| Condition | Handling |
|-----------|----------|
| Stop clicked while done event processing | Done event clears streaming state; stop button disappears before click possible |
| User switches conversations during streaming | Stop button only shows for current streaming conversation |
| Rapid stop/send clicks | Button state controlled by store subscription; mode check in click handler |
| Stream naturally completes | `setStreamingConversation(null)` in finally block reverts button |
| Multiple conversations streaming in background | Only `streamingConversationId === currentConversation.id` shows stop button |

### Streaming Graceful Degradation

The streaming implementation handles server restarts gracefully:
- LangGraph uses a `ThreadPoolExecutor` internally for graph execution
- During server restart, the executor shuts down while streaming may still be in progress
- This raises `RuntimeError: cannot schedule new futures after shutdown`
- The `stream_chat_events()` method catches this specific error and continues with accumulated content
- The final event is still yielded with whatever content was accumulated before the interruption
- This allows partial responses to be saved to the database even during restarts

### Stream Recovery with Placeholder Message Pattern

When streaming responses, the connection can drop mid-stream (network issues, proxy timeouts, client disconnects). To handle this gracefully, we use a **placeholder message pattern** with pre-generated IDs:

**How it works:**

1. **Pre-generate ID on server**: When a stream starts, `_StreamContext` generates a UUID (`expected_assistant_msg_id`) for the assistant message
2. **Save placeholder to DB**: `_yield_user_message_saved()` saves an empty assistant message with this ID to the database immediately, so `GET /api/messages/{id}` returns 200 from the start
3. **Send ID early**: The ID is included in the `user_message_saved` SSE event, sent at the very start of streaming
4. **Frontend stores ID**: The frontend captures this ID in `StreamingState.expectedAssistantMessageId`
5. **Update placeholder on completion**: When streaming finishes, `save_message_to_db()` calls `db.update_message_content()` to fill in the placeholder with final content
6. **Clean up on failure**: If an error occurs with no content, the placeholder is deleted via `db.delete_message_by_id()`
7. **Recovery on failure**: If the stream ends without a `done` event, the frontend can fetch the specific message by its known ID — and since the placeholder exists, the fetch succeeds immediately

**Why pre-generated IDs + placeholders?**

Without a known ID, the frontend would have to fetch "recent messages" and guess which one is the response - creating race conditions if:
- Another message arrives (from another tab/device)
- The user quickly sends another message
- Multiple streams complete around the same time

Without placeholders, the frontend would get 404s until the message is saved at stream end, requiring multiple retries. With placeholders, the message exists in DB from the start — recovery shifts from "find the message" to "wait for content to arrive."

**Recovery flow (missing done event):**

```
Stream starts → placeholder saved to DB → user_message_saved event (includes ID)
     ↓
[Connection drops during thinking/tokens]
     ↓
Stream ends without done event
     ↓
Frontend detects missing done event
     ↓
Phase 1: GET /api/messages/{id} → 200 (placeholder found instantly)
     ↓
Phase 2: Message empty? Poll for content (~120s, covers long tool chains)
     ↓
Content arrives: Display recovered message
Content never arrives: Show "Response may be incomplete" warning
```

### Content Recovery in Done Event

Even when the stream completes successfully, token events can be lost during transmission (network hiccups, iOS Safari connection issues, proxy buffering). To handle this, the `done` event includes the full message content:

```json
{
  "type": "done",
  "id": "message-uuid",
  "created_at": "2024-01-24T12:00:00.000Z",
  "content": "The full message content...",
  ...
}
```

**Recovery flow (missing tokens):**

```
Stream starts → thinking events arrive → [tokens lost] → done event arrives
     ↓
Frontend receives done event but has no accumulated content
     ↓
Frontend detects: event.content exists but state.fullContent is empty
     ↓
Frontend renders content from done event instead
     ↓
Message displays correctly despite lost token events
```

This belt-and-suspenders approach ensures the message content is always available, even if individual token events were lost during streaming.

**Key files:**
- [chat_streaming.py](../../src/api/helpers/chat_streaming.py) - `_StreamContext.expected_assistant_msg_id`, `_yield_user_message_saved()`, placeholder lifecycle
- [stream_finalize.py](../../src/api/helpers/stream_finalize.py) - `_finalize_stream()` fills the placeholder and builds `done`
- [message.py](../../src/db/models/message.py) - `update_message_content()`, `delete_message_by_id()`
- [stream-recovery.ts](../../web/src/core/stream-recovery.ts) - Two-phase `fetchMessageWithRetry()` (Phase 1: find, Phase 2: content poll)
- [stream-resume.ts](../../web/src/core/stream-resume.ts) - `handleMissingDoneEvent()`; [stream-session.ts](../../web/src/core/stream-session.ts) - `StreamingState.expectedAssistantMessageId`
- [conversation_messages.py](../../src/api/routes/conversation_messages.py) - `GET /api/messages/<message_id>` endpoint, placeholder filtering

**Other uses for pre-generated IDs:**
- **Idempotent saves**: The cleanup thread and main generator both use the same ID, preventing duplicates
- **Reliable done event**: `_finalize_stream` fetches by known ID instead of "last message"
- **Audit trails**: Message lifecycle can be tracked from stream start to completion

### Generator vs Cleanup Thread Synchronization

The streaming architecture has two paths that can save the assistant message:
1. **Generator path**: The main streaming generator calls `_finalize_stream()` ([stream_finalize.py](../../src/api/helpers/stream_finalize.py)) when complete
2. **Cleanup thread path**: `cleanup_and_save()` ([stream_producer.py](../../src/api/helpers/stream_producer.py)) waits for the producer thread and saves if needed

This dual-path design ensures messages are saved even if the client disconnects, but creates a race
condition where both paths might try to save the same message simultaneously.

**Synchronization mechanism:**

```python
# In _StreamContext
save_lock = threading.Lock()           # Atomic check-then-save
generator_done_event = threading.Event() # Signal from generator to cleanup
final_results["saved"] = False         # Track if message was saved
```

**Why generator has priority:**
- Generator can send the `done` SSE event to the client with the saved message
- Cleanup thread can only save, not notify the client
- If generator saves first, client gets proper confirmation

**Flow:**

```
Generator thread                    Cleanup thread
     |                                    |
     |  (streaming tokens...)             |
     |                                    | wait for stream thread
     |  acquire save_lock                 |
     |  save message                      |
     |  set saved=True                    |
     |  release save_lock                 |
     |  set generator_done_event    -->   | event received
     |  send done event to client         | return (no save needed)
     |                                    |
```

**Timeout fallback:**
If the generator hangs or crashes, the cleanup thread has a timeout
(`STREAM_CLEANUP_WAIT_DELAY`) after which it will acquire the lock and save if `saved=False`.

**Key files:** [chat_streaming.py](../../src/api/helpers/chat_streaming.py) (`_StreamContext`), [stream_producer.py](../../src/api/helpers/stream_producer.py) (`cleanup_and_save()`)

### Streaming Data Flow (components that change together)

The producer/consumer pipeline (see [Chat Turn Lifecycle](#chat-turn-lifecycle)) has several parts that are tightly coupled — changing the shape of streamed events or the accumulated state means updating **all** of them in lockstep, or the stream silently loses data:

```
stream_events()        → event_queue → _process_event_queue() → _handle_queue_event() → _finalize_stream()   → save_message_to_db()
(stream_producer.py)                   (chat_streaming.py)                               (stream_finalize.py)   (chat_save.py)
```

1. `_StreamContext` class ([chat_streaming.py](../../src/api/helpers/chat_streaming.py)) — holds the accumulated state (content, thinking, IDs, journal) for the stream
2. `stream_events()` ([stream_producer.py](../../src/api/helpers/stream_producer.py)) — the producer thread: `turn.apply()`, runs `stream_chat_events()`, journals and pushes events onto `event_queue`
3. `_handle_queue_event()` — translates each queued event into the client-facing SSE payload
4. `_finalize_stream()` / `_finalize_approval_stream()` ([stream_finalize.py](../../src/api/helpers/stream_finalize.py)) — final processing / `done` event after the queue drains
5. `_StreamContext.start_threads()` — starts the producer and the `cleanup_and_save()` thread
6. `save_message_to_db()` in [chat_save.py](../../src/api/helpers/chat_save.py) — persists the assistant message (`result_messages: list[Any]` of LangChain `BaseMessage` objects)
7. All mock return values in the integration tests (they stub these return types)

### Resumable Streams

Generation always survived a client disconnect (the producer thread plus the cleanup-thread save complete the turn regardless). Resumable streams add the ability for a reconnecting client to **replay what it missed** and keep tailing the same in-flight turn.

**Stream journal.** The producer journals every client-facing SSE event to the `stream_journal` table (migration [0035_add_stream_journal.py](../../migrations/0035_add_stream_journal.py)) via `_StreamJournal` in [stream_resume.py](../../src/api/helpers/stream_resume.py), keyed by assistant `message_id` with a monotonic `seq`. Writes are batch-flushed (by count or interval) and old rows are TTL-swept at journal start. Journaling is **best-effort** — a journal failure logs a warning and never breaks the live stream.

**Why DB-backed?** A resume request may land on a **different gunicorn worker** than the one still generating, so an in-memory buffer would be invisible to it. Persisting to SQLite makes the journal cross-worker.

**Resume endpoint.** `GET /api/conversations/<conv_id>/chat/stream/<message_id>/resume?after_seq=N` (`chat_stream_resume` in [routes/chat.py](../../src/api/routes/chat.py), generator `stream_resume_events` in [stream_resume.py](../../src/api/helpers/stream_resume.py)). It replays journaled rows with `seq > after_seq`, then tails the journal until the producer's `stream_end` marker, then waits briefly for the saved message and synthesizes a `done` event from it. If the placeholder is gone (failed turn) or the stream stalls with no terminal marker, it emits `{"type": "error", "code": "RESUME_FAILED"}`.

**Client reconnect.** `tryResumeStream` in [stream-resume.ts](../../web/src/core/stream-resume.ts) tracks `state.lastSeq` from each `event.seq` and reconnects with `after_seq=lastSeq`. This is what makes mobile network handoffs (wifi ↔ cellular, backgrounding) recover live progress instead of only polling for the final message.

**Invariants (violating these re-introduces fixed bugs):**

- **Any NEW SSE event type must be added to `_JOURNALED_EVENT_TYPES`** in [stream_resume.py](../../src/api/helpers/stream_resume.py), or it will not be journaled and therefore won't replay on resume. (Current set: `token`, `thinking`, `tool_start`, `tool_end`, `approval_required`, `timeout`.) The one deliberate exception is `retry`: a momentary status that a resumed client has no reason to replay. The `done`/`final` result is intentionally **not** journaled — it isn't reliably JSON-serializable and is instead rebuilt from the saved message.
- **A 404 from the resume endpoint must fall back to poll-based recovery immediately, with no retries.** A 404 means there is no journal for this message (expired, or a server build without the endpoint — e.g. the E2E mock server). The instant fallback in `tryResumeStream` is what keeps the existing E2E suite green.
- The client-side resume invariants (ordering vs. the active-request restore in `switchToConversation`, clearing `inflight-streams` only on terminal outcome, `swapAbortController`, removing the empty placeholder row by `data-message-id`) are tightly coupled — see the resume flow in [stream-resume.ts](../../web/src/core/stream-resume.ts) (entries persisted by [inflight-streams.ts](../../web/src/core/inflight-streams.ts)) / [conversation-switch.ts](../../web/src/core/conversation-switch.ts).

### Reliable Sends (Outbox)

A message send used to be pure optimism: a DOM-only bubble, no store entry, nothing surfaced on failure — a send that died with the connection looked delivered and vanished on reload. The send pipeline (Aug 2026) makes delivery explicit:

**Idempotent sends.** The client generates the user message UUID (`crypto.randomUUID()`) and sends it as `client_message_id` in both chat POSTs. The server uses it as the message row ID (`db.add_message(message_id=...)` — no migration needed) and `_dedupe_client_message_id` in [chat_turn.py](../../src/api/helpers/chat_turn.py) returns **409 CONFLICT** with the message id when it already exists in the conversation (validation error if it exists elsewhere). Retries therefore can never duplicate a message; a 409 on retry means "it actually landed" and triggers a refetch-reconcile instead of an error.

**Send outbox** ([core/outbox.ts](../../web/src/core/outbox.ts)). Every outgoing message is written to the Zustand store (`status: 'pending'`) and persisted to localStorage before any network I/O. Delivery is confirmed by the **first SSE event** (streaming) or the response (batch) → entry dropped, status cleared. On failure the entry flips to `failed`. Reconciliation (`reconcileOutboxWithServer`, called at every conversation-load site in [conversation.ts](../../web/src/core/conversation.ts) and [conversation-deeplink.ts](../../web/src/core/conversation-deeplink.ts)) compares outbox entries against server messages: confirmed → dropped, in-flight in this session → rendered pending, otherwise → rendered failed with retry/discard.

**Failure UX.** Failed bubbles stay in place with inline "Not sent — Retry / Discard" actions ([components/messages/send-state.ts](../../web/src/components/messages/send-state.ts), dispatching `outbox:retry`/`outbox:discard` CustomEvents handled in [rerun.ts](../../web/src/core/rerun.ts)). Transient failures (network error, connect timeout) get **one silent auto-retry** after `SEND_AUTO_RETRY_DELAY_MS` before surfacing. Attachments over `OUTBOX_PERSIST_MAX_FILE_CHARS` aren't persisted to localStorage — a reload keeps the text but drops the files (`filesDropped`, warned on retry).

**Invariants:**

- The double-send guard (`getActiveRequest`) must run **before** the optimistic render in `sendMessage` — a bubble with no request behind it is exactly the original bug.
- The initial streaming POST has a **30s connect timeout even with an external AbortController** (`API_CHAT_CONNECT_TIMEOUT_MS` in [api/chat.ts](../../web/src/api/chat.ts)); passing a controller used to disable all timeouts.
- `markSendFailed` no-ops once the outbox entry is confirmed — a mid-stream failure after delivery must not flag the *user* message as unsent (that path belongs to stream recovery above).
- Image `data-pending` (lightbox gating) keys off `message.status`, not ID shape — there are no `temp-` message IDs anymore (conversations still use `temp-` IDs).

### Auto-Scroll

Scroll behavior during and after a turn (follow threshold, streaming pause, end-of-turn repositioning, mobile keyboard) is documented in [Scroll Behavior](../ui/scroll-behavior.md#auto-scroll-rules-aug-2026-audit).

## Force Tools System

The `forceTools` state in Zustand allows forcing specific tools to be used. Currently only `web_search` is exposed via UI, but the system supports any tool name. The force tools instruction is added to the system prompt when tools are specified.

- Frontend: `store.forceTools: string[]` with `toggleForceTool(tool)` and `clearForceTools()`
- Backend: `force_tools` parameter on the `chat/batch` and `chat/stream` endpoints
- Agent: `get_force_tools_prompt()` in [prompts.py](../../src/agent/prompts.py)

## Conversation and Message Patterns

### Conversation Titles

Titles are set two ways, both resolved by `_resolve_title_update()` in
[chat_save.py](../../src/api/helpers/chat_save.py) (called from both the stream save
pipeline and the batch endpoint):

1. **First exchange (auto-generation)**: while the title is still `DEFAULT_CONVERSATION_TITLE`,
   `generate_title()` in [title.py](../../src/agent/title.py) creates one with a cheap Flash
   call (single leading emoji + space, 3-6 words, user's language). This path always takes
   precedence over the agent tool on the same turn.
2. **Agent-driven retitle**: the agent sees the current title in its per-request dynamic
   context (`CONVERSATION_TITLE_CONTEXT_PROMPT` in [prompt_texts/core.py](../../src/agent/prompt_texts/core.py))
   and calls the extract-only `set_conversation_title` tool
   ([tools/metadata.py](../../src/agent/tools/metadata.py)) when the conversation's scope has
   clearly widened or narrowed. The arg is read post-hoc by `extract_conversation_title()` in
   [content.py](../../src/agent/content.py) (last call wins, cleaned and clamped like
   `generate_title`), applied to the DB, and delivered to the UI via the existing `title`
   field on the `done` event / batch response — no new SSE event type, no frontend changes.

Rules: program conversations (sports / language / planner) are never retitled and get no
title context in their prompt; retitling to the identical title is a no-op; a title failure
never aborts the message save. Manual renames are not protected — the agent may retitle a
manually renamed conversation on a later scope change.

### Lazy Conversation Creation

Conversations are created locally with `temp-` prefixed ID and only persisted to DB on first message. This prevents empty conversations from polluting the database.

**Key files:**
- [conversation.ts](../../web/src/core/conversation.ts) - `createConversation()`, `isTempConversation()`
- [messaging.ts](../../web/src/core/messaging.ts) - `persistTempConversation()` creates the real conversation on first send

### User Message ID Handling

The client generates the user message ID (`crypto.randomUUID()`, sent as `client_message_id`) and the server stores the row under it, so a normal send's ID is final from the start. The server still echoes the ID - `user_message_saved` SSE event (streaming) or `user_message_id` (batch) - and `updateUserMessageId()` swaps it into the DOM: a no-op for normal sends, needed for re-runs, whose `rerun-*` anchor maps to an existing message.

Images in a message that is not yet confirmed (`message.status` pending) carry `data-pending="true"` and show `cursor: wait`.

### Concurrent Request Handling

The app supports multiple active requests across different conversations simultaneously. Requests continue processing in the background even when users switch conversations.

**Key implementation:**
- Active requests tracked per conversation in the store's `activeRequests` map (UI snapshot); the AbortControllers live in [active-requests.ts](../../web/src/core/active-requests.ts)
- Requests only update UI if their conversation is still current
- Server-side: cleanup threads ensure messages are saved even if client disconnects

### Seamless Conversation Switching

When switching away from a conversation with an active request and back, the UI state is seamlessly restored.

**State management:**
- `activeRequests` Map in store tracks content and thinking state per conversation
- The streaming context in [messages/streaming.ts](../../web/src/components/messages/streaming.ts) (`getStreamingMessageElement`) tracks DOM elements for continued updates
- The in-session store is authoritative for messages: every completion path (done event, journal resume, poll recovery, batch reply) `appendMessage`s the finished assistant reply, and `appendMessage` is idempotent by id because one reply can complete via more than one path
- Streaming context includes `conversationId` to determine whether to clean up

### Conversation Selection Race Condition

A module-level `pendingConversationId` variable in [conversation.ts](../../web/src/core/conversation.ts) tracks which conversation the user most recently clicked. When an API call completes, we check if it matches - if not, the user navigated elsewhere and we cancel the operation.

## Frontend Send, Re-run and Retry

The send path is split by responsibility in `web/src/core/`:

| Module | Role |
|--------|------|
| [messaging.ts](../../web/src/core/messaging.ts) | `sendMessage()` from the composer: double-send guard, temp-conversation persistence, optimistic user bubble + outbox entry, then `dispatchSend()`; while a reply in that conversation is still running, routes the text (no attachments) to [steering.ts](../../web/src/core/steering.ts) (interject) instead. Owns dispatch-level failure handling (`handleSendFailure`: 409 reconcile, one silent auto-retry on transient errors, then `markSendFailed` + toast) |
| [stream-send.ts](../../web/src/core/stream-send.ts) / [batch-send.ts](../../web/src/core/batch-send.ts) | `sendStreamingMessage()` / `sendBatchMessage()`: one turn in each mode |
| [stream-session.ts](../../web/src/core/stream-session.ts), [stream-events.ts](../../web/src/core/stream-events.ts), [stream-done.ts](../../web/src/core/stream-done.ts) | Per-stream state, per-event handling, the terminal `done` event |
| [stream-resume.ts](../../web/src/core/stream-resume.ts), [stream-recovery.ts](../../web/src/core/stream-recovery.ts), [inflight-streams.ts](../../web/src/core/inflight-streams.ts) | Journal resume, poll recovery, reload-resume |
| [send-delivery.ts](../../web/src/core/send-delivery.ts), [outbox.ts](../../web/src/core/outbox.ts) | Delivery state (`confirmDelivery`, `markSendFailed`, auto-retry claim) and the persisted outbox |
| [active-requests.ts](../../web/src/core/active-requests.ts) | AbortControllers per in-flight request (stop button, logout) |
| [rerun.ts](../../web/src/core/rerun.ts) | Actions on already-sent messages (below) |
| [response-scroll.ts](../../web/src/core/response-scroll.ts), [thinking-state.ts](../../web/src/core/thinking-state.ts) | End-of-turn scroll, per-stream thinking trace |

**Actions on sent messages** ([rerun.ts](../../web/src/core/rerun.ts)). Message components
dispatch document events; `initOutboxHandlers()` (called once from init) handles them.
All except retry/discard refuse to run while the conversation has an active request.

| Event | Action |
|-------|--------|
| `outbox:retry` | `retryFailedMessage()` re-dispatches the outbox entry through `dispatchSend()` (idempotent via `client_message_id`; a manual retry re-arms the auto-retry) |
| `outbox:discard` | Drops the outbox entry and the bubble |
| `message:regenerate` | Deletes the last assistant reply, then re-runs with `rerun_mode: "regenerate"` |
| `message:continue` | Re-runs with `rerun_mode: "continue"` - also what the stopped-early note's **Continue** button dispatches |
| `message:edit` | Inline edit; saving truncates the conversation from that message (server first), then re-sends the edited text through the normal `sendMessage()` pipeline |

A re-run sends an empty message plus `rerun_mode` through the usual streaming or batch
path, with a `rerun-<timestamp>` anchor id in place of a user message id (no optimistic
bubble or outbox entry exists, so send-state updates are no-ops). Server side,
`_resolve_rerun()` in [chat_turn.py](../../src/api/helpers/chat_turn.py) inserts no user
message: `regenerate` requires the conversation to end with a user message and re-answers
it; `continue` requires a trailing assistant reply and sends a continue instruction.

There is no draft store: an unsent message stays visible as a failed bubble with
Retry / Discard (see [Reliable Sends](#reliable-sends-outbox)).

**Testing:** [rerun.spec.ts](../../web/tests/e2e/chat/rerun.spec.ts) ("Chat - Regenerate /
Continue / Edit"), [send-failure.spec.ts](../../web/tests/e2e/chat/send-failure.spec.ts)
("Send Failure Handling", "Send Auto-Retry"), "Chat - Message Retry" in
[message-actions.spec.ts](../../web/tests/e2e/chat/message-actions.spec.ts),
[messaging-store.test.ts](../../web/tests/unit/messaging-store.test.ts),
[test_routes_chat_turn.py](../../tests/integration/test_routes_chat_turn.py).

## Key Files

- [routes/chat.py](../../src/api/routes/chat.py) - chat endpoints
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - `prepare_turn()`, `build_turn_context()`, `TurnContext`
- [stream_producer.py](../../src/api/helpers/stream_producer.py), [chat_streaming.py](../../src/api/helpers/chat_streaming.py), [stream_finalize.py](../../src/api/helpers/stream_finalize.py) - streaming producer / consumer / finalize
- [chat_save.py](../../src/api/helpers/chat_save.py) - `save_message_to_db()`, title resolution
- [stream_resume.py](../../src/api/helpers/stream_resume.py) - stream journal and resume
- [agent.py](../../src/agent/agent.py) - `ChatAgent.chat_batch()`, `stream_chat_events()`
- [web/src/core/](../../web/src/core/) - send, stream, resume and re-run modules (table above)

## See Also

- [Agent Graph](../architecture/agent-graph.md) - the agent loop, retries, tool rounds
- [Conversation Context](../architecture/conversation-context.md) - history enrichment and compaction
- [Thinking Indicator and Source Chips](thinking-and-sources.md) - streamed trace and sources
- [Streaming Metadata](../architecture/streaming-metadata.md) - MSG_CONTEXT stripping, client-side recovery
- [File Handling](file-handling.md) - uploads, thumbnails, video
- [UI Features](ui-features.md) - Input toolbar, message sending behavior
- [Frontend and E2E Testing](../testing/frontend.md) - chat E2E specs
