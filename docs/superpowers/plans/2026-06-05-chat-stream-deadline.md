# Chat-stream Request Deadline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the duration of an interactive `chat/stream` turn at the application layer, persisting partial content and notifying the client on timeout, so a long/hung agent run can no longer occupy a gthread worker thread indefinitely.

**Architecture:** Defense-in-depth using two enforcement points that share `Config.CHAT_TIMEOUT` (wall-clock via `time.monotonic()`): (1) the **producer** thread (`stream_events`) breaks the agent loop when the deadline passes, stopping the agent and freeing the producer thread; (2) the **consumer** generator (`_process_event_queue`, the gthread worker thread) enforces a slightly-higher backstop deadline that guarantees the worker thread is freed and partial streamed content is saved even if the producer is wedged. Partial content is accumulated from `token` events in the consumer and persisted by reusing the existing save machinery.

**Tech Stack:** Python 3.13/3.14, Flask, gunicorn (gthread), pytest. All changes in `src/api/helpers/chat_streaming.py`, `src/config.py`, `.env.example`, plus a new unit test file.

**Spec:** `docs/superpowers/specs/2026-06-05-chat-stream-deadline-design.md`

---

## File Structure

- **Modify** `src/api/helpers/chat_streaming.py` — add `time` import + `STREAM_TIMEOUT_MARKER` constant; add `partial_content` field to `_StreamContext`; producer deadline in `stream_events`; consumer backstop + timeout-marker handling in `_process_event_queue`; token accumulation in `_handle_queue_event`; new `_handle_stream_timeout` helper.
- **Modify** `src/config.py` — repurpose dead `CHAT_TIMEOUT` (default `300`→`600`), update comment.
- **Modify** `.env.example` — document `CHAT_TIMEOUT` as the enforced chat-turn deadline.
- **Create** `tests/unit/test_chat_streaming_timeout.py` — unit tests for producer/consumer deadline behavior.

All edits are auto-formatted by the repo's PostToolUse hook (ruff). **Pitfall:** the hook strips imports that aren't yet used at edit time — add an import in the SAME edit that introduces its first use, or it will be removed.

---

## Task 1: Producer cooperative deadline (`stream_events`)

**Files:**
- Modify: `src/api/helpers/chat_streaming.py` (imports ~line 9; `stream_events` loop ~lines 431–466)
- Test: `tests/unit/test_chat_streaming_timeout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_chat_streaming_timeout.py`:

```python
"""Unit tests for the chat-stream request deadline (CHAT_TIMEOUT)."""

import queue

from src.api.helpers.chat_streaming import stream_events
from src.config import Config


class _ForeverAgent:
    """Fake ChatAgent whose stream_chat_events never finishes on its own."""

    def stream_chat_events(self, *args, **kwargs):
        i = 0
        while True:
            i += 1
            yield {"type": "token", "text": f"t{i}"}


def _drain(q: queue.Queue) -> list:
    items = []
    while True:
        item = q.get_nowait()
        items.append(item)
        if item is None:
            break
    return items


def test_stream_events_breaks_at_deadline(monkeypatch) -> None:
    """Producer must stop iterating the agent once CHAT_TIMEOUT passes and
    signal a timeout marker followed by the completion sentinel."""
    monkeypatch.setattr(Config, "CHAT_TIMEOUT", 0)  # deadline already passed
    q: queue.Queue = queue.Queue()
    final_results: dict = {"ready": False, "saved": False}

    stream_events(
        _ForeverAgent(), q, final_results,
        "hello", None, [], None,
        "Alice", "user-1", None, False, None,
        "conv-1", "req-1",
    )

    items = _drain(q)
    assert {"type": "timeout"} in items
    assert items[-1] is None
    assert any(isinstance(x, dict) and x.get("type") == "token" for x in items)
    assert final_results["ready"] is False  # no final event arrived
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_chat_streaming_timeout.py::test_stream_events_breaks_at_deadline -v`
Expected: FAIL — the `_ForeverAgent` generator runs forever, so the test hangs/times out (no deadline logic yet). Use a pytest timeout or Ctrl-C to confirm it does not pass.

- [ ] **Step 3: Add the `time` import**

In `src/api/helpers/chat_streaming.py`, change the import block (top of file):

