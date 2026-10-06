# Agent Graph

The agent loop behind every turn - interactive chat (batch and streaming) and autonomous
agents alike - is a LangGraph state machine in [graph.py](../../src/agent/graph.py),
driven by `ChatAgent` in [agent.py](../../src/agent/agent.py). What the loop is fed
(enriched, possibly compacted history) is covered in
[Conversation Context](conversation-context.md); how its events reach the browser in
[Chat and Streaming](../features/chat-and-streaming.md).

## Graph Flow

```
START -> chat -> should_continue -> "tools": tools -> check_tool_results -> chat (loop)
                                 -> "end": END
```

Without tools: `START -> chat -> END`. `should_continue` also routes to `END` when every
tool call in the model's reply is extract-only (`set_conversation_title`) **and** the reply
already has text - the args are read in post-processing, so executing them would only cost
an extra model round.

Multi-step planning is the model's own job (Gemini native thinking; see the
optional `thinking_level` key on `Config.MODELS` entries). The old
classifier + plan-node subsystem was removed in Aug 2026 after telemetry
showed a 1.9% fire rate at 1.6-2.4s added latency — git history has the
implementation if it's ever needed again.

Compiled graphs are cached per signature (model, tools, thinking, autonomous, context
cache name) in a bounded LRU (`get_compiled_graph()`, `AGENT_GRAPH_CACHE_SIZE`).
Context-cache names rotate when a Gemini cache lapses or is recreated, so each
otherwise-identical signature keeps only its 3 most-recently-used names (the
uncached fallback plus SPORTS and LANGUAGE, which bind the same tools). Without
that cap dead names filled the LRU and each prod worker grew ~200 MB in a day.

## Chat Node and Transient-Error Retries

`chat_node` invokes the model through `with_retry(model.invoke, on_retry=_emit_retry_status)`
([retry.py](../../src/agent/retry.py)). Connection errors, timeouts and rate-limit / 503
responses (`is_transient_error()` walks the exception cause chain, since the Gemini SDK
wraps them) are retried with exponential backoff and jitter, configured by
`AGENT_MAX_RETRIES`, `AGENT_RETRY_BASE_DELAY_SECONDS` and `AGENT_RETRY_MAX_DELAY_SECONDS`.

**A model that is down falls back to the other tier.** A `503 UNAVAILABLE` ("high demand",
`is_model_unavailable()`) is not retried: on Aug 27 2026 Flash returned it for minutes
while Pro was up, and stacked retries (the SDK's own backoff, ~40 s, inside each of
`AGENT_MAX_RETRIES` attempts) kept turns on "Thinking" for ~3 minutes per call. The chat
model's SDK retries are capped at `AGENT_MODEL_SDK_MAX_RETRIES` (1), and `chat_node`
reruns the call on `other_model_tier()` - the other `MODELS` entry, built uncached (the
context cache is per (profile, model)) with the same tools - and stays on it for the
rest of the turn (`AgentState.model_fallback`). The reply's `response_metadata` carries
`model_fallback`, so `usage_info["model_fallback"]` prices the turn at the model that
answered; the stream emits a `model_fallback` event and the batch response a
`model_fallback` field, and the client shows a note ([model-fallback.ts](../../web/src/core/model-fallback.ts)).

Retries are **per model call**, not per turn: replaying a whole turn would re-execute
non-idempotent tools (Todoist/Calendar writes, WhatsApp sends). The autonomous-agent
executor therefore has no retry wrapper of its own.

**Retry status event.** The backoff can add up to ~70 s per call, which looked like a hang.
`_emit_retry_status` writes `{"type": "retry", "attempt", "max_retries"}` to LangGraph's
custom stream; `stream_chat_events()` streams with `stream_mode=["messages", "custom"]`
and forwards it as a `retry` SSE event, shown as "The model is busy - retrying (attempt N
of M)…" in the thinking indicator until the model makes progress (see
[Thinking Indicator](../features/thinking-and-sources.md)). Outside a streaming run there
is no writer and the call is a no-op. `retry` is deliberately **not** journaled for resume
- a momentary status a resumed client has no reason to replay.

