# Chat and Streaming

This document covers the chat system, streaming responses, thinking indicators, web search sources, and tool usage.

## Gemini API Integration

### Models
- `gemini-3-pro-preview` - Complex tasks, advanced reasoning
- `gemini-3-flash-preview` - Fast, cheap (default)

### Response Format
Gemini may return content in various formats:
- String: `"response text"`
- List: `[{'type': 'text', 'text': '...', 'extras': {...}}]`
- Dict: `{'type': 'text', 'text': '...'}`

Use `extract_text_content()` in [content.py](../../src/agent/content.py) to normalize.

### Parameters
- `thinking_level`: Controls reasoning (minimal/low/medium/high)
- Temperature: Keep at 1.0 (Gemini 3 default)

## Streaming Architecture

### Stop Streaming

Users can abort an ongoing streaming response by clicking the stop button.

**How it works:**

1. **Button transformation**: When streaming starts for the current conversation, the send button transforms to a stop button (red square icon with `.btn-stop` class)
2. **State tracking**: `streamingConversationId` in Zustand store tracks which conversation is streaming
3. **Abort mechanism**: Clicking stop calls `abortController.abort()` on the streaming fetch request
4. **Stream cancellation**: The API client catches `AbortError` and re-throws it so the caller can handle cleanup
5. **UI cleanup**: The streaming assistant message element is removed from the DOM immediately
6. **User feedback**: A toast notification confirms "Response stopped."

**Note on partial messages**: When the user aborts, the backend cleanup thread may still save a partial message to the database. These partial messages are intentionally NOT deleted automatically - users can clean them up later using the message delete button. This simpler approach avoids complex timing issues with backend cleanup threads and race conditions.

**Key files:**
- [store.ts](../../web/src/state/store.ts) - `streamingConversationId` state
- [client.ts](../../web/src/api/client.ts) - Abort handling
- [MessageInput.ts](../../web/src/components/MessageInput.ts) - Button transformation
- [messaging.ts](../../web/src/core/messaging.ts) - Abort flow

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
- [message.py](../../src/db/models/message.py) - `update_message_content()`, `delete_message_by_id()`
- [stream-recovery.ts](../../web/src/core/stream-recovery.ts) - Two-phase `fetchMessageWithRetry()` (Phase 1: find, Phase 2: content poll)
- [messaging.ts](../../web/src/core/messaging.ts) - `handleMissingDoneEvent()`, `StreamingState.expectedAssistantMessageId`
- [conversations.py](../../src/api/routes/conversations.py) - `GET /api/messages/<message_id>` endpoint, placeholder filtering

**Other uses for pre-generated IDs:**
- **Idempotent saves**: The cleanup thread and main generator both use the same ID, preventing duplicates
- **Reliable done event**: `_finalize_stream` fetches by known ID instead of "last message"
- **Audit trails**: Message lifecycle can be tracked from stream start to completion

### Generator vs Cleanup Thread Synchronization

The streaming architecture has two paths that can save the assistant message:
1. **Generator path**: The main streaming generator calls `_finalize_stream()` when complete
2. **Cleanup thread path**: A background thread waits for the stream and saves if needed

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

**Key file:** [chat_streaming.py](../../src/api/helpers/chat_streaming.py)

### Streaming Data Flow (components that change together)

The producer/consumer pipeline in [chat_streaming.py](../../src/api/helpers/chat_streaming.py) has several parts that are tightly coupled — changing the shape of streamed events or the accumulated state means updating **all** of them in lockstep, or the stream silently loses data:

```
stream_events() → event_queue → _process_event_queue() → _handle_queue_event() → _finalize_stream() → save_message_to_db()
```

1. `_StreamContext` class — holds the accumulated state (content, thinking, IDs, journal) for the stream
2. `stream_events()` — the producer thread that runs the LangGraph stream and pushes events onto `event_queue`
3. `_handle_queue_event()` — translates each queued event into the client-facing SSE payload
4. `_finalize_stream()` — final processing / `done` event after the queue drains
5. `_StreamContext.start_threads()` — starts the producer (and cleanup) threads
6. `save_message_to_db()` in [chat_save.py](../../src/api/helpers/chat_save.py) — persists the assistant message (`result_messages: list[Any]` of LangChain `BaseMessage` objects)
7. All mock return values in the integration tests (they stub these return types)