```python
import json
import queue
import threading
import time
import uuid
```

- [ ] **Step 4: Implement the producer deadline**

In `stream_events`, replace the agent-iteration block (currently lines ~431–466, from `event_count = 0` through `event_queue.put(None)  # Signal completion`) with:

```python
        event_count = 0
        deadline = time.monotonic() + Config.CHAT_TIMEOUT
        timed_out = False
        gen = agent.stream_chat_events(
            message_text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
            conversation_id=conversation_id,
            is_sports=is_sports,
            sports_context=sports_context,
            is_language=is_language,
            language_context=language_context,
        )
        try:
            for event in gen:
                event_count += 1
                if event.get("type") == "final":
                    # Store final results for cleanup thread
                    final_results["clean_content"] = event.get("content", "")
                    final_results["result_messages"] = event.get("result_messages", [])
                    final_results["tool_results"] = event.get("tool_results", [])
                    final_results["usage_info"] = event.get("usage_info", {})
                    final_results["ready"] = True
                event_queue.put(event)
                if not final_results["ready"] and time.monotonic() > deadline:
                    timed_out = True
                    logger.warning(
                        "Chat stream exceeded CHAT_TIMEOUT; stopping agent",
                        extra={
                            "user_id": user_id,
                            "conversation_id": conv_id,
                            "timeout_seconds": Config.CHAT_TIMEOUT,
                            "event_count": event_count,
                        },
                    )
                    break
        finally:
            # Cooperatively stop the agent generator (raises GeneratorExit at its
            # current yield point). Idempotent / safe after normal exhaustion.
            gen.close()

        if timed_out:
            event_queue.put({"type": "timeout"})

        logger.debug(
            "Stream thread completed",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "event_count": event_count,
            },
        )

        event_queue.put(None)  # Signal completion
```

- [ ] **Step 5: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_chat_streaming_timeout.py::test_stream_events_breaks_at_deadline -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/helpers/chat_streaming.py tests/unit/test_chat_streaming_timeout.py
git commit -m "feat(stream): producer-side CHAT_TIMEOUT deadline stops the agent"
```

---

## Task 2: Consumer token accumulation, backstop deadline, and timeout handling

**Files:**
- Modify: `src/api/helpers/chat_streaming.py` (`STREAM_TIMEOUT_MARKER` constant near `logger`; `_StreamContext.__init__` ~line 714; `_process_event_queue` ~lines 992–1008; `_handle_queue_event` ~lines 1066–1070; new `_handle_stream_timeout`)
- Test: `tests/unit/test_chat_streaming_timeout.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_chat_streaming_timeout.py`:

```python
import time
import types

from src.api.helpers.chat_streaming import (
    STREAM_TIMEOUT_MARKER,
    _handle_queue_event,
    _process_event_queue,
)


def _make_ctx(items=()) -> types.SimpleNamespace:
    """Minimal stand-in for _StreamContext for consumer-path tests."""
    q: queue.Queue = queue.Queue()
    for it in items:
        q.put(it)
    ctx = types.SimpleNamespace(
        event_queue=q,
        partial_content="",
        clean_content="",
        result_messages=[],
        tool_results=[],
        usage_info={},
        final_results={"ready": False, "saved": False},
        user_id="user-1",
        conv_id="conv-1",
        client_connected=True,
    )
    ctx.mark_disconnected = lambda error, where: None
    return ctx


def test_handle_queue_event_accumulates_token_text() -> None:
    ctx = _make_ctx()
    list(_handle_queue_event(ctx, {"type": "token", "text": "hel"}))
    list(_handle_queue_event(ctx, {"type": "token", "text": "lo"}))
    assert ctx.partial_content == "hello"


def test_consumer_handles_producer_timeout_marker() -> None:
    """Tokens then a {'type':'timeout'} marker -> partial content saved + event."""
    ctx = _make_ctx(
        [
            {"type": "token", "text": "partial "},
            {"type": "token", "text": "answer"},
            {"type": "timeout"},
        ]
    )
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' in out
    assert ctx.clean_content == "partial answer" + STREAM_TIMEOUT_MARKER
    assert ctx.final_results["ready"] is True
    assert ctx.final_results["clean_content"] == ctx.clean_content


