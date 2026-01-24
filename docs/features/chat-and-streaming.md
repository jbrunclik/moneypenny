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

### Stream Recovery with Pre-Generated Message ID

When streaming responses, the connection can drop mid-stream (network issues, proxy timeouts, client disconnects). To handle this gracefully, we use a pre-generated message ID system:

**How it works:**

1. **Pre-generate ID on server**: When a stream starts, `_StreamContext` generates a UUID (`expected_assistant_msg_id`) for the assistant message
2. **Send ID early**: The ID is included in the `user_message_saved` SSE event, sent at the very start of streaming
3. **Frontend stores ID**: The frontend captures this ID in `StreamingState.expectedAssistantMessageId`
4. **Message saved with known ID**: When the message is saved to DB, it uses this pre-generated ID (not a new one)
5. **Recovery on failure**: If the stream ends without a `done` event, the frontend can fetch the specific message by its known ID

**Why pre-generated IDs?**

Without a known ID, the frontend would have to fetch "recent messages" and guess which one is the response - creating race conditions if:
- Another message arrives (from another tab/device)
- The user quickly sends another message
- Multiple streams complete around the same time

With pre-generated IDs, recovery is deterministic - we fetch exactly the message we expect.

**Recovery flow:**

```
Stream starts → user_message_saved event (includes expected_assistant_message_id)
     ↓
[Connection drops during thinking/tokens]
     ↓
Stream ends without done event
     ↓
Frontend detects missing done event
     ↓
Frontend calls GET /api/messages/{expected_assistant_message_id}
     ↓
If found: Display recovered message
If not found: Show incomplete indicator (message may not have been saved)
```

**Key files:**
- [chat_streaming.py](../../src/api/helpers/chat_streaming.py) - `_StreamContext.expected_assistant_msg_id`, `_yield_user_message_saved()`
- [messaging.ts](../../web/src/core/messaging.ts) - `handleMissingDoneEvent()`, `StreamingState.expectedAssistantMessageId`
- [conversations.py](../../src/api/routes/conversations.py) - `GET /api/messages/<message_id>` endpoint

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

### Metadata Format

Each historical message includes a JSON metadata block using the same `<!-- METADATA: -->` format as assistant response metadata:

```
<!-- METADATA: {"timestamp":"2024-06-15 14:30 CET","relative_time":"3 hours ago","files":[{"name":"report.pdf","type":"PDF","id":"msg-abc123:0"}]} -->
Can you analyze this data?
```

### Enrichment Fields

**For all messages:**
- `timestamp` - Absolute timestamp with timezone (e.g., "2024-06-15 14:30 CET")
- `relative_time` - Human-readable relative time (e.g., "3 hours ago")
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

## See Also

- [File Handling](file-handling.md) - Image generation, code execution, file uploads
- [UI Features](ui-features.md) - Input toolbar, message sending behavior
- [Memory and Context](memory-and-context.md) - User memories and custom instructions
- [Testing](../testing.md) - E2E tests for chat functionality