### Resumable Streams

Generation always survived a client disconnect (the producer thread plus the cleanup-thread save complete the turn regardless). Resumable streams add the ability for a reconnecting client to **replay what it missed** and keep tailing the same in-flight turn.

**Stream journal.** The producer journals every client-facing SSE event to the `stream_journal` table (migration [0035_add_stream_journal.py](../../migrations/0035_add_stream_journal.py)) via `_StreamJournal` in [stream_resume.py](../../src/api/helpers/stream_resume.py), keyed by assistant `message_id` with a monotonic `seq`. Writes are batch-flushed (by count or interval) and old rows are TTL-swept at journal start. Journaling is **best-effort** — a journal failure logs a warning and never breaks the live stream.

**Why DB-backed?** A resume request may land on a **different gunicorn worker** than the one still generating, so an in-memory buffer would be invisible to it. Persisting to SQLite makes the journal cross-worker.

**Resume endpoint.** `GET /conversations/<conv_id>/chat/stream/<message_id>/resume?after_seq=N` (`chat_stream_resume` in [routes/chat.py](../../src/api/routes/chat.py), generator `stream_resume_events` in [stream_resume.py](../../src/api/helpers/stream_resume.py)). It replays journaled rows with `seq > after_seq`, then tails the journal until the producer's `stream_end` marker, then waits briefly for the saved message and synthesizes a `done` event from it. If the placeholder is gone (failed turn) or the stream stalls with no terminal marker, it emits `{"type": "error", "code": "RESUME_FAILED"}`.

**Client reconnect.** `tryResumeStream` in [messaging.ts](../../web/src/core/messaging.ts) tracks `state.lastSeq` from each `event.seq` and reconnects with `after_seq=lastSeq`. This is what makes mobile network handoffs (wifi ↔ cellular, backgrounding) recover live progress instead of only polling for the final message.

**Invariants (violating these re-introduces fixed bugs):**

- **Any NEW SSE event type must be added to `_JOURNALED_EVENT_TYPES`** in [stream_resume.py](../../src/api/helpers/stream_resume.py), or it will not be journaled and therefore won't replay on resume. (Current set: `token`, `thinking`, `tool_start`, `tool_end`, `approval_required`, `timeout`.) The `done`/`final` result is intentionally **not** journaled — it isn't reliably JSON-serializable and is instead rebuilt from the saved message.
- **A 404 from the resume endpoint must fall back to poll-based recovery immediately, with no retries.** A 404 means there is no journal for this message (expired, or a server build without the endpoint — e.g. the E2E mock server). The instant fallback in `tryResumeStream` is what keeps the existing E2E suite green.
- The client-side resume invariants (ordering vs. the active-request restore in `switchToConversation`, clearing `inflight-streams` only on terminal outcome, `swapAbortController`, removing the empty placeholder row by `data-message-id`) are tightly coupled — see the resume flow in [messaging.ts](../../web/src/core/messaging.ts) / [conversation.ts](../../web/src/core/conversation.ts).

### Reliable Sends (Outbox)

A message send used to be pure optimism: a DOM-only bubble, no store entry, nothing surfaced on failure — a send that died with the connection looked delivered and vanished on reload. The send pipeline (Aug 2026) makes delivery explicit:

**Idempotent sends.** The client generates the user message UUID (`crypto.randomUUID()`) and sends it as `client_message_id` in both chat POSTs. The server uses it as the message row ID (`db.add_message(message_id=...)` — no migration needed) and `_dedupe_client_message_id` in [routes/chat.py](../../src/api/routes/chat.py) returns **409 CONFLICT** with the message id when it already exists in the conversation (validation error if it exists elsewhere). Retries therefore can never duplicate a message; a 409 on retry means "it actually landed" and triggers a refetch-reconcile instead of an error.

