# Conversation Context

What the model sees of a conversation's past on each turn: enriched history (timestamps, files, tool digests) and, for long chats, a segmented summary in place of older turns. The loop that consumes it is in [Agent Graph](agent-graph.md).

## History Enrichment

Conversation history is enriched with contextual metadata before being sent to the LLM. This helps the model understand temporal context, reference historical files, and know which tools were used.

### Context Format

Each historical message includes a JSON context block in `<!-- MSG_CONTEXT: -->` format, built by `enrich_history()` in [history.py](../../src/agent/history.py) and rendered by `ChatAgent._format_message_with_metadata()`:

```
<!-- MSG_CONTEXT: {"timestamp":"2024-06-15 14:30 CET","files":[{"name":"report.pdf","type":"PDF","id":"msg-abc123:0"}]} -->
Can you analyze this data?
```

Note: The dedicated marker keeps the model from echoing history context in its replies (the old response-side `<!-- METADATA: -->` block is gone - metadata now comes from tool calls, see [Source Chips](../features/thinking-and-sources.md#source-chips)).

Only **stable, message-derived** fields are embedded inline. A recomputed relative time ("3 hours ago") is deliberately omitted because it would change every historical message's serialized bytes on each turn, defeating Gemini's implicit prefix caching of the history. The model derives elapsed time from the absolute `timestamp` plus the current time provided in the dynamic context block. For the same reason, in cached mode the per-request dynamic context (`[CONTEXT]`) is appended at the **tail** (just before the current user message) rather than the head, so the stable history forms a reusable prefix.

### Enrichment Fields

**For all messages:**
- `timestamp` - Absolute timestamp with timezone (e.g., "2024-06-15 14:30 CET")
- `session_gap` - Present when resuming after a gap (e.g., "2 days")

**For user messages:**
- `files` - Array of file metadata with `name`, `type`, and `id` (format: `message_id:file_index`)

**For assistant messages:**
- `tools_used` - Array of tool names used (e.g., `["web_search", "garmin_connect"]`)
- `tool_summary` - Human-readable summary (e.g., "searched 3 web sources, generated 1 image")
- `tool_digest` - Sources the turn read, as "read: Title (url); ..." (enables a precise re-fetch)
- `tool_outputs` - One line per non-web tool call of that turn - see [Tool-Output Digests](#tool-output-digests)
- `grounding` - Claims of that answer the [grounding check](../features/grounding.md) found unsourced, partly sourced or contradicted, with reasons ("unsourced: X (reason); ...", capped by `GROUNDING_CONTEXT_MAX_CHARS`), so a follow-up does not restate them as fact; the history text itself stays clean
- `research` - On a [deep research](../features/deep-research.md) report: "deep research round N: q1; q2; ...", so a follow-up uses the report instead of re-running it

### Tool-Output Digests

A turn's `ToolMessage`s are gone by the next turn: history only carries the assistant's
prose. Web sources survive as the `tool_digest`, but every other tool (Garmin, Todoist,
calendar, `kv_store`, code execution) left nothing, so a follow-up like "what was my HRV
again?" had to re-call the tool. [tool_outputs.py](../../src/agent/tool_outputs.py) keeps a
bounded digest per call:

- **Built at save time**: `save_message_to_db()` ([chat_save.py](../../src/api/helpers/chat_save.py))
  calls `build_tool_outputs(result_messages)` and stores `[{"tool", "args", "result"}]` in
  the `messages.tool_outputs` column (migration
  [0054_add_message_tool_outputs.py](../../migrations/0054_add_message_tool_outputs.py)).
- **Rendered in later turns**: `format_tool_outputs()` turns it into one line per call,
  `tool(args) -> head of result` (e.g. `garmin_connect({"action":"hrv"}) -> {"hrv":62}`),
  in that message's `MSG_CONTEXT`.
- **Bounds**: args cut to 160 chars, each result to 400, the whole line to
  `TOOL_OUTPUTS_MAX_CHARS` (1,500; a final entry notes how many calls were dropped).
  `_full_result`, `_efficiency` and `_degraded` keys are stripped.
- **Excluded tools** (`_EXCLUDED_TOOLS`): web/page tools (covered by the sources digest),
  `generate_image`, recall tools (`search_conversations`, `read_conversation`,
  `search_memory`, `retrieve_file`), `manage_memory`, `request_approval`, and the
  extract-only tools.
- **Deterministic** from persisted data, so the history prefix stays byte-stable for
  caching. Compaction folds it into the summarizer's input (`[Tool results: ...]`) so the
  facts survive summarization.

**Retention trade-off (accepted Sep 2026):** tool results used to be ephemeral; now their
heads are stored with the message and re-sent to the model while the message is in the
verbatim window (then folded into the summary). That includes health metrics (Garmin) and
third-party data such as calendar attendee emails. Untrusted text inside a result (an
invite description, a task title) is likewise re-exposed each turn - `-->` is neutralized
so it cannot break out of the MSG_CONTEXT comment, but its instructions are not. Add a
tool to `_EXCLUDED_TOOLS` if its outputs should stay ephemeral.

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
- [message_content.py](../../src/agent/message_content.py) - `format_message_with_metadata()`; [agent.py](../../src/agent/agent.py) - `_build_messages()`
- [tool_outputs.py](../../src/agent/tool_outputs.py) - `build_tool_outputs()`, `format_tool_outputs()`
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - `prepare_turn()` enriches history; `build_turn_context()` compacts it (both chat modes)
- [config.py](../../src/config.py) - `HISTORY_SESSION_GAP_HOURS` configuration

### Testing

- Unit tests: `TestFormatMessageWithMetadata` in [test_agent_messages.py](../../tests/unit/test_agent_messages.py)
- Unit tests: [test_history.py](../../tests/unit/test_history.py) - comprehensive tests for enrichment functions
- Unit tests: [test_tool_outputs.py](../../tests/unit/test_tool_outputs.py) - digest building, bounds, exclusions

## Conversation Compaction

Long chats re-send their entire history to the LLM on every turn, so cost grows ~O(n²) over a conversation. [conversation_compaction.py](../../src/agent/conversation_compaction.py) bounds the history *sent to the model* on regular (non-agent) conversations by replacing older turns with a running summary while keeping recent turns verbatim.

**Key properties:**
- **Non-destructive** — unlike the autonomous-agent path in [compaction.py](../../src/agent/compaction.py), the full message history stays in the database for display. Only the enriched history handed to the agent is compacted.
- **Segmented, from full text** — the summary is a list of segments ([compaction_segments.py](../../src/agent/compaction_segments.py)). Each batch of `CONVERSATION_COMPACTION_RESUMMARIZE_BATCH` messages is summarized **once**, from full message text (8k chars/message cap), into a segment of ~`CONVERSATION_COMPACTION_SEGMENT_WORDS` words that is appended. Only when the total exceeds `CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS` are two adjacent segments merged — always the pair with the fewest passes (oldest first), so merge depth grows logarithmically. Appending keeps the summary's prefix stable between refreshes (friendly to prefix caching).
- **Lazy & off the request path** — state is persisted in `kv_store` (namespace `conv_compaction`, key = `conversation_id`; DB-backed, safe across gunicorn workers) and refreshed on a background thread; the current turn uses whatever state already exists.
- **Failure-safe** — a failed refresh never drops context (prior segments + the un-summarized middle, or the full history when there is no summary yet) and backs off exponentially (30 min doubling to 1 day, `failures`/`retry_after` in the state) instead of retrying every turn. `run_summary_model` logs the finish/block reason when the model returns no text.
- **Recall fallback** — the summary message ends with `SUMMARY_RECALL_HINT`, and `search_conversations` includes this conversation's *summarized* messages (`summarized_message_ids()`), so exact details the summary dropped stay reachable.

**Why segments (Sep 2026 measurement):** the previous design re-folded a single summary into itself every 10 messages under a 500-word cap and truncated each message to 500 chars — the summarizer saw ~25% of the text it replaced and a 449-message chat had been through ~42 passes. A fact-recall probe on 7 real conversations (facts extracted from sampled exchanges, judged answerable from the summary alone) scored: old design 55%, segments 150 words/1,200 cap 73%, **segments 250 words/2,500 cap 86%** (174 facts). Cost of the chosen budget: ~$0.011 per 10-message refresh and ~3k extra input tokens per compacted turn — roughly +$8–9/month at current usage. The summarizer runs with `thinking_level=LOW` (`run_summary_model`): on 3 of the conversations LOW scored 81–92% vs 74–88% at the API default while cutting summarizer cost ~30% (thinking tokens were ~85% of its output spend).

**Legacy state:** pre-segment `{summary, covered_count[, generation]}` values are served as a single segment and rebuilt from full text (chunked to fit the cap) on the conversation's next turn.

`build_compacted_history(user_id, conversation_id, history)` returns `[summary_message] + uncovered_middle + recent` once the history exceeds the threshold, otherwise the input unchanged. It is called once, from `build_turn_context()` in [chat_turn.py](../../src/api/helpers/chat_turn.py), so batch and streaming turns share it; it is skipped for interactive agent conversations (`is_autonomous`), which use the agent compaction below.

**Configuration:**
- `CONVERSATION_COMPACTION_ENABLED` (default: `true`)
- `CONVERSATION_COMPACTION_THRESHOLD` (default: `30`) — message count above which compaction kicks in
- `CONVERSATION_COMPACTION_KEEP_RECENT` (default: `12`) — recent messages always kept verbatim
- `CONVERSATION_COMPACTION_RESUMMARIZE_BATCH` (default: `10`) — messages per new segment
- `CONVERSATION_COMPACTION_TOKEN_THRESHOLD` (default: `60000`) — estimated-token trigger
- `CONVERSATION_COMPACTION_SEGMENT_WORDS` (default: `250`) / `CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS` (default: `2500`) — segment size and total cap (the per-turn cost knob)

**Depth tracking & UI:** the state is `{segments: [{text, end, passes}], covered_count}`; the displayed depth (`generation`) is the deepest segment's `passes`. Legacy states report their recorded or estimated generation (`generation_estimated`) until rebuilt. `get_compaction_status()` mirrors `build_compacted_history`'s gating without side effects and backs `GET /api/conversations/<id>/compaction` ([routes/costs.py](../../src/api/routes/costs.py)): whether the next turn is compacted, how many leading messages the summary replaces (`boundary_message_id` = the last one), the depth and the summary text. The frontend shows it as a header chip, an in-list divider and a popup (see [Compaction indicator](../ui/components.md#compaction-indicator)). The summary refreshes in the background, so right after a batch boundary the indicator can show the previous state until the chip next refreshes (end of the following turn or reload).

**Testing:** [test_conversation_compaction.py](../../tests/unit/test_conversation_compaction.py), [test_compaction_segments.py](../../tests/unit/test_compaction_segments.py), [test_conversation_search_tool.py](../../tests/unit/test_conversation_search_tool.py) (summarized-part search), [test_routes_costs.py](../../tests/integration/test_routes_costs.py) (route), `web/tests/unit/compaction-indicator.test.ts`, `web/tests/e2e/compaction.spec.ts` (`/test/seed` accepts a per-conversation `compaction` state).

## Autonomous-Agent Compaction

Scheduled agents append to one conversation forever and can accumulate many messages over time, potentially exceeding LLM context limits. Compaction automatically summarizes older messages to keep conversations manageable.

**How it works:**
1. Before each execution, check if message count exceeds `AGENT_COMPACTION_THRESHOLD` (default: 50)
2. If over threshold, summarize the older messages with the **segmented** summarizer shared with regular chats ([compaction_segments.py](../../src/agent/compaction_segments.py)): the previous compaction's `[Previous conversation summary]` message is kept verbatim as the first segment, and only the messages after it are summarized - from full text, in batches, with agent framing (`Trigger`/`Agent` labels, agent name and description). Segments merge only past `CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS`. (Previously the prior summary was re-folded into one new summary each time, compounding the loss.)
3. Replace old messages with a single summary message (the rendered segments)
4. Keep the most recent `AGENT_COMPACTION_KEEP_RECENT` messages (default: 10)
5. If summarization fails, compaction is **skipped** (messages kept, retried next run) - it used to delete them behind a placeholder "history was compacted" text

The summary captures:
- Key actions taken by the agent
- Important information discovered
- Ongoing tasks or goals
- Any errors or issues encountered

Unlike chat compaction this path is **destructive** - the summarized messages are replaced
in the database - and runs in the executor before each run
(`compact_conversation()` in [compaction.py](../../src/agent/compaction.py)). Both paths
share `run_summary_model()` and the segment helpers.

## Key Files

- [history.py](../../src/agent/history.py) - `enrich_history()`
- [tool_outputs.py](../../src/agent/tool_outputs.py) - tool-output digests
- [conversation_compaction.py](../../src/agent/conversation_compaction.py) - chat compaction, `build_compacted_history()`, `get_compaction_status()`
- [compaction_segments.py](../../src/agent/compaction_segments.py) - segment summarize / merge / render
- [compaction.py](../../src/agent/compaction.py) - agent compaction, `run_summary_model()`
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - where both are applied to a turn

## See Also

- [Agent Graph](agent-graph.md) - the loop that consumes this history
- [Memory and Context](../features/memory-and-context.md) - memories, custom instructions, user context in the prompt
- [Compaction indicator](../ui/components.md#compaction-indicator) - header chip, divider, popup
- [Cost Tracking](../features/cost-tracking.md) - what compaction saves