def test_consumer_backstop_fires_with_no_events(monkeypatch) -> None:
    """Empty queue + passed deadline -> emits timeout and returns (no hang)."""
    monkeypatch.setattr(Config, "CHAT_TIMEOUT", 0)
    monkeypatch.setattr(Config, "SSE_KEEPALIVE_INTERVAL", 0.05)
    ctx = _make_ctx()  # empty queue
    started = time.monotonic()
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' in out
    assert time.monotonic() - started < 2.0  # terminated promptly
    assert ctx.clean_content == ""  # no partial content to save


def test_consumer_normal_completion_no_timeout() -> None:
    """token -> final -> None completes normally with no timeout event."""
    ctx = _make_ctx(
        [
            {"type": "token", "text": "full "},
            {"type": "final", "content": "full answer", "result_messages": [],
             "tool_results": [], "usage_info": {}},
            None,
        ]
    )
    out = "".join(_process_event_queue(ctx))
    assert '"type": "timeout"' not in out
    assert ctx.clean_content == "full answer"
    assert ctx.final_results["ready"] is False  # consumer doesn't set ready on normal path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_chat_streaming_timeout.py -v`
Expected: FAIL — `ImportError: cannot import name 'STREAM_TIMEOUT_MARKER'` / `_handle_stream_timeout` not defined and timeout handling absent.

- [ ] **Step 3: Add the marker constant**

In `src/api/helpers/chat_streaming.py`, immediately after `logger = get_logger(__name__)`:

```python
# Appended to partial content when an interactive chat turn hits CHAT_TIMEOUT.
STREAM_TIMEOUT_MARKER = "\n\n_…(response timed out)_"
```

- [ ] **Step 4: Add the `partial_content` field**

In `_StreamContext.__init__`, directly after `self.clean_content = ""` (line ~714):

```python
        self.clean_content = ""
        # Streamed token text accumulated for partial-save on timeout.
        self.partial_content = ""
```

- [ ] **Step 5: Accumulate token text in `_handle_queue_event`**

In `_handle_queue_event`, replace the `thinking/tool_start/tool_end/token` branch (lines ~1066–1070):

```python
    elif event_type in ("thinking", "tool_start", "tool_end", "token"):
        if event_type == "token":
            context.partial_content += item.get("text", "")
        try:
            yield f"data: {json.dumps(item)}\n\n"
        except (BrokenPipeError, ConnectionError, OSError) as e:
            context.mark_disconnected(e, f"streaming ({event_type})")
```

- [ ] **Step 6: Add the `_handle_stream_timeout` helper**

In `src/api/helpers/chat_streaming.py`, add directly above `_process_event_queue`:

```python
def _handle_stream_timeout(context: _StreamContext) -> Generator[str]:
    """Persist partial streamed content and emit a timeout event to the client.

    Populates both the generator-side (context.*) and cleanup-thread-side
    (final_results[*]) save inputs so whichever path saves keeps the partial
    text. If no content streamed yet, saves nothing (placeholder is deleted by
    generate()'s finally).
    """
    logger.warning(
        "Chat stream timed out",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "timeout_seconds": Config.CHAT_TIMEOUT,
            "partial_chars": len(context.partial_content),
        },
    )
    if context.partial_content:
        context.clean_content = context.partial_content + STREAM_TIMEOUT_MARKER
        context.final_results["clean_content"] = context.clean_content
        context.final_results["ready"] = True

    event_data = {"type": "timeout", "message": "Response timed out before completing."}
    try:
        yield f"data: {json.dumps(event_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        context.mark_disconnected(e, "streaming (timeout)")
```

- [ ] **Step 7: Add the consumer backstop deadline**

Replace the entire body of `_process_event_queue` (lines ~992–1008):