**Send outbox** ([core/outbox.ts](../../web/src/core/outbox.ts)). Every outgoing message is written to the Zustand store (`status: 'pending'`) and persisted to localStorage before any network I/O. Delivery is confirmed by the **first SSE event** (streaming) or the response (batch) → entry dropped, status cleared. On failure the entry flips to `failed`. Reconciliation (`reconcileOutboxWithServer`, called at every conversation-load site in [conversation.ts](../../web/src/core/conversation.ts)) compares outbox entries against server messages: confirmed → dropped, in-flight in this session → rendered pending, otherwise → rendered failed with retry/discard.

**Failure UX.** Failed bubbles stay in place with inline "Not sent — Retry / Discard" actions ([components/messages/send-state.ts](../../web/src/components/messages/send-state.ts), dispatching `outbox:retry`/`outbox:discard` CustomEvents handled in messaging.ts). Transient failures (network error, connect timeout) get **one silent auto-retry** after `SEND_AUTO_RETRY_DELAY_MS` before surfacing. Attachments over `OUTBOX_PERSIST_MAX_FILE_CHARS` aren't persisted to localStorage — a reload keeps the text but drops the files (`filesDropped`, warned on retry).

**Invariants:**

- The double-send guard (`getActiveRequest`) must run **before** the optimistic render in `sendMessage` — a bubble with no request behind it is exactly the original bug.
- The initial streaming POST has a **30s connect timeout even with an external AbortController** (`API_CHAT_CONNECT_TIMEOUT_MS` in [client.ts](../../web/src/api/client.ts)); passing a controller used to disable all timeouts.
- `markSendFailed` no-ops once the outbox entry is confirmed — a mid-stream failure after delivery must not flag the *user* message as unsent (that path belongs to stream recovery above).
- Image `data-pending` (lightbox gating) keys off `message.status`, not ID shape — there are no `temp-` message IDs anymore (conversations still use `temp-` IDs).

### Auto-Scroll System

The scroll behavior is the most annoyance-sensitive UX area (regressions here hurt daily use more than visual bugs). Key mechanics after the Aug 2026 audit:

- **One follow threshold**: every "is the user following?" decision uses `SCROLL_USER_DETECTION_THRESHOLD_PX` (200px) — `SCROLL_BOTTOM_THRESHOLD_PX` aliases it and `isScrolledToBottom` defaults to it. Don't introduce new distance constants for the same question.
- **Streaming pause** ([streaming.ts](../../web/src/components/messages/streaming.ts)): wheel/touchmove pause immediately; the scroll handler additionally pauses on **direction** (an upward, non-programmatic move landing away from the bottom) to cover scrollbar drags and keyboard scrolling. Never pause on position alone — streaming growth changes `scrollHeight` and produced false positives historically.
- **Scroll-button tap re-arms follow synchronously** (`setOnJumpToBottom` hook) — the debounced position-based resume can miss while tokens grow `scrollHeight` during the smooth animation. While paused mid-stream, the button becomes a labeled "New messages" pill.
- **End-of-turn repositioning is length-conditional** (`RESPONSE_JUMP_MIN_VIEWPORT_RATIO`): responses taller than ~one viewport jump to their top (read-from-start); shorter ones finish at the bottom. The batch path pins the bottom **instantly** — `scrollToBottom`'s smooth animator has no user-interference abort and fights user scrolls for its whole run (unlike `scrollToElementTop`, which aborts on external movement).
- **`overflow-anchor: none` on `.messages`**: scroll anchoring is manual (pagination prepend compensation + image-load adjustment); browser anchoring on top of it double-adjusted.
- **Mobile keyboard** ([core/keyboard-viewport.ts](../../web/src/core/keyboard-viewport.ts)): the fixed 100vh layout means keyboards OVERLAY the page. The visualViewport overlap becomes `--keyboard-inset` (shrinks `html/body` height) and the messages view re-pins to the bottom when the user was following. Guards: pinch zoom (`scale !== 1`), no editable element focused, overlaps under `KEYBOARD_INSET_MIN_PX`.
- **Thinking-trace collapse compensation**: finalizing the trace shrinks content above a reader scrolled below it — `finalizeThinkingIndicator` measures the height delta and restores `scrollTop`.
- **Don't touch** `scheduleScrollAfterImageLoad` in [thumbnails.ts](../../web/src/utils/thumbnails.ts) without a confirmed bug — it's correct-by-heavy-defense with dedicated regression E2E tests (2-image races in conversation.spec.ts).