Before each model call, tool results the model has already consumed are **aged**
(`_age_consumed_tool_messages`): multimodal content (fetched PDFs/images, screenshots)
becomes a stub and long text is cut to `AGENT_AGED_TOOL_RESULT_MAX_CHARS` (2000), since
every `ToolMessage` is otherwise re-sent on each loop iteration.

## Tool Node

`create_tool_node()` wraps LangGraph's `ToolNode`:

1. **Autonomous agents only**: calls the agent may not use are split out and answered
   with a permission-blocked `ToolMessage` (every `tool_call_id` needs a response or
   Gemini rejects the next turn); `request_approval` runs **after** its batch siblings
   so their results are not lost when it pauses the run
   (see [Agent Tools](../features/agent-tools.md)).
2. Runs the tool calls and logs a `Tool round completed` line with tool
   names, outcomes, result sizes and `elapsed_ms`.
3. `_capture_and_strip_tool_messages` stores each result's `_full_result` (generated
   images, code output files) server-side under the request id and strips it, so the
   model sees ~50 tokens of metadata instead of base64 blobs.

## Self-Correction Node

After tool execution, `check_tool_results()` inspects `ToolMessage` results for errors before returning control to the LLM.

**How it works:**

1. Scans the latest batch of `ToolMessage` objects (stops at the preceding `AIMessage`)
2. Detects errors **structurally** in `_tool_message_error()` ([graph.py](../../src/agent/graph.py)): `status == "error"` (set by the ToolNode exception handler and the permission-blocked path) or a JSON object with a truthy `"error"` key (the envelope every tool returns on failure). It deliberately **never** substring-matches content - matching `"Error:"`/`"failed"` false-positived on legitimate results, e.g. a fetched page that describes a failure. Tools mark permanent failures (integration not configured, invalid action) with `"retriable": false`, which skips pointless retries
3. On a retriable error with retries remaining: increments `tool_retries`, injects guidance telling the LLM to try a different approach
4. On error after max retries (or a non-retriable one): injects guidance telling the LLM to give up gracefully and explain the issue
   - Guidance is a `SystemMessage`, or a `HumanMessage` wrapped in `[SYSTEM GUIDANCE]` markers in cached mode (LangChain drops mid-conversation system messages there)
5. On success: resets `tool_retries` to 0
6. Always routes back to the `chat` node - the LLM decides the next step