```python
def _process_event_queue(context: _StreamContext) -> Generator[str]:
    """Process events from the queue and yield SSE data.

    Enforces a backstop deadline (CHAT_TIMEOUT + one keepalive interval of grace
    so the producer's own deadline normally fires first). The grace ensures the
    worker thread is freed and partial content saved even if the producer is
    wedged inside a single non-yielding call.
    """
    deadline = time.monotonic() + Config.CHAT_TIMEOUT + Config.SSE_KEEPALIVE_INTERVAL
    while True:
        if time.monotonic() > deadline:
            yield from _handle_stream_timeout(context)
            break
        try:
            item = context.event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL)

            if item is None:
                break
            elif isinstance(item, Exception):
                yield from _handle_queue_error(context, item)
                return
            elif isinstance(item, dict):
                if item.get("type") == "timeout":
                    yield from _handle_stream_timeout(context)
                    break
                yield from _handle_queue_event(context, item)

        except queue.Empty:
            yield from _send_keepalive(context)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_chat_streaming_timeout.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 9: Commit**

```bash
git add src/api/helpers/chat_streaming.py tests/unit/test_chat_streaming_timeout.py
git commit -m "feat(stream): consumer backstop deadline saves partial content on timeout"
```

---

## Task 3: Config default + documentation

**Files:**
- Modify: `src/config.py:59`
- Modify: `.env.example` (Gunicorn/timeout section)

- [ ] **Step 1: Update `CHAT_TIMEOUT` default and comment**

In `src/config.py`, replace line 59:

```python
    # Hard deadline for a single interactive chat turn (chat/stream). Enforced in
    # src/api/helpers/chat_streaming.py. Should be <= GUNICORN_TIMEOUT so the app
    # aborts gracefully (saving partial content) before gunicorn acts.
    CHAT_TIMEOUT: int = int(os.getenv("CHAT_TIMEOUT", "600"))  # 10 minutes
```

- [ ] **Step 2: Document in `.env.example`**

In `.env.example`, find the `GUNICORN_TIMEOUT=300` block and add immediately after it:

```bash
# Interactive chat-turn deadline in seconds (default: 600 = 10 minutes).
# Hard cap on a single chat/stream turn, enforced in the app. On timeout the
# partial response is saved and the client gets a "timeout" event. Keep this
# <= GUNICORN_TIMEOUT so the app aborts gracefully before gunicorn intervenes.
CHAT_TIMEOUT=600
```

- [ ] **Step 3: Verify config imports cleanly**

Run: `source .venv/bin/activate && python -c "from src.config import Config; print(Config.CHAT_TIMEOUT)"`
Expected: prints `600`

- [ ] **Step 4: Commit**

```bash
git add src/config.py .env.example
git commit -m "feat(config): enforce CHAT_TIMEOUT as chat-turn deadline (default 600s)"
```

---

## Task 4: End-to-end integration test (timeout saves partial message)

**Files:**
- Modify: `tests/integration/test_routes_chat.py` (add one test in the streaming test class)

This confirms the full route persists partial content and emits a `timeout` event, exercising the real `_StreamContext`, threads, and save path.

- [ ] **Step 1: Inspect an existing streaming test for fixtures/setup**

Run: `source .venv/bin/activate && sed -n '512,645p' tests/integration/test_routes_chat.py`
Expected: shows a streaming test using `mock_agent.stream_chat_events = mock_stream_events` and the `client`, `auth_headers`, `test_conversation` fixtures. Mirror its fixtures and patch target exactly.

- [ ] **Step 2: Write the failing test**

Add this test to the same class that contains `test_streaming_chat_with_generated_image` (mirror that test's imports, fixtures, decorators, and the patch target it uses for `ChatAgent`). Replace `<PATCH_TARGET_FOR_ChatAgent>` with the exact target that test uses (e.g. `src.api.helpers.chat_streaming.ChatAgent`):

```python
    def test_stream_saves_partial_content_on_timeout(
        self, client, auth_headers, test_conversation, monkeypatch
    ):
        """When CHAT_TIMEOUT trips mid-stream, the partial text is persisted
        with the timeout marker and a 'timeout' event is sent."""
        from src.config import Config
        from src.api.helpers.chat_streaming import STREAM_TIMEOUT_MARKER

        monkeypatch.setattr(Config, "CHAT_TIMEOUT", 0)  # trip after first event

        def mock_stream_events(*args, **kwargs):
            yield {"type": "token", "text": "partial reply"}
            # Would continue, but the producer deadline (0s) stops it here.
            while True:
                yield {"type": "token", "text": " more"}

        with patch("<PATCH_TARGET_FOR_ChatAgent>") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_agent.stream_chat_events = mock_stream_events

            resp = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                json={"message": "hi"},
                headers=auth_headers,
            )
            body = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert '"type": "timeout"' in body

        # The saved assistant message keeps the partial text + marker.
        from src.db.models import db

        messages = db.get_messages(test_conversation.id)
        assistant = [m for m in messages if m.role == "assistant"]
        assert assistant, "expected a persisted assistant message"
        assert assistant[-1].content.startswith("partial reply")
        assert assistant[-1].content.endswith(STREAM_TIMEOUT_MARKER)