## Thinking Indicator

During streaming responses, the app shows a thinking indicator at the top of assistant messages to provide feedback about the model's internal processing and tool usage.

### Design Principles

- **Streaming only**: The indicator only appears during streaming mode, not when loading historical messages
- **No persistence**: Thinking state and tool activity are NOT stored in the database
- **Singleton thinking**: There's exactly ONE thinking item that accumulates all thinking text, updated in real-time
- **Live updates**: Thinking text is visible and updates during streaming, not just in finalized view
- **Full trace**: Shows thinking (singleton) + all tool events with details
- **Rich details**: Shows full thinking text, search queries, URLs, and image prompts
- **Auto-collapse**: When the message finishes, the indicator collapses into a "Show details" toggle

### How it works

1. **Backend streaming**: `stream_chat_events()` in [agent.py](../../src/agent/agent.py) yields structured events:
   - `{"type": "thinking", "text": "..."}` - Accumulated thinking text (if `include_thoughts=True`)
   - `{"type": "tool_start", "tool": "web_search", "detail": "search query"}` - Tool starting with details
   - `{"type": "tool_end", "tool": "web_search"}` - When a tool finishes
   - `{"type": "token", "text": "..."}` - Regular content tokens
   - `{"type": "final", ...}` - Final result with metadata

2. **SSE forwarding**: [routes/chat.py](../../src/api/routes/chat.py) forwards these events via Server-Sent Events

3. **Frontend handling**: [messaging.ts](../../web/src/core/messaging.ts) parses events and calls:
   - `updateStreamingThinking(text)` for thinking events (with full accumulated text)
   - `updateStreamingToolStart(tool, detail)` for tool_start events (with optional detail)
   - `updateStreamingToolEnd()` for tool_end events

4. **UI rendering**: [ThinkingIndicator.ts](../../web/src/components/ThinkingIndicator.ts) manages the indicator:
   - Maintains a trace of all thinking/tool events with details
   - Shows animated "Thinking" with brain icon and dots during thinking
   - Shows tool icons, labels, and details (query/URL/prompt) with animated dots during execution
   - Shows checkmark when tools complete
   - Collapses into an expandable "Show details" toggle when message finishes

### Tool labels and details

The indicator uses user-friendly labels and shows relevant details for tools:
- `web_search` → "Searching the web" + search query → "Searched" + query (finalized)
- `fetch_url` → "Fetching page" + URL → "Fetched" + URL (finalized)
- `generate_image` → "Generating image" + prompt → "Generated image" + prompt (finalized)
- `execute_code` → "Running code" + first line of code → "Ran code" (finalized)

### Trace State Management

The thinking state tracks a full trace of events:

```typescript
interface ThinkingTraceItem {
  type: 'thinking' | 'tool';
  label: string;
  detail?: string;  // thinking text, search query, URL, or prompt
  completed: boolean;
}
```

**Singleton thinking behavior:**
- The trace is initialized with ONE thinking item at index 0
- All thinking updates go to this same item (detail gets replaced, not appended)
- When a tool starts, thinking is marked `completed: true` but remains in place
- If more thinking comes after a tool, the same thinking item is updated and marked `completed: false`
- This ensures there's always exactly one thinking item showing accumulated/latest thinking text

**Example trace progression:**
1. Initial: `[{type: 'thinking', completed: false}]`
2. Thinking arrives: `[{type: 'thinking', detail: "Analyzing...", completed: false}]`
3. Tool starts: `[{type: 'thinking', detail: "Analyzing...", completed: true}, {type: 'tool', label: 'web_search', ...}]`
4. More thinking: `[{type: 'thinking', detail: "New analysis...", completed: false}, {type: 'tool', ...}]`

### Display States

- **Streaming**: Shows full trace with active item at the bottom (for auto-scroll). Active items show animated dots
- **Finalized**: Collapses into toggle button. Clicking expands to show full trace with thinking first, then tools

