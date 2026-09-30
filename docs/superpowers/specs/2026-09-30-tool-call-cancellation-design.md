# Server-side Stop (turn and tool-call cancellation) - Design

Status: approved design, Sep 30 2026. Replaces the TODO item "Server-side tool-call cancellation".

## Problem

Stop is client-side only. Clicking it aborts the SSE reader and removes the streaming
message from the DOM, but the server keeps running the whole turn - further LLM calls,
tool rounds, a 30 s `execute_code` - is billed for all of it, and saves the complete
reply, which then appears after a reload. Observed: a `sleep 30` sandbox run completed
after Stop.

## Goal and success criteria

Stop behaves like Claude Desktop: the turn ends within about a second, the text produced
so far is kept with a "Stopped" note and a **Continue** action, and no further work is
billed.

- Stop during token streaming: no more tokens are consumed; the saved message equals the
  streamed text.
- Stop between tool rounds: no new LLM call or tool round starts.
- Stop during `execute_code`: the sandbox process is killed within ~1 s; the session
  container and `/work` survive.
- Stop during a browser batch: no further steps run.
- Stop during `delegate_task`: the subagent stops at its next checkpoint.
- Other tools (search, fetch, integrations) finish (bounded by `TOOL_TIMEOUT`); their
  results are discarded.
- Reloading shows the same partial message the user saw, never the "full" reply.

Non-goals: interrupting a Playwright call or an HTTP request mid-flight; cancelling
autonomous-agent runs (they have no Stop button); changing interjection semantics.

## Design

### 1. Signal

- New route `POST /api/conversations/<conv_id>/chat/stop` (auth, chat rate limit, 404 for
  a foreign conversation). It writes kv flag namespace `cancel`, key `conv_id` - the same
  cross-worker carrier as interjections (`src/agent/interjection.py`), because the POST
  may land on a different gunicorn worker than the one running the turn. One active
  request per conversation (frontend double-send guard) makes the key unambiguous.
- The flag is cleared at turn start (a Stop that arrived after the previous turn ended
  must not cancel the next one) and at turn end.
- The worker running the turn creates a `CancelToken` (new module
  `src/agent/cancellation.py`): a `threading.Event`, a list of kill callbacks, and a
  registry keyed by `request_id` (`get_current_request_id()` is already available inside
  tools and graph nodes, avoiding a new contextvar that would need forwarding into the
  producer thread - see docs/features/agent-tools.md "Three layers").
- A poller thread per active turn reads the kv flag every
  `CANCEL_POLL_INTERVAL_SECONDS` (0.5) and, when set, sets the event and runs the kill
  callbacks once. Checkpoints only read the event (no DB access on the hot path). The
  poller stops when the turn ends.

### 2. Checkpoints

A checkpoint that sees the event raises `TurnCancelled` (new exception).

| Where | Behavior |
|---|---|
| Token stream loop in `ChatAgent.stream_chat_events` | Stop consuming chunks; the accumulated text is the partial reply |
| `check_tool_results`, and on entry to `chat_node` | No new round starts |
| `execute_code` | Registers a kill callback for the duration of `session.run`: `container.exec_run(["pkill", "-KILL", "-f", "/sandbox/"], user="root")`. `run` returns (exit 137); the tool reports "stopped by user", then the next checkpoint raises |
| Browser batch (`run_batch`) | Checks the event before each step; stops like a failed step |
| `delegate_task` | Its subagent graph passes the same checkpoints (it runs under the parent's request id - verify during implementation, pass the token explicitly if not) |
| Other tools | Run to completion; the next checkpoint raises |

`_handle_tool_errors` must re-raise `TurnCancelled` (same rule as
`ApprovalRequestedException`) - otherwise it becomes an error ToolMessage and the turn
continues.

### 3. Finalize

- The stream producer (`src/api/helpers/stream_producer.py`) catches `TurnCancelled` and
  finalizes through the normal save path with the partial content, so sources, usage and
  cost recording stay consistent. Cost covers tokens actually used.
- New optional field `stop_reason: "round_cap" | "user"` on the `done` event and the
  message payload (schemas in `src/api/schemas/chat.py`, `src/api/utils.py`).
  `stopped_early` keeps meaning the round cap, so existing clients and tests are
  untouched. Persisted like `stopped_early` today.
- Empty partial (stopped before any text): save "Stopped before answering." so the turn
  stays visible and Continue works.
- The resume journal gets a terminal marker as for any finished turn, so a resuming
  client receives the `done` event.

### 4. Frontend

- Stop sends `POST .../chat/stop` (fire-and-forget) and keeps reading the stream. The
  server ends the turn and sends `done` with `stop_reason: "user"`; the message renders
  with the existing stopped-early note, labelled "Stopped", whose **Continue** dispatches
  the existing `rerun_mode: "continue"`.
- Fallback: no `done` within `STOP_DONE_GRACE_MS` (5000) -> abort the reader as today
  (`handleUserStop`), without removing the partial message; sync loads the saved message
  later.
- The "Response stopped." toast stays.

## Error handling

- `/stop` for a conversation with no running turn: 200, flag cleared at the next turn
  start (harmless).
- kv read failure in the poller: log and retry at the next interval; never breaks the
  turn.
- Kill callback failure: logged; the tool finishes on its own timeout; the next
  checkpoint still stops the turn.

## Testing

- Unit: `CancelToken` + poller (flag -> event -> callbacks once; stop on turn end);
  `TurnCancelled` raised at each checkpoint; `_handle_tool_errors` re-raises it;
  `run_batch` stops between steps; producer saves the partial with `stop_reason`;
  flag cleared at turn start and end.
- Integration: live sandbox `sleep 30` killed within ~1 s with `/work` preserved (skips
  without Docker); `/stop` route auth/404 and kv lifecycle.
- E2E (mock server): Stop mid-stream -> partial message with "Stopped · Continue";
  reload shows the same message; Continue resumes. Desktop and mobile.

## Rollout

Backend and frontend ship together. An old client never calls `/stop`, so it keeps
today's behavior.