```

> Note: adjust `db.get_messages(...)` and the `auth_headers`/`test_conversation` fixture names to match the conventions actually used in `test_routes_chat.py` (confirm in Step 1). The assertion contract (status 200, `timeout` event present, partial text + marker persisted) must not change.

- [ ] **Step 3: Run test to verify it fails (before Tasks 1–3) or passes (after)**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_routes_chat.py -k timeout -v`
Expected: PASS once Tasks 1–3 are implemented. If you run it before implementation, it FAILS (no `timeout` event, no marker).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_routes_chat.py
git commit -m "test(stream): e2e timeout persists partial assistant message"
```

---

## Task 5: Full verification + TODO update

**Files:**
- Modify: `TODO.md` (mark the app-level deadline item done)

- [ ] **Step 1: Run lint**

Run: `source .venv/bin/activate && make lint`
Expected: ruff + mypy + eslint all pass. Fix any issues before continuing.

- [ ] **Step 2: Run the full backend test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass (the prior baseline was 1457 passed, 1 skipped, plus the new tests).

- [ ] **Step 3: Smoke-test the real app under gthread**

Run:
```bash
source .venv/bin/activate
PORT=8796 GEMINI_API_KEY="${GEMINI_API_KEY:-test-key-placeholder}" \
  gunicorn --bind 127.0.0.1:8796 --workers 1 --worker-class gthread --threads 8 \
  --timeout 60 "src.app:create_app()" > /tmp/deadline_smoke.log 2>&1 &
sleep 6
curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8796/api/health
kill %1 2>/dev/null
grep -iE "Using worker|Error|Traceback" /tmp/deadline_smoke.log | head
```
Expected: `health=200`, `Using worker: gthread`, no tracebacks.

- [ ] **Step 4: Mark the TODO item done**

In `TODO.md`, change the item that begins `**App-level request deadline now load-bearing under gthread**` to `[x]` and append a short DONE note: enforced `CHAT_TIMEOUT` (default 600s) at producer + consumer with partial-save on timeout; reference this plan.

- [ ] **Step 5: Commit**

```bash
git add TODO.md
git commit -m "docs(todo): mark app-level chat-stream deadline done"
```

---

## Self-Review

**Spec coverage:**
- 600s configurable default → Task 3. ✓
- Save partial + notify → Task 2 (`_handle_stream_timeout`, token accumulation) + Task 4 (e2e). ✓
- Producer cooperative deadline → Task 1. ✓
- Consumer backstop deadline → Task 2. ✓
- Reuse existing save machinery (populate `final_results`/`context.*`) → Task 2 Step 6. ✓
- New `timeout` SSE event → Task 2. ✓
- Empty partial → save nothing → Task 2 (`test_consumer_backstop_fires_with_no_events`) + existing `generate()` finally. ✓
- Normal completion unchanged → Task 2 (`test_consumer_normal_completion_no_timeout`) + Task 5 full suite. ✓
- Approval path not disturbed → the producer deadline check is gated on `not final_results["ready"]` and the approval path puts an `approval_required` event then returns; deadline only breaks the agent loop, and `_handle_stream_timeout` is only invoked on the `timeout` marker / backstop. Full suite (Task 5) covers the approval tests.

**Placeholder scan:** One intentional placeholder `<PATCH_TARGET_FOR_ChatAgent>` in Task 4 with explicit Step-1 instructions to resolve it from the existing test; the assertion contract is fully specified. No other placeholders.

**Type consistency:** `STREAM_TIMEOUT_MARKER` (str), `context.partial_content` (str), `final_results["ready"]` (bool), `{"type": "timeout"}` event shape, and `_handle_stream_timeout(context) -> Generator[str]` are used identically across Tasks 1, 2, and 4. `Config.CHAT_TIMEOUT` (int seconds) and `Config.SSE_KEEPALIVE_INTERVAL` are read consistently in producer and consumer.