### Trace Ordering

During streaming, thinking stays at the end of the trace (for auto-scroll). Tools are inserted before thinking. When finalized, trace is reordered: thinking first, then tools (logical reading order).

### Markdown Support

Thinking text is rendered with markdown formatting for better readability (lists, code blocks, emphasis, etc.).

### Gemini Thinking Support

The Gemini API supports a `include_thoughts=True` parameter that returns thinking content in the response. When enabled:
- `ChatGoogleGenerativeAI` is initialized with `include_thoughts=True`
- Response chunks may contain parts with `{'type': 'thinking', 'thinking': "..."}` format
- `extract_thinking_and_text()` separates thinking content from regular text
- Thinking text is accumulated across chunks and emitted as updates
- The backend yields `{"type": "thinking", "text": accumulated_text}` events during streaming

### Key Files

- [agent.py](../../src/agent/agent.py) - `stream_chat_events()`, `ChatAgent` class
- [content.py](../../src/agent/content.py) - `extract_thinking_and_text()`
- [routes/chat.py](../../src/api/routes/chat.py) - SSE streaming with thinking/tool events
- [api.ts](../../web/src/types/api.ts) - `StreamEvent` and `ThinkingState` types
- [ThinkingIndicator.ts](../../web/src/components/ThinkingIndicator.ts) - UI component
- [messages/streaming.ts](../../web/src/components/messages/streaming.ts) - Streaming state management
- [messaging.ts](../../web/src/core/messaging.ts) - Event handling
- [thinking.css](../../web/src/styles/components/thinking.css) - Styles and animations

### Testing

- Backend unit tests: `TestExtractThinkingAndText` in [test_chat_agent_helpers.py](../../tests/unit/test_chat_agent_helpers.py)
- Frontend unit tests: [thinking-indicator.test.ts](../../web/tests/unit/thinking-indicator.test.ts)
- E2E tests: "Chat - Thinking Indicator" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

## Web Search Sources

When the LLM uses `web_search` or `fetch_url` tools, it cites sources that are displayed to the user.

### How it works

1. **Tool returns JSON**: `web_search` returns `{"query": "...", "results": [{title, url, snippet}, ...]}` instead of plain text
2. **LLM appends metadata**: System prompt instructs LLM to append `<!-- METADATA:\n{"sources": [...]}\n-->` at the end of responses when web tools are used
3. **Backend extracts sources**: `extract_metadata_from_response()` in [content.py](../../src/agent/content.py) parses and strips the metadata block. It handles both HTML comment format (preferred) and plain JSON format (fallback), removing both if the LLM outputs metadata in both formats
4. **Streaming filters metadata**: During streaming, the HTML comment metadata marker is detected and not sent to the frontend. Any plain JSON metadata that slips through is cleaned in the final buffer check
5. **Sources stored in DB**: Messages table has a `sources` column (JSON array)
6. **Sources in API response**: Both batch and streaming responses include `sources` array
7. **UI shows sources button**: A globe icon appears in message actions when sources exist, opening a popup with clickable links

### Key Files

- [tools/web.py](../../src/agent/tools/web.py) - `web_search()` returns structured JSON
- [prompts.py](../../src/agent/prompts.py) - `TOOLS_SYSTEM_PROMPT_*` constants
- [content.py](../../src/agent/content.py) - `extract_metadata_from_response()`, streaming filter
- [models/](../../src/db/models/) - `Message.sources` field, `add_message()` with sources param
- [routes/chat.py](../../src/api/routes/chat.py) - Sources included in batch/stream responses
- [SourcesPopup.ts](../../web/src/components/SourcesPopup.ts) - Popup component
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Sources button rendering

### Metadata Format

```html
<!-- METADATA:
{"sources": [{"title": "Source Title", "url": "https://..."}]}
-->
```

The metadata block is always at the end of the LLM response and is stripped before storing/displaying content. Sometimes the LLM outputs plain JSON metadata (without HTML comments) instead of or in addition to the HTML comment format. The extraction function handles both formats, preferring HTML comment format but removing both if present.

## Force Tools System