The same node also counts tool rounds (see [Tool Round Economics](#tool-round-economics))
and injects **mid-run steering**: a follow-up the user sent while the turn was running
(`POST /api/conversations/<id>/chat/interject`, stored cross-worker in `kv_store` by
[interjection.py](../../src/agent/interjection.py)) is popped here and injected as
guidance before the next round. It is checked first, so a round-cap or nudge early return
can never swallow it.

The `ToolNode` is created with `handle_tool_errors=_handle_tool_errors` (a callable, **not** `True`) so ordinary tool exceptions become `ToolMessage` errors rather than crashes, while control-flow exceptions still propagate.

> **Pitfall — never pass `handle_tool_errors=True`.** With `True`, LangGraph's `ToolNode` catches *every* `Exception` subclass and converts it into an error `ToolMessage` (`status="error"`). That silently swallows control-flow exceptions too: `ApprovalRequestedException` (raised by the autonomous-agent approval flow) never reached the executor, so runs *completed* instead of pausing in `waiting_approval`, and self-correction told the model to retry — producing duplicate approval records. The fix is the `_handle_tool_errors(e)` callable in [graph.py](../../src/agent/graph.py): it re-raises `ApprovalRequestedException` and returns the default error-template string for everything else. (LangGraph's own `interrupt()` uses `GraphBubbleUp`, which the framework exempts — the native alternative.)
>
> **Lesson:** when an exception must cross a framework boundary (`ToolNode`, `executor.map`, `graph.stream`), write the regression test through a **real compiled graph**, not a mocked node — tests that mocked `execute_agent` never exercised this propagation boundary, and the `except` in the streaming layer was dead code until the exception actually started arriving. Fixing propagation can also unmask latent bugs in the previously-dead catch paths.

**Configuration:**
- `AGENT_MAX_TOOL_RETRIES`: Max consecutive tool failures before giving up (default: `2`)

## Graph State (no checkpointer)

The chat graph is **stateless across requests**. Every invoke receives the full message list to send (built from the DB history, then compacted — see [Conversation Compaction](conversation-context.md#conversation-compaction)), so no LangGraph checkpointer is attached.

This is deliberate: `AgentState.messages` uses the `add_messages` reducer, which *appends* input messages to any existing thread state and dedups only by message `id`. Since freshly built history messages have no `id`, attaching a persistent checkpointer keyed by `conversation_id` made every follow-up turn **accumulate and duplicate** the entire history — for regular chat *and* autonomous agents (nothing in the code ever resumed a thread; agent approvals re-run `execute_agent` fresh from the DB). `compile_graph()` therefore just calls `graph.compile()`, and within-request multi-step state (the tool loop) is held in memory during the invoke.

## AgentState Fields

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # Messages for this invoke
    tool_retries: int   # Consecutive tool failure count (reset to 0 on success)
    tool_rounds: int    # Tool-execution rounds this turn (soft cap nudges the model to answer)
```

## Tool Round Economics

Every tool round re-invokes the model with the **entire accumulated conversation**, so wall-clock and cost scale with the number of *rounds*, not the number of tool calls. Five tool calls in one round are near-free relative to five calls across five rounds.

A Sep 2026 audit of 14 days of production logs found the agent doing exactly the wrong thing:

| Finding | Measurement |
|---|---|
| Rounds carrying exactly one tool call | 1,752 of 1,835 (95.5%) |
| `web_search` calls that were solo in their round | 858 of 864 (99%) |
| Turns issuing 2+ separate `web_search` rounds | 207 of 521 |
| Avoidable rounds from un-batched search alone | ~554 |
| `web_search` → `fetch_url` chains (what `research` exists to replace) | 65 |
| Consecutive `kv_store` rounds (get-then-set) | 57 |
| Tool round cap (`AGENT_MAX_TOOL_ROUNDS`) hit | 83 times |
| Turn wall-clock | p50 10s, p90 91s, max 610s |

**The key lesson: prompt-level batching guidance does not work.** Both the system prompt and the `web_search` docstring already told the model to batch queries and prefer `research`; it batched twice in 864 rounds. What works is putting the directive in the **tool result**, which the model reads far more reliably than standing instructions.

Mechanisms now in place:

- **`src/agent/tools/turn_usage.py`** — counts tool calls per turn, keyed by request id (the tool node runs calls on a thread pool, so a contextvar would not survive). Returns 0 without a request context, so evals and unit tests are unaffected.
- **Search escalation** (Sep 30 2026, replacing the Sep 6 `_efficiency` text nudges, which measurably did not move traffic) — from the 2nd single-query `web_search` in a turn, `web_search` runs the query as `research` (search + read the top `WEB_SEARCH_ESCALATE_MAX_SOURCES` pages, default 3) and returns research-shaped JSON with an `_escalated` note pointing at batched `queries=[...]`. It never refuses, so a dependent follow-up search still works. Counted per *call*: the first search and any batched call are unchanged. `fetch_url` still attaches a nudge toward `research` when a search already ran this turn.
- **Composite actions** — `garmin_connect(action="get_readiness_snapshot")` returns readiness + sleep + HRV + stats + training status + recent activities in one concurrent fetch, replacing five sequential calls. `kv_store(action="merge", ...)` deep-merges server-side, replacing get-then-set.
- **Browser batches** — `browser(actions=[...])` runs a known navigate/type/click sequence in one round, and page-changing actions return the page's interactive `elements` with selectors so the next step needs no screenshot/`extract` round (see [Agent Tools](../features/agent-tools.md#batches)). Unlike search escalation this is still steered by the prompt and docstring.
- **Concurrency inside tools** — batched `web_search` queries and Garmin's per-activity breakdowns fan out in a thread pool, so batching does not just trade LLM round-trips for provider round-trips. Garmin sub-fetches run under `copy_context()` because the helpers read conversation contextvars.
- **Session caching** — `garmin.login()` re-fetches profile + settings on every call (two extra HTTP round trips). `src/agent/tools/garmin_session.py` caches the client per user, fingerprinting the stored token on each lookup so a reconnect invalidates every worker immediately; tokens are written back only when garth actually rotates them.
- **Per-round timing** — `Tool round completed` logs tool names, outcomes, result sizes and `elapsed_ms`. Before this, tool latency could only be inferred by diffing timestamps of surrounding LLM calls.

Re-run the audit from the production host's application logs (14+ days), filtering for `LLM requested tool calls` (tool names + count per round) and `Tool round completed` (per-round latency); treat rounds of one request id as one turn.

**Follow-up audit (Sep 29 2026, 30 days).** 173 distinct turns hit the cap - 3.3% of 5,291 turns; after the Sep 6 nudges it settled at 2-5 a day (one 34-turn spike on Sep 26). Inside capped turns 98% of rounds still carried a single tool call, `web_search` dominant (499 calls, then `fetch_url` 83, `browser` 62). Count distinct capped turns by the FIRST cap line (`"tool_rounds": 6`) - the cap message repeats on every later round, so raw line counts overstate it (271 lines for 173 turns).

**Follow-up audit (Sep 30 2026).** Production before the Sep 6 nudges (Aug 26-Sep 6, 12 days) vs after (Sep 7-30, 24 days): single-call rounds 95.6% -> 96.0%; `web_search` turns with 2+ separate search rounds 67% -> 63%; average rounds per tool-using turn 2.68 -> 2.68; cap hits 2.9% -> 3.1% of turns; search -> fetch chains 5.5 -> 4.8 a day. Only the structural change moved: `kv_store` get-then-set pairs 5.2 -> 3.1 a day once `merge` shipped. The text nudges did not change behaviour, hence search escalation. Evals (2 runs after vs 6 before): tool rounds on the 32 tool-using cases -4%; `cz_batched_lookups` 2-6 rounds (avg 4.3, often over its cap of 3) -> 3, 3; `web_lookup_cited` -> 1, 1; `cz_local_lookup` -> 1, 1; the new `dependent_followup_search` case passes; about +6% cost per case from the extra page reads. Re-measure in production after ~14 days with the same method: rounds ≤90 s apart count as one turn, rounds from `LLM requested tool calls` lines, distinct cap hits from `Tool round cap reached` with `tool_rounds == max_rounds`.

**Round cap and nudges.** `check_tool_results` injects a one-time efficiency reminder at `AGENT_TOOL_ROUNDS_SOFT_NUDGE` rounds (default 4) and, from `AGENT_MAX_TOOL_ROUNDS` (default 6) on, guidance to answer with what it has instead of calling more tools. The cap is soft - `AGENT_RECURSION_LIMIT` is the hard backstop.

## Stopped-Early Replies

A turn that hits the cap was told to answer with what it has, so the reply may be partial. It is flagged `stopped_early` - derived from `message_costs.tool_rounds >= AGENT_MAX_TOOL_ROUNDS` (`is_round_capped()` in [api/utils.py](../../src/api/utils.py)), no extra column - on the stream `done` event, the batch response and loaded message lists (`serialize_messages_for_response()`, one query per page). The UI shows "Stopped at the tool-step limit - this answer may be incomplete." with a **Continue** button on the latest reply, which dispatches the existing `message:continue` re-run ([messages/stopped-early.ts](../../web/src/components/messages/stopped-early.ts)).

## Stop Checkpoints

Pressing Stop ends the turn server-side ([cancellation.py](../../src/agent/cancellation.py); flow in [Chat and Streaming](../features/chat-and-streaming.md#stop-streaming)). The turn's `CancelToken` is looked up by request id, and these checkpoints read it:

| Checkpoint | Effect |
|---|---|
| Token loop in `ChatAgent.stream_chat_events` | Stops consuming model output; the text so far becomes the reply and the `final` event carries `stop_reason: "user"` |
| Start of `chat_node`, each retry attempt, and every streamed token of the model call (`CancelOnToken` callback) | No further model call; a running one is aborted mid-stream |
| Start of `check_tool_results` | The round that just finished is the last one |
| `execute_code` (cancel callback) | Kills the running user program in the session container - every process except PID 1 (`docker-init`), its oldest child (the keep-alive command) and the killer, so children and orphans of user code die too; the exec runs on its own daemon thread, never the stop poller. A Stop before the run starts raises `TurnCancelled` (re-raised past the tool's broad `except`) |
| Browser batches (`run_batch`) | No further steps |

The per-token check matters: LangGraph runs nodes on a background executor, and closing the graph stream **waits** for the running node - without aborting inside the node thread, a Stop would block until the model finished (every token billed). `chat_node` merges `CancelOnToken` into its *inherited* callback manager (`_with_cancel_callback`); replacing the callbacks instead drops LangGraph's streaming handler and the model stops streaming. Remaining latency: time to the first token, and a retry backoff already sleeping.

A checkpoint raises `TurnCancelled`. Like `ApprovalRequestedException` it is control flow: `_handle_tool_errors` re-raises it (an error ToolMessage would let the turn continue), and `delegate_task` re-raises it past its broad exception handler, so a subagent's checkpoint ends the parent turn. `stream_chat_events` catches it and finishes the turn normally with the partial text. Autonomous runs and batch mode have no registered token, so every checkpoint is a no-op there. Tools without a checkpoint (search, fetch, integrations) run to completion - bounded by `TOOL_TIMEOUT` - and the next checkpoint ends the turn.

## Key Files

- [graph.py](../../src/agent/graph.py) - graph construction, `chat_node`, `check_tool_results`, tool node, graph cache
- [agent.py](../../src/agent/agent.py) - `ChatAgent`, `stream_chat_events()`, `chat_batch()`
- [retry.py](../../src/agent/retry.py) - `with_retry`, `is_transient_error`
- [interjection.py](../../src/agent/interjection.py) - mid-run steering carrier
- [tools/turn_usage.py](../../src/agent/tools/turn_usage.py) - per-turn tool-call counts behind search escalation and the fetch nudge
- [api/utils.py](../../src/api/utils.py) - `is_round_capped()`
- [messages/stopped-early.ts](../../web/src/components/messages/stopped-early.ts) - stopped-early note + Continue
- [config.py](../../src/config.py) - `AGENT_MAX_TOOL_RETRIES`, `AGENT_MAX_TOOL_ROUNDS`, `AGENT_TOOL_ROUNDS_SOFT_NUDGE`, `AGENT_AGED_TOOL_RESULT_MAX_CHARS`, `AGENT_MAX_RETRIES`, `AGENT_MODEL_SDK_MAX_RETRIES`, `AGENT_RETRY_*`, `WEB_SEARCH_ESCALATE_MAX_SOURCES`

## Testing

- [test_graph.py](../../tests/unit/test_graph.py) - self-correction, routing, graph structure
- [test_retry.py](../../tests/unit/test_retry.py), [test_retry_status.py](../../tests/unit/test_retry_status.py) - backoff and the `retry` event; `web/tests/unit/streaming-retry-status.test.ts` for the UI line
- [test_tool_efficiency.py](../../tests/unit/test_tool_efficiency.py) - fetch nudge, per-call search counting and composite actions
- [test_search_escalation.py](../../tests/unit/test_search_escalation.py) - repeat single-query `web_search` runs as `research`
- [test_stopped_early.py](../../tests/unit/test_stopped_early.py), `web/tests/unit/stopped-early.test.ts` - stopped-early flag and note
- [test_routes_interject.py](../../tests/integration/test_routes_interject.py) - mid-run steering

## See Also

- [Conversation Context](conversation-context.md) - history enrichment and compaction
- [Chat and Streaming](../features/chat-and-streaming.md) - turn setup, SSE pipeline, resume
- [Agent Tools](../features/agent-tools.md) - tool binding, permissions, adding a tool
- [Autonomous Agents](../features/agents.md) - scheduled runs of the same graph
