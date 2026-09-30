# Thinking Indicator and Source Chips

What a streaming turn shows while it works (the thinking/tool trace and the retry status) and the source chips attached once it is done. The stream itself is covered in [Chat and Streaming](chat-and-streaming.md).

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
   - `{"type": "retry", "attempt": 2, "max_retries": 3}` - A transient model error (Gemini 503/429) is being retried with backoff - see [Retry Status](#retry-status)
   - `{"type": "token", "text": "..."}` - Regular content tokens
   - `{"type": "final", ...}` - Final result with metadata

2. **SSE forwarding**: the producer thread ([stream_producer.py](../../src/api/helpers/stream_producer.py)) queues them and the consumer ([chat_streaming.py](../../src/api/helpers/chat_streaming.py)) relays them as Server-Sent Events (see [Chat and Streaming](chat-and-streaming.md#streaming-data-flow-components-that-change-together))

3. **Frontend handling**: [stream-events.ts](../../web/src/core/stream-events.ts) parses events and calls:
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

Labels, past-tense labels and icons come from `TOOL_METADATA` in [tool_display.py](../../src/agent/tool_display.py); the detail string from `extract_tool_detail()` (sent as `detail` on `tool_start`). For example:
- `web_search` → "Searching the web" + search query (all queries of a batched call) → "Searched" + query (finalized)
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

### Retry Status

When the chat node retries a transient model error (see
[Agent Graph](../architecture/agent-graph.md#chat-node-and-transient-error-retries)), the
stream carries a `retry` event. `updateStreamingRetryStatus()` in
[messages/streaming.ts](../../web/src/components/messages/streaming.ts) shows "The model is
busy - retrying (attempt N of M)…" in a line next to (not inside) the re-rendered trace,
and `clearStreamingRetryStatus()` removes it as soon as the model makes progress
(thinking, tool call, token) or the turn ends. Without it the backoff (up to ~70 s per
call) looked like a hang. The event is not journaled, so a resumed stream never replays it.

### Gemini Thinking Support

The Gemini API supports a `include_thoughts=True` parameter that returns thinking content in the response. When enabled:
- `ChatGoogleGenerativeAI` is initialized with `include_thoughts=True`
- Response chunks may contain parts with `{'type': 'thinking', 'thinking': "..."}` format
- `extract_thinking_and_text()` separates thinking content from regular text
- Thinking text is accumulated across chunks and emitted as updates
- The backend yields `{"type": "thinking", "text": accumulated_text}` events during streaming

### Key Files

- [agent.py](../../src/agent/agent.py) - `stream_chat_events()`, `ChatAgent` class; [stream_events.py](../../src/agent/stream_events.py) - graph stream to client events
- [content.py](../../src/agent/content.py) - `extract_thinking_and_text()`
- [tool_display.py](../../src/agent/tool_display.py) - `TOOL_METADATA`, `extract_tool_detail()`
- [api.ts](../../web/src/types/api.ts) - `StreamEvent` and `ThinkingState` types
- [ThinkingIndicator.ts](../../web/src/components/ThinkingIndicator.ts) - UI component
- [messages/streaming.ts](../../web/src/components/messages/streaming.ts) - Streaming state management
- [stream-events.ts](../../web/src/core/stream-events.ts) - Event handling ([thinking-state.ts](../../web/src/core/thinking-state.ts) keeps the per-stream trace)
- [thinking.css](../../web/src/styles/components/thinking.css) - Styles and animations

### Testing

- Backend unit tests: `TestExtractThinkingAndText` in [test_content_text.py](../../tests/unit/test_content_text.py)
- Frontend unit tests: [thinking-indicator.test.ts](../../web/tests/unit/thinking-indicator.test.ts), [thinking-state.test.ts](../../web/tests/unit/thinking-state.test.ts), [streaming-retry-status.test.ts](../../web/tests/unit/streaming-retry-status.test.ts)
- Backend: [test_retry_status.py](../../tests/unit/test_retry_status.py), [test_tool_display.py](../../tests/unit/test_tool_display.py)
- E2E tests: "Chat - Thinking Indicator" describe block in [thinking-indicator.spec.ts](../../web/tests/e2e/chat/thinking-indicator.spec.ts)

## Source Chips

When a turn reads web pages, those pages are shown to the user as sources - automatically, with no citation tool.

### How it works

1. **Tool returns JSON**: `web_search` returns `{"query": "...", "results": [{title, url, snippet}, ...]}` instead of plain text (`research`, `fetch_url` and the browser also produce citable pages)
2. **Backend derives sources from what was read**: `extract_read_sources()` in [content.py](../../src/agent/content.py) pairs the turn's tool calls with their results: pages `research` actually fetched (not failed fetches or unfetched candidates; an escalated repeat `web_search`, marked `_escalated`, counts as `research`), successful `fetch_url` calls (titled by URL), `browser` pages, and sources a `delegate_task` subagent returned. A turn that answered from search snippets alone gets the top 5 search results (rank-interleaved) instead. De-duplicated, at most 10.
3. **Why no citation tool (removed Sep 2026)**: there used to be a `cite_sources` tool meant to ride along with the final answer. In production the model sent it WITHOUT answer text in 687 of 869 tool-using turns (79%, 30 days) despite the prompt forbidding exactly that, so the no-op tool ran and the model was called again just to write the answer - ~49M extra input tokens a month, an extra model call of latency, inflated round counts (false "stopped early" notes, eval round-cap failures) - and it forgot to cite in other turns. Trade-off accepted: chips list every page read, not just the ones the answer relied on. (The old text-based `<!-- METADATA: -->` block is long gone too.)
4. **Sources stored in DB**: Messages table has a `sources` column (JSON array)
5. **Sources in API response**: Both batch and streaming responses include `sources` array
6. **Sources in later turns**: `history.py` turns stored sources into a `tool_digest` ("read: Title (url); ...") in the message's `MSG_CONTEXT`, so the model can re-fetch a page it cited earlier
7. **UI shows sources button**: A globe icon appears in message actions when sources exist, opening a popup with clickable links

### Key Files

- [tools/web.py](../../src/agent/tools/web.py) - `web_search()` returns structured JSON
- [content.py](../../src/agent/content.py) - `extract_read_sources()`
- [models/](../../src/db/models/) - `Message.sources` field, `add_message()` with sources param
- [chat_save.py](../../src/api/helpers/chat_save.py) - calls `extract_read_sources()` when saving the turn (batch and streaming); the autonomous executor does the same
- [SourcesPopup.ts](../../web/src/components/SourcesPopup.ts) - Popup component
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Sources button rendering
- [test_read_sources.py](../../tests/unit/test_read_sources.py) - which pages become chips

## See Also

- [Chat and Streaming](chat-and-streaming.md) - the SSE pipeline these events travel through
- [Agent Graph](../architecture/agent-graph.md) - retries and tool rounds behind the trace
- [Conversation Context](../architecture/conversation-context.md) - how sources reach later turns (`tool_digest`)