The `forceTools` state in Zustand allows forcing specific tools to be used. Currently only `web_search` is exposed via UI, but the system supports any tool name. The force tools instruction is added to the system prompt when tools are specified.

- Frontend: `store.forceTools: string[]` with `toggleForceTool(tool)` and `clearForceTools()`
- Backend: `force_tools` parameter in `/chat/batch` and `/chat/stream` endpoints
- Agent: `get_force_tools_prompt()` in [prompts.py](../../src/agent/prompts.py)

## Conversation and Message Patterns

### Conversation Titles

Titles are set two ways, both resolved by `_resolve_title_update()` in
[chat_save.py](../../src/api/helpers/chat_save.py) (called from both the stream save
pipeline and the batch endpoint):

1. **First exchange (auto-generation)**: while the title is still `DEFAULT_CONVERSATION_TITLE`,
   `generate_title()` in [agent.py](../../src/agent/agent.py) creates one with a cheap Flash
   call (single leading emoji + space, 3-6 words, user's language). This path always takes
   precedence over the agent tool on the same turn.
2. **Agent-driven retitle**: the agent sees the current title in its per-request dynamic
   context (`CONVERSATION_TITLE_CONTEXT_PROMPT` in [prompts.py](../../src/agent/prompts.py))
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
- [messaging.ts](../../web/src/core/messaging.ts) - `sendMessage()` handles temp → real ID conversion

### User Message ID Handling

User messages are initially created with temp IDs (`temp-{timestamp}`) in the frontend. The backend returns the real message ID via:
- **Streaming mode**: `user_message_saved` SSE event
- **Batch mode**: `user_message_id` field in response

Images with temp message IDs are marked with `data-pending="true"` and show `cursor: wait` until the real ID is available.

### Concurrent Request Handling

The app supports multiple active requests across different conversations simultaneously. Requests continue processing in the background even when users switch conversations.

**Key implementation:**
- Active requests tracked per conversation in `activeRequests` map
- Requests only update UI if their conversation is still current
- Server-side: cleanup threads ensure messages are saved even if client disconnects

### Seamless Conversation Switching

When switching away from a conversation with an active request and back, the UI state is seamlessly restored.

**State management:**
- `activeRequests` Map in store tracks content and thinking state per conversation
- `streamingMessageElements` Map in [messaging.ts](../../web/src/core/messaging.ts) tracks DOM elements for continued updates
- Streaming context includes `conversationId` to determine whether to clean up

### Conversation Selection Race Condition

A module-level `pendingConversationId` variable in [conversation.ts](../../web/src/core/conversation.ts) tracks which conversation the user most recently clicked. When an API call completes, we check if it matches - if not, the user navigated elsewhere and we cancel the operation.

## History Enrichment

Conversation history is enriched with contextual metadata before being sent to the LLM. This helps the model understand temporal context, reference historical files, and know which tools were used.

### Context Format

Each historical message includes a JSON context block using `<!-- MSG_CONTEXT: -->` format (distinct from response `<!-- METADATA: -->`):

```
<!-- MSG_CONTEXT: {"timestamp":"2024-06-15 14:30 CET","files":[{"name":"report.pdf","type":"PDF","id":"msg-abc123:0"}]} -->
Can you analyze this data?
```

Note: The distinct marker prevents the LLM from echoing history context in its responses.

Only **stable, message-derived** fields are embedded inline. A recomputed relative time ("3 hours ago") is deliberately omitted because it would change every historical message's serialized bytes on each turn, defeating Gemini's implicit prefix caching of the history. The model derives elapsed time from the absolute `timestamp` plus the current time provided in the dynamic context block. For the same reason, in cached mode the per-request dynamic context (`[CONTEXT]`) is appended at the **tail** (just before the current user message) rather than the head, so the stable history forms a reusable prefix.

### Enrichment Fields

**For all messages:**
- `timestamp` - Absolute timestamp with timezone (e.g., "2024-06-15 14:30 CET")
- `session_gap` - Present when resuming after a gap (e.g., "2 days")

**For user messages:**
- `files` - Array of file metadata with `name`, `type`, and `id` (format: `message_id:file_index`)

**For assistant messages:**
- `tools_used` - Array of tool names used (e.g., `["web_search", "generate_image"]`)
- `tool_summary` - Human-readable summary (e.g., "searched 3 web sources, generated 1 image")

### Session Gap Detection

When messages are more than `HISTORY_SESSION_GAP_HOURS` apart (default: 4 hours), a session gap indicator is included. This helps the LLM understand context breaks in the conversation.

### File References

The compact `id` format (`message_id:file_index`) allows the LLM to directly reference historical files:
- `retrieve_file(message_id="msg-abc123", file_index=0)` - to analyze a file
- `generate_image(history_image_message_id="msg-abc123", history_image_file_index=0)` - to edit an image

### Configuration

```bash
# .env
HISTORY_SESSION_GAP_HOURS=4  # Gap threshold for session markers (hours)
```

### Key Files

- [history.py](../../src/agent/history.py) - `enrich_history()`, timestamp/file/tool formatting functions
- [agent.py](../../src/agent/agent.py) - `_format_message_with_metadata()`, `_build_messages()`
- [routes/chat.py](../../src/api/routes/chat.py) - Integration in batch and stream endpoints
- [config.py](../../src/config.py) - `HISTORY_SESSION_GAP_HOURS` configuration

### Testing

- Unit tests: `TestFormatMessageWithMetadata` in [test_chat_agent_helpers.py](../../tests/unit/test_chat_agent_helpers.py)
- Unit tests: [test_history.py](../../tests/unit/test_history.py) - comprehensive tests for enrichment functions

## Conversation Compaction (cost control)

Long chats re-send their entire history to the LLM on every turn, so cost grows ~O(n²) over a conversation. [conversation_compaction.py](../../src/agent/conversation_compaction.py) bounds the history *sent to the model* on regular (non-agent) conversations by replacing older turns with a running summary while keeping recent turns verbatim.

**Key properties:**
- **Non-destructive** — unlike the autonomous-agent path in [compaction.py](../../src/agent/compaction.py), the full message history stays in the database for display. Only the enriched history handed to the agent is compacted.
- **Lazy & cheap** — the running summary is persisted in `kv_store` (namespace `conv_compaction`, key = `conversation_id`; DB-backed, safe across the 4 gunicorn workers) and regenerated only when the un-summarized middle grows by `CONVERSATION_COMPACTION_RESUMMARIZE_BATCH` messages. So a summarization call (via the cheap `AI_ASSIST_MODEL`) fires roughly every N turns, not every turn.
- **Failure-safe** — if summarization fails it never drops context: it falls back to the prior summary plus the un-summarized middle, or to the full history when there is no usable summary yet.

`build_compacted_history(user_id, conversation_id, history)` returns `[summary_message] + uncovered_middle + recent` once the history exceeds the threshold, otherwise the input unchanged. It is wired into both the batch route ([routes/chat.py](../../src/api/routes/chat.py)) and the stream path (`_StreamContext.setup_context()` in [chat_streaming.py](../../src/api/helpers/chat_streaming.py)), gated on `not is_autonomous`. Reuses `summarize_messages()` from `compaction.py`.

**Configuration:**
- `CONVERSATION_COMPACTION_ENABLED` (default: `true`)
- `CONVERSATION_COMPACTION_THRESHOLD` (default: `30`) — message count above which compaction kicks in
- `CONVERSATION_COMPACTION_KEEP_RECENT` (default: `12`) — recent messages always kept verbatim
- `CONVERSATION_COMPACTION_RESUMMARIZE_BATCH` (default: `10`) — re-summarize cadence

**Testing:** [test_conversation_compaction.py](../../tests/unit/test_conversation_compaction.py)

## LangGraph Agent Graph

The chat agent is implemented as a LangGraph state machine in [graph.py](../../src/agent/graph.py).

### Graph Flow

```
START -> chat -> should_continue -> "tools": tools -> check_tool_results -> chat (loop)
                                 -> "end": END
```

Without tools: `START -> chat -> END`

Multi-step planning is the model's own job (Gemini native thinking; see the
optional `thinking_level` key on `Config.MODELS` entries). The old
classifier + plan-node subsystem was removed in Aug 2026 after telemetry
showed a 1.9% fire rate at 1.6-2.4s added latency — git history has the
implementation if it's ever needed again.

### Self-Correction Node

After tool execution, `check_tool_results()` inspects `ToolMessage` results for errors before returning control to the LLM.

**How it works:**

1. Scans the latest batch of `ToolMessage` objects (stops at the preceding `AIMessage`)
2. Detects errors by checking `status="error"` or content patterns (`"Error:"`, `"Exception:"`, `"Traceback"`, `"failed"`)
3. On error with retries remaining: increments `tool_retries` counter, injects a `SystemMessage` telling the LLM to try a different approach
4. On error after max retries: injects a `SystemMessage` telling the LLM to give up gracefully and explain the issue
5. On success: resets `tool_retries` to 0
6. Always routes back to the `chat` node - the LLM decides the next step

The `ToolNode` is created with `handle_tool_errors=_handle_tool_errors` (a callable, **not** `True`) so ordinary tool exceptions become `ToolMessage` errors rather than crashes, while control-flow exceptions still propagate.

> **Pitfall — never pass `handle_tool_errors=True`.** With `True`, LangGraph's `ToolNode` catches *every* `Exception` subclass and converts it into an error `ToolMessage` (`status="error"`). That silently swallows control-flow exceptions too: `ApprovalRequestedException` (raised by the autonomous-agent approval flow) never reached the executor, so runs *completed* instead of pausing in `waiting_approval`, and self-correction told the model to retry — producing duplicate approval records. The fix is the `_handle_tool_errors(e)` callable in [graph.py](../../src/agent/graph.py): it re-raises `ApprovalRequestedException` and returns the default error-template string for everything else. (LangGraph's own `interrupt()` uses `GraphBubbleUp`, which the framework exempts — the native alternative.)
>
> **Lesson:** when an exception must cross a framework boundary (`ToolNode`, `executor.map`, `graph.stream`), write the regression test through a **real compiled graph**, not a mocked node — tests that mocked `execute_agent` never exercised this propagation boundary, and the `except` in the streaming layer was dead code until the exception actually started arriving. Fixing propagation can also unmask latent bugs in the previously-dead catch paths.

**Configuration:**
- `AGENT_MAX_TOOL_RETRIES`: Max consecutive tool failures before giving up (default: `2`)

### Graph State (no checkpointer)

The chat graph is **stateless across requests**. Every invoke receives the full message list to send (built from the DB history, then compacted — see [Conversation Compaction](#conversation-compaction-cost-control)), so no LangGraph checkpointer is attached.

This is deliberate: `AgentState.messages` uses the `add_messages` reducer, which *appends* input messages to any existing thread state and dedups only by message `id`. Since freshly built history messages have no `id`, attaching a persistent checkpointer keyed by `conversation_id` made every follow-up turn **accumulate and duplicate** the entire history — for regular chat *and* autonomous agents (nothing in the code ever resumed a thread; agent approvals re-run `execute_agent` fresh from the DB). `compile_graph()` therefore just calls `graph.compile()`, and within-request multi-step state (the tool loop) is held in memory during the invoke.

### AgentState Fields

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # Messages for this invoke
    tool_retries: int   # Consecutive tool failure count (reset to 0 on success)
    tool_rounds: int    # Tool-execution rounds this turn (soft cap nudges the model to answer)
```

### Key Files

- [graph.py](../../src/agent/graph.py) - Graph construction, all nodes and routers
- [agent.py](../../src/agent/agent.py) - `ChatAgent`, `stream_chat_events()`, `chat_batch()`
- [config.py](../../src/config.py) - `AGENT_MAX_TOOL_RETRIES`, `AGENT_MAX_TOOL_ROUNDS`

### Testing

- Unit tests: [test_graph.py](../../tests/unit/test_graph.py) - self-correction, planning, and graph structure

## See Also

- [File Handling](file-handling.md) - Image generation, code execution, file uploads
- [UI Features](ui-features.md) - Input toolbar, message sending behavior
- [Memory and Context](memory-and-context.md) - User memories and custom instructions
- [Testing](../testing.md) - E2E tests for chat functionality
