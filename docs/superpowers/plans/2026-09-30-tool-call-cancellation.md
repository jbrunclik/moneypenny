# Server-side Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pressing Stop ends the running turn on the server within about a second, keeps the partial reply with a "Stopped · Continue" note, and bills no further work.

**Architecture:** A `/chat/stop` route sets a cross-worker kv flag; the worker running the turn owns a `CancelToken` (registry keyed by request id) that a poller thread flips when the flag appears. Checkpoints (token stream, graph nodes, `execute_code`, browser batches) read the token and raise `TurnCancelled`; `ChatAgent.stream_chat_events` turns that into its normal `final` event with `stop_reason: "user"`, so the existing save/done/resume paths carry the partial reply. A new `messages.stop_reason` column persists it; the frontend renders the existing stopped-early note with a "Stopped" label.

**Tech Stack:** Python 3.14, Flask, LangGraph, SQLite (yoyo migrations), llm-sandbox/Docker, Playwright worker; TypeScript + Vite + Zustand, Vitest, Playwright E2E.

**Spec:** [docs/superpowers/specs/2026-09-30-tool-call-cancellation-design.md](../specs/2026-09-30-tool-call-cancellation-design.md)

## Global Constraints

- kv namespace for the stop flag: `cancel`, key = conversation id (same carrier as `interjection.py`).
- `CANCEL_POLL_INTERVAL_SECONDS = 0.5` (backend `src/config.py`, env-overridable), `STOP_DONE_GRACE_MS = 5000` (frontend `web/src/config.ts`).
- `stop_reason` values: `"user"` only in this plan (the round cap keeps using `stopped_early`, derived from `message_costs` as today).
- Empty partial reply text: `Stopped before answering.`
- Stop note label for `stop_reason: "user"`: `Stopped.` + **Continue** (dispatches the existing `message:continue`).
- `_handle_tool_errors` must re-raise `TurnCancelled` (like `ApprovalRequestedException`).
- Repo is public: no hostnames/infra in code, docs or commit messages.
- Work on branch `feat/server-stop` (main must stay deployable). Each task commit on the branch requires `make lint` exit 0 and `make test` (backend) exit 0; Task 6+ also the Vitest suites. Main receives the branch only after `make lint` + `make test-all` exit 0 in-session (Task 7). Always check `$?` on a redirected log, never through a pipe.
- Conventional Commits; functions < 50 lines; files ≤ 500 lines; type hints everywhere.

## Review Focus

1. Stop pressed before `user_message_saved` arrives (server may not have the turn yet) → frontend aborts exactly as today (no `/stop` call); the send is reconciled as today. Pinned in Task 6 (`handleStopStreaming` test "aborts immediately when the turn has not started").
2. A stale stop flag from a previous turn (Stop clicked after the turn already ended) must not cancel the next turn → flag cleared synchronously before the producer starts. Pinned in Task 4 (`test_stale_stop_flag_does_not_cancel_the_next_turn`).
3. Stop while a non-interruptible tool (e.g. 20 s web search) runs → the turn ends at the next checkpoint, the tool result is not followed by another LLM call. Pinned in Task 3 (`test_check_tool_results_raises_when_cancelled`).
4. Client already disconnected (grace-period abort fired) → cleanup thread saves the partial **with** `stop_reason`, so a reload shows "Stopped". Pinned in Task 4 (`test_cleanup_save_keeps_stop_reason`).
5. Autonomous agents / batch mode (no registered token) → every checkpoint is a no-op. Pinned in Task 1 (`test_is_cancelled_without_a_registered_token_is_false`).

---

## File Structure

| File | Responsibility |
|---|---|
| Create `src/agent/cancellation.py` | `TurnCancelled`, `CancelToken`, token registry, `is_cancelled()`, `raise_if_cancelled()`, `on_cancel()`, kv flag helpers, `run_poller()` |
| Modify `src/config.py`, `.env.example` | `CANCEL_POLL_INTERVAL_SECONDS` |
| Modify `src/api/routes/chat.py` | `POST /conversations/<id>/chat/stop` |
| Modify `src/agent/graph.py` | checkpoints in `chat_node`, `check_tool_results`; `_handle_tool_errors` re-raise |
| Modify `src/agent/agent.py`, `src/agent/stream_events.py` | token-level checkpoint; `final` event carries `stop_reason` |
| Create `migrations/0055_add_message_stop_reason.py` | `messages.stop_reason TEXT` |
| Modify `src/db/models/dataclasses.py`, `message_rows.py`, `message.py` | `Message.stop_reason`, `set_message_stop_reason()` |
| Modify `src/api/helpers/stream_producer.py`, `chat_streaming.py`, `stream_finalize.py`, `chat_save.py` | token scope around the producer, flag clearing, `stop_reason` through save |
| Modify `src/api/utils.py`, `src/api/schemas/chat.py` | `stop_reason` in done event, message list, schema |
| Modify `src/agent/tools/code_execution.py`, `src/agent/tools/browser_steps.py` | kill user code on cancel; stop batches between steps |
| Modify `tests/e2e-server.py` | mock stream honours cancellation |
| Modify `web/src/config.ts`, `web/src/api/conversations.ts`, `web/src/core/active-requests.ts`, `web/src/core/stream-session.ts`, `web/src/core/stream-send.ts`, `web/src/core/stream-done.ts`, `web/src/components/messages/stopped-early.ts`, `web/src/components/messages/render.ts`, `web/src/types/api.ts` | server stop + grace abort, "Stopped" note |
| Modify docs: `docs/features/chat-and-streaming.md`, `docs/architecture/agent-graph.md`, `docs/features/code-execution.md`, `TODO.md` | behaviour docs, drop the TODO item |

---

### Task 1: Cancellation core

**Files:**
- Create: `src/agent/cancellation.py`
- Modify: `src/config.py` (next to the other agent settings), `.env.example`
- Test: `tests/unit/test_cancellation.py`, `tests/integration/test_cancellation_flag.py`

**Interfaces:**
- Produces:
  - `class TurnCancelled(Exception)`
  - `class CancelToken` with `.cancel() -> None`, `.cancelled -> bool` (property), `.add_callback(fn: Callable[[], None]) -> None`, `.remove_callback(fn) -> None`
  - `register_token(request_id: str) -> CancelToken`, `unregister_token(request_id: str) -> None`
  - `is_cancelled() -> bool`, `raise_if_cancelled() -> None` (use `get_current_request_id()`)
  - `on_cancel(fn: Callable[[], None]) -> contextmanager` (registers on the current token; no-op without one)
  - `request_stop(user_id: str, conv_id: str) -> None`, `stop_requested(user_id: str, conv_id: str) -> bool`, `clear_stop_request(user_id: str, conv_id: str) -> None`
  - `run_poller(token: CancelToken, check: Callable[[], bool], done: threading.Event, interval_seconds: float) -> None` (blocking loop; the caller runs it in a thread)
  - `STOPPED_EMPTY_TEXT = "Stopped before answering."`, `STOP_REASON_USER = "user"`

- [ ] **Step 1: Write the failing unit tests**

```python
"""Unit tests for turn cancellation (src/agent/cancellation.py)."""

import threading

import pytest

from src.agent import cancellation
from src.agent.cancellation import CancelToken, TurnCancelled
from src.agent.tool_results import set_current_request_id


@pytest.fixture(autouse=True)
def _request_scope():
    set_current_request_id("req-1")
    yield
    cancellation.unregister_token("req-1")
    set_current_request_id(None)


def test_is_cancelled_without_a_registered_token_is_false() -> None:
    assert cancellation.is_cancelled() is False
    cancellation.raise_if_cancelled()  # no-op


def test_cancel_flips_the_current_token() -> None:
    token = cancellation.register_token("req-1")
    token.cancel()
    assert cancellation.is_cancelled() is True
    with pytest.raises(TurnCancelled):
        cancellation.raise_if_cancelled()


def test_callbacks_run_once_on_cancel() -> None:
    token = CancelToken()
    calls: list[int] = []
    token.add_callback(lambda: calls.append(1))
    token.cancel()
    token.cancel()
    assert calls == [1]


def test_a_failing_callback_does_not_block_the_others() -> None:
    token = CancelToken()
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("kill failed")

    token.add_callback(boom)
    token.add_callback(lambda: calls.append("second"))
    token.cancel()
    assert calls == ["second"]


def test_on_cancel_registers_only_for_the_block() -> None:
    token = cancellation.register_token("req-1")
    calls: list[str] = []
    with cancellation.on_cancel(lambda: calls.append("inside")):
        pass
    token.cancel()
    assert calls == []


def test_on_cancel_fires_while_inside_the_block() -> None:
    token = cancellation.register_token("req-1")
    calls: list[str] = []
    with cancellation.on_cancel(lambda: calls.append("inside")):
        token.cancel()
    assert calls == ["inside"]


def test_poller_cancels_when_the_check_turns_true() -> None:
    token = CancelToken()
    done = threading.Event()
    answers = iter([False, True])
    thread = threading.Thread(
        target=cancellation.run_poller,
        args=(token, lambda: next(answers), done, 0.01),
    )
    thread.start()
    thread.join(timeout=2)
    assert token.cancelled is True
    assert not thread.is_alive()


def test_poller_exits_when_the_turn_ends() -> None:
    token = CancelToken()
    done = threading.Event()
    thread = threading.Thread(
        target=cancellation.run_poller, args=(token, lambda: False, done, 0.01)
    )
    thread.start()
    done.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert token.cancelled is False


def test_poller_survives_a_failing_check() -> None:
    token = CancelToken()
    done = threading.Event()
    answers = iter([RuntimeError("db locked"), True])

    def check() -> bool:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    thread = threading.Thread(target=cancellation.run_poller, args=(token, check, done, 0.01))
    thread.start()
    thread.join(timeout=2)
    assert token.cancelled is True
```

- [ ] **Step 2: Write the failing kv-flag integration test** (`tests/integration/test_cancellation_flag.py`)

```python
"""The stop flag round-trips through kv_store (cross-worker carrier)."""

from src.agent.cancellation import clear_stop_request, request_stop, stop_requested
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User


def test_stop_flag_lifecycle(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    assert stop_requested(test_user.id, test_conversation.id) is False
    request_stop(test_user.id, test_conversation.id)
    assert stop_requested(test_user.id, test_conversation.id) is True
    clear_stop_request(test_user.id, test_conversation.id)
    assert stop_requested(test_user.id, test_conversation.id) is False
```

- [ ] **Step 3: Run both, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_cancellation.py tests/integration/test_cancellation_flag.py -q > /tmp/t.log 2>&1; echo $?`
Expected: non-zero; `ModuleNotFoundError: src.agent.cancellation`.

- [ ] **Step 4: Implement `src/agent/cancellation.py`**

```python
"""Server-side Stop: cancel a running chat turn at the next checkpoint.

The stop route may land on a different gunicorn worker than the one running
the turn, so the request travels through kv_store (namespace ``cancel``,
keyed by conversation id - one active turn per conversation, like
interjections). The worker running the turn owns a CancelToken, registered
by request id (tools and graph nodes already know it via
get_current_request_id); a poller thread flips the token when the flag
appears. Checkpoints only read the token - no DB access on the hot path.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from src.agent.tool_results import get_current_request_id
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "cancel"
STOP_REASON_USER = "user"
STOPPED_EMPTY_TEXT = "Stopped before answering."


class TurnCancelled(Exception):  # noqa: N818 - control flow, not an error
    """Raised at a checkpoint once the user pressed Stop."""


class CancelToken:
    """One turn's cancel state: an event plus kill callbacks run once."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def add_callback(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.append(fn)

    def remove_callback(self, fn: Callable[[], None]) -> None:
        with self._lock:
            if fn in self._callbacks:
                self._callbacks.remove(fn)

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks)
        for fn in callbacks:
            try:
                fn()
            except Exception:
                logger.warning("Cancel callback failed", exc_info=True)


_tokens: dict[str, CancelToken] = {}
_tokens_lock = threading.Lock()


def register_token(request_id: str) -> CancelToken:
    token = CancelToken()
    with _tokens_lock:
        _tokens[request_id] = token
    return token


def unregister_token(request_id: str) -> None:
    with _tokens_lock:
        _tokens.pop(request_id, None)


def _current_token() -> CancelToken | None:
    request_id = get_current_request_id()
    if request_id is None:
        return None
    with _tokens_lock:
        return _tokens.get(request_id)


def is_cancelled() -> bool:
    token = _current_token()
    return token is not None and token.cancelled


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise TurnCancelled


@contextmanager
def on_cancel(fn: Callable[[], None]) -> Iterator[None]:
    """Run ``fn`` if the turn is cancelled while inside the block."""
    token = _current_token()
    if token is None:
        yield
        return
    token.add_callback(fn)
    try:
        yield
    finally:
        token.remove_callback(fn)


def request_stop(user_id: str, conv_id: str) -> None:
    db.kv_set(user_id, KV_NAMESPACE, conv_id, "1")


def stop_requested(user_id: str, conv_id: str) -> bool:
    return bool(db.kv_get(user_id, KV_NAMESPACE, conv_id))


def clear_stop_request(user_id: str, conv_id: str) -> None:
    try:
        db.kv_delete(user_id, KV_NAMESPACE, conv_id)
    except Exception:
        logger.debug("Stop flag clear failed", exc_info=True)


def run_poller(
    token: CancelToken,
    check: Callable[[], bool],
    done: threading.Event,
    interval_seconds: float,
) -> None:
    """Poll ``check`` until it is true (then cancel) or the turn ends."""
    while not done.wait(interval_seconds):
        try:
            if check():
                logger.info("Stop requested - cancelling turn")
                token.cancel()
                return
        except Exception:
            logger.warning("Stop flag poll failed", exc_info=True)
```

Add to `src/config.py` (agent settings block, near `AGENT_MAX_TOOL_ROUNDS`):

```python
    # Server-side Stop: how often the running turn checks for a stop request
    # (kv flag written by POST /chat/stop, possibly on another worker)
    CANCEL_POLL_INTERVAL_SECONDS: float = float(os.getenv("CANCEL_POLL_INTERVAL_SECONDS", "0.5"))
```

Add to `.env.example` next to the agent settings:

```
# How often a running chat turn checks for a Stop request, seconds (default: 0.5)
CANCEL_POLL_INTERVAL_SECONDS=0.5
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/unit/test_cancellation.py tests/integration/test_cancellation_flag.py -q > /tmp/t.log 2>&1; echo $?`
Expected: `0`.

- [ ] **Step 6: Commit**

```bash
git add src/agent/cancellation.py src/config.py .env.example tests/unit/test_cancellation.py tests/integration/test_cancellation_flag.py
git commit -m "feat(agent): cancellation token, registry and stop-flag poller"
```

---

### Task 2: Stop route

**Files:**
- Modify: `src/api/routes/chat.py` (after `chat_interject`)
- Test: `tests/integration/test_routes_chat_stop.py`

**Interfaces:**
- Consumes: `request_stop(user_id, conv_id)` from Task 1.
- Produces: `POST /api/conversations/<conv_id>/chat/stop` → `200 {"status": "stopping"}`; `404` for an unknown/foreign conversation.

- [ ] **Step 1: Write the failing tests**

```python
"""Integration tests for POST /api/conversations/<conv_id>/chat/stop."""

from flask.testing import FlaskClient

from src.agent.cancellation import stop_requested
from src.db.models.dataclasses import Conversation, User


class TestChatStop:
    def test_sets_the_stop_flag(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.get_json() == {"status": "stopping"}
        assert stop_requested(test_user.id, test_conversation.id) is True

    def test_rejects_unknown_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/api/conversations/nonexistent/chat/stop", headers=auth_headers)
        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        response = client.post(f"/api/conversations/{test_conversation.id}/chat/stop")
        assert response.status_code == 401
```

- [ ] **Step 2: Run, verify failure** — `.venv/bin/pytest tests/integration/test_routes_chat_stop.py -q > /tmp/t.log 2>&1; echo $?` → non-zero (404/405 on the route).

- [ ] **Step 3: Implement the route** (in `src/api/routes/chat.py`, below `chat_interject`; import `request_stop` from `src.agent.cancellation` at module top)

```python
@api.route("/conversations/<conv_id>/chat/stop", methods=["POST"])
@api.doc(
    summary="Stop the running chat turn",
    description=(
        "Ask the in-flight turn of this conversation to stop at its next "
        "checkpoint (cross-worker via kv_store). The stream then ends with a "
        "done event carrying stop_reason 'user' and the partial reply saved. "
        "Harmless when no turn is running."
    ),
    responses=[401, 404],
)
@rate_limit_chat
@require_auth
def chat_stop(user: User, conv_id: str) -> dict[str, str]:
    """Request that the running turn stops."""
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        raise_not_found_error("Conversation")
    request_stop(user.id, conv_id)
    logger.info("Stop requested", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "stopping"}
```

- [ ] **Step 4: Run, verify pass** — same command → `0`. Then `make openapi > /tmp/o.log 2>&1; echo $?` → `0` (regenerates `static/openapi.json`; never hand-edit it).

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/chat.py tests/integration/test_routes_chat_stop.py static/openapi.json
git commit -m "feat(api): POST /chat/stop requests a server-side stop"
```

---

### Task 3: Graph and stream checkpoints

**Files:**
- Modify: `src/agent/graph.py` (`chat_node` start, `check_tool_results` start, `_handle_tool_errors`)
- Modify: `src/agent/agent.py` (`stream_chat_events`), `src/agent/stream_events.py` (`StreamEventProcessor.finish`)
- Test: `tests/unit/test_graph_cancellation.py`

**Interfaces:**
- Consumes: `raise_if_cancelled`, `is_cancelled`, `TurnCancelled`, `STOP_REASON_USER`, `register_token` (Task 1).
- Produces: the `final` event of `stream_chat_events` gains `"stop_reason": "user"` when the turn was cancelled (key absent otherwise). `StreamEventProcessor.finish(turn_started: float, stop_reason: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
"""Cancellation checkpoints in the agent graph and the token stream."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import cancellation
from src.agent.cancellation import TurnCancelled
from src.agent.graph import _handle_tool_errors, chat_node, check_tool_results
from src.agent.tool_results import set_current_request_id


@pytest.fixture
def token():
    set_current_request_id("req-graph")
    token = cancellation.register_token("req-graph")
    yield token
    cancellation.unregister_token("req-graph")
    set_current_request_id(None)


def test_chat_node_raises_before_calling_the_model(token: cancellation.CancelToken) -> None:
    model = MagicMock()
    token.cancel()
    with pytest.raises(TurnCancelled):
        chat_node({"messages": [HumanMessage(content="hi")]}, model)  # type: ignore[typeddict-item]
    model.invoke.assert_not_called()


def test_check_tool_results_raises_when_cancelled(token: cancellation.CancelToken) -> None:
    token.cancel()
    with pytest.raises(TurnCancelled):
        check_tool_results({"messages": [HumanMessage(content="hi")]})  # type: ignore[typeddict-item]


def test_tool_error_handler_reraises_turn_cancelled() -> None:
    with pytest.raises(TurnCancelled):
        _handle_tool_errors(TurnCancelled())


def test_ordinary_tool_errors_still_become_messages() -> None:
    assert "Please fix your mistakes" in _handle_tool_errors(ValueError("bad"))


def _fake_graph_stream(chunks: list[str], on_chunk: Any = None) -> Any:
    def stream(*_args: Any, **_kwargs: Any) -> Any:
        for i, text in enumerate(chunks):
            if on_chunk:
                on_chunk(i)
            yield ("messages", (AIMessage(content=text), {"langgraph_node": "chat"}))

    return stream


def test_stream_stops_at_the_next_chunk_and_keeps_the_partial(
    token: cancellation.CancelToken,
) -> None:
    from src.agent.agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = _fake_graph_stream(
        ["Hello", " world", " never"], on_chunk=lambda i: token.cancel() if i == 2 else None
    )

    events = list(agent.stream_chat_events("hi"))

    final = events[-1]
    assert final["type"] == "final"
    assert final["stop_reason"] == "user"
    assert final["content"] == "Hello world"


def test_uncancelled_final_has_no_stop_reason() -> None:
    from src.agent.agent import ChatAgent

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = _fake_graph_stream(["Hello"])

    final = list(agent.stream_chat_events("hi"))[-1]
    assert "stop_reason" not in final


def test_turn_cancelled_raised_inside_the_graph_ends_the_stream(
    token: cancellation.CancelToken,
) -> None:
    from src.agent.agent import ChatAgent

    def stream(*_args: Any, **_kwargs: Any) -> Any:
        yield ("messages", (AIMessage(content="Partial"), {"langgraph_node": "chat"}))
        raise TurnCancelled

    agent = ChatAgent.__new__(ChatAgent)
    agent._build_messages = MagicMock(return_value=[HumanMessage(content="hi")])  # type: ignore[method-assign]
    agent.graph = MagicMock()
    agent.graph.stream = stream

    final = list(agent.stream_chat_events("hi"))[-1]
    assert final["stop_reason"] == "user"
    assert final["content"] == "Partial"
```

Add the `delegate_task` coverage (its subagent runs `ChatAgent.chat_batch` in the same thread, so it shares the parent's request id and token; the graph checkpoints must propagate out of the tool, not be swallowed into an error string):

```python
def test_delegate_subagent_stop_propagates(token: cancellation.CancelToken) -> None:
    from unittest.mock import patch

    from src.agent.tools.delegate import delegate_task

    def cancelled_batch(*_args: Any, **_kwargs: Any) -> Any:
        token.cancel()
        cancellation.raise_if_cancelled()  # what the subagent's chat_node does

    with (
        patch("src.agent.agent.ChatAgent.chat_batch", cancelled_batch),
        patch("src.agent.tools.delegate.check_autonomous_permission"),
    ):
        with pytest.raises(TurnCancelled):
            delegate_task.invoke({"task": "Compare three laptops"})
```

If `delegate_task` catches exceptions broadly around `chat_batch`, add `except TurnCancelled: raise` ahead of that handler.

Note for the implementer: if the chunk fixture shape differs from what `StreamEventProcessor.process` expects (check `tests/unit/test_agent_streaming.py` for the real `("messages", (chunk, metadata))` shape and the node-name metadata key), adapt `_fake_graph_stream` - not the production code - and keep the assertions.

- [ ] **Step 2: Run, verify failure** — `.venv/bin/pytest tests/unit/test_graph_cancellation.py -q > /tmp/t.log 2>&1; echo $?` → non-zero (no `TurnCancelled` raised / no `stop_reason`).

- [ ] **Step 3: Implement the checkpoints**

In `src/agent/graph.py` add `from src.agent.cancellation import TurnCancelled, raise_if_cancelled` at module top, then:

```python
# first statement of chat_node (before list(state["messages"])):
    # Server-side Stop: never start another model call once Stop was pressed
    raise_if_cancelled()
```

```python
# first statement of check_tool_results (before messages = state["messages"]):
    # Server-side Stop: the round that just finished is the last one
    raise_if_cancelled()
```

```python
# in _handle_tool_errors, next to the ApprovalRequestedException re-raise:
    if isinstance(e, (ApprovalRequestedException, TurnCancelled)):
        raise e
```

Update the `_handle_tool_errors` docstring's first paragraph to name `TurnCancelled` as the second control-flow exception.

In `src/agent/stream_events.py`, `StreamEventProcessor.finish`:

```python
    def finish(self, turn_started: float, stop_reason: str | None = None) -> Iterator[dict[str, Any]]:
        ...  # unchanged body up to the final yield
        final: dict[str, Any] = {
            "type": "final",
            "content": clean_content,
            "tool_results": self.tool_results,
            "usage_info": usage_info,
            "result_messages": self.all_messages,
        }
        if stop_reason:
            final["stop_reason"] = stop_reason
        yield final
```

In `src/agent/agent.py`, `stream_chat_events` (imports: `from src.agent.cancellation import STOP_REASON_USER, TurnCancelled, is_cancelled`):

```python
        config = get_graph_config()
        turn_started = time.monotonic()
        stop_reason: str | None = None
        stream = self.graph.stream(
            cast(Any, {"messages": messages}),
            config=config,
            # "custom" carries node-written statuses (transient-error
            # retries) that must reach the client while the node sleeps
            stream_mode=["messages", "custom"],
        )
        try:
            for mode, event in stream:
                # Server-side Stop: stop consuming model output at once; the
                # text so far is the reply (checked per chunk, token read only)
                if is_cancelled():
                    raise TurnCancelled
                yield from processor.process(mode, event)
        except TurnCancelled:
            stop_reason = STOP_REASON_USER
            logger.info(
                "Turn stopped by user",
                extra={"accumulated_response_length": len(processor.full_response)},
            )
        except RuntimeError as e:
            ...  # unchanged executor-shutdown handling
        finally:
            stream.close()

        yield from processor.finish(turn_started, stop_reason=stop_reason)
```

- [ ] **Step 4: Run, verify pass** — the Step 2 command → `0`; then `.venv/bin/pytest tests/unit/test_graph.py tests/unit/test_graph_routing.py tests/unit/test_agent_streaming.py -q > /tmp/t.log 2>&1; echo $?` → `0`.

- [ ] **Step 5: Commit**

```bash
git add src/agent/graph.py src/agent/agent.py src/agent/stream_events.py tests/unit/test_graph_cancellation.py
git commit -m "feat(agent): stop checkpoints in the graph and the token stream"
```

---

### Task 4: Producer scope, persistence, done event

**Files:**
- Create: `migrations/0055_add_message_stop_reason.py`
- Modify: `src/db/models/dataclasses.py` (`Message.stop_reason: str | None = None`), `src/db/models/message_rows.py`, `src/db/models/message.py` (`set_message_stop_reason`)
- Modify: `src/api/helpers/stream_producer.py` (token scope + poller in `stream_events`; `final_results["stop_reason"]`)
- Modify: `src/api/helpers/chat_streaming.py` (clear flag before `start_threads`; `context.stop_reason`; cleanup lambda passes it)
- Modify: `src/api/helpers/stream_finalize.py`, `src/api/helpers/chat_save.py` (`save_message_to_db(..., stop_reason: str | None = None)`)
- Modify: `src/api/utils.py` (`build_stream_done_event`, `build_chat_response`, `serialize_messages_for_response` read `stop_reason` from the message)
- Modify: `src/api/schemas/chat.py` (`MessageResponse.stop_reason`, `ChatBatchResponse.stop_reason`)
- Test: `tests/integration/test_stream_stop.py`, extend `tests/unit/test_stream_producer.py`

**Interfaces:**
- Consumes: Task 1 (`register_token`, `unregister_token`, `run_poller`, `stop_requested`, `clear_stop_request`, `STOPPED_EMPTY_TEXT`), Task 3 (`final["stop_reason"]`).
- Produces: `db.set_message_stop_reason(message_id: str, stop_reason: str) -> None`; `Message.stop_reason`; done event / message JSON field `stop_reason: "user"` (absent otherwise).

- [ ] **Step 1: Write the failing tests** (`tests/integration/test_stream_stop.py`)

Model it on the existing streaming route tests (`tests/integration/test_routes_chat.py` - reuse its fixtures and its way of patching `ChatAgent.stream_chat_events` and reading the SSE body). Three tests:

```python
"""Server-side Stop through the real streaming route (agent stream patched)."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

from flask.testing import FlaskClient

from src.agent import cancellation
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User


def _stream_that_stops(*_args: Any, **_kwargs: Any) -> Generator[dict[str, Any]]:
    yield {"type": "token", "text": "Partial answer"}
    yield {
        "type": "final",
        "content": "Partial answer",
        "tool_results": [],
        "usage_info": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "result_messages": [],
        "stop_reason": "user",
    }


def _done_event(body: str) -> dict[str, Any]:
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    return next(e for e in events if e.get("type") == "done")


def test_stopped_turn_saves_partial_with_stop_reason(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database,
    test_conversation: Conversation,
) -> None:
    with patch("src.agent.agent.ChatAgent.stream_chat_events", _stream_that_stops):
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            json={"message": "Tell me a long story"},
            headers=auth_headers,
        )
        body = response.get_data(as_text=True)

    done = _done_event(body)
    assert done["stop_reason"] == "user"
    saved = test_database.get_message_by_id(done["id"])
    assert saved is not None and saved.content == "Partial answer"
    assert saved.stop_reason == "user"
    listed = client.get(
        f"/api/conversations/{test_conversation.id}/messages", headers=auth_headers
    ).get_json()
    assert any(m.get("stop_reason") == "user" for m in listed["messages"])


def test_empty_stopped_turn_saves_placeholder_text(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database,
    test_conversation: Conversation,
) -> None:
    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        yield {"type": "final", "content": "", "tool_results": [], "usage_info": {},
               "result_messages": [], "stop_reason": "user"}

    with patch("src.agent.agent.ChatAgent.stream_chat_events", stream):
        body = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            json={"message": "hi"}, headers=auth_headers,
        ).get_data(as_text=True)

    assert _done_event(body)["content"] == cancellation.STOPPED_EMPTY_TEXT


def test_stale_stop_flag_does_not_cancel_the_next_turn(
    client: FlaskClient, auth_headers: dict[str, str], test_user: User,
    test_conversation: Conversation,
) -> None:
    cancellation.request_stop(test_user.id, test_conversation.id)  # Stop after the last turn

    seen: dict[str, bool] = {}

    def stream(*_a: Any, **_k: Any) -> Generator[dict[str, Any]]:
        import time
        time.sleep(0.2)  # > CANCEL_POLL_INTERVAL in tests (patched below)
        seen["cancelled"] = cancellation.is_cancelled()
        yield {"type": "final", "content": "Full", "tool_results": [], "usage_info": {},
               "result_messages": []}

    with (
        patch("src.agent.agent.ChatAgent.stream_chat_events", stream),
        patch("src.config.Config.CANCEL_POLL_INTERVAL_SECONDS", 0.02),
    ):
        body = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            json={"message": "hi"}, headers=auth_headers,
        ).get_data(as_text=True)

    assert seen["cancelled"] is False
    assert "stop_reason" not in _done_event(body)
    assert cancellation.stop_requested(test_user.id, test_conversation.id) is False
```

Add a fourth test, `test_stop_flag_cancels_the_running_turn`: patch the stream to call `cancellation.request_stop(...)` for the conversation, then loop `for _ in range(100): if cancellation.is_cancelled(): break; time.sleep(0.01)` with `CANCEL_POLL_INTERVAL_SECONDS` patched to `0.02`, record the result, and yield a normal final; assert it saw `True` (proves route-flag → poller → token wiring inside the producer).

In `tests/unit/test_stream_producer.py` add `test_cleanup_save_keeps_stop_reason`: same setup as `test_cleanup_saves_when_generator_exits_without_saving` with `final_results["stop_reason"] = "user"`, and assert the save callable received it. Since `cleanup_and_save` takes a zero-arg save callable, assert on the lambda built in `_StreamContext.start_threads` instead: construct a `_StreamContext` with MagicMock user/conv/turn, set `final_results` (`ready=True`, `stop_reason="user"`, content etc.), patch `src.api.helpers.chat_streaming.save_message_to_db`, call the cleanup lambda by patching `threading.Thread` to capture `args`, and assert `stop_reason="user"` was passed.

- [ ] **Step 2: Run, verify failure** — `.venv/bin/pytest tests/integration/test_stream_stop.py tests/unit/test_stream_producer.py -q > /tmp/t.log 2>&1; echo $?` → non-zero (`stop_reason` missing, `Message` has no `stop_reason`).

- [ ] **Step 3: Migration** — `make migration NAME=add_message_stop_reason`, then set the file to:

```python
"""Add stop_reason to messages.

Why an assistant reply ended early: "user" when the user pressed Stop and
the server ended the turn (partial reply kept, Continue offered). NULL for
normal replies. The tool-round cap keeps being derived from message_costs.
"""

from yoyo import step

__depends__ = {"0054_add_message_tool_outputs"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN stop_reason TEXT",
        "ALTER TABLE messages DROP COLUMN stop_reason",
    ),
]
```

- [ ] **Step 4: Model** — `Message.stop_reason: str | None = None` (dataclasses.py, after `tool_outputs`); in `row_to_message`: `stop_reason=row["stop_reason"] if "stop_reason" in row.keys() else None`; in `MessageMixin`:

```python
    def set_message_stop_reason(self, message_id: str, stop_reason: str) -> None:
        """Record why an assistant reply ended early (e.g. "user" for Stop)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE messages SET stop_reason = ? WHERE id = ?",
                (stop_reason, message_id),
            )
            conn.commit()
```

(Match the commit/connection idiom of `update_message_content` in the same file if it differs.)

- [ ] **Step 5: Save path** — `save_message_to_db(..., mode: str = "stream", stop_reason: str | None = None)`. At its start: `if stop_reason and not content.strip(): content = STOPPED_EMPTY_TEXT`. After the assistant message is persisted (the `_persist_assistant_message` result), `if stop_reason: db.set_message_stop_reason(assistant_msg.id, stop_reason)`. Keep the function < 100 lines; extract a helper if it grows.

- [ ] **Step 6: Producer scope** (`stream_producer.stream_events`, imports from `src.agent.cancellation`):

```python
    # Server-side Stop: a token for this request, flipped by a poller when
    # the stop route's kv flag appears (the route may run on another worker)
    token = register_token(turn.request_id)
    turn_done = threading.Event()
    poller = threading.Thread(
        target=_poll_stop_flag,
        args=(token, user_id, conv_id, turn_done),
        daemon=True,
        name="stop-poller",
    )
    poller.start()
    try:
        ...  # existing body; in the "final" branch also:
        #   final_results["stop_reason"] = event.get("stop_reason")
    finally:
        turn_done.set()
        unregister_token(turn.request_id)
        clear_stop_request(user_id, conv_id)
        ...  # existing finally (journal.finish, _close_thread_db_connections)
```

```python
def _poll_stop_flag(
    token: CancelToken, user_id: str, conv_id: str, done: threading.Event
) -> None:
    try:
        run_poller(
            token, lambda: stop_requested(user_id, conv_id), done,
            Config.CANCEL_POLL_INTERVAL_SECONDS,
        )
    finally:
        _close_thread_db_connections()
```

Initialize `final_results` with `"stop_reason": None` in `_StreamContext.__init__`.

- [ ] **Step 7: Consumer + finalize** — in `chat_streaming.generate()`, before `context.start_threads()`: `clear_stop_request(context.user_id, context.conv_id)` (synchronous, so a Stop sent after `user_message_saved` can never be wiped by a late clear). In `_handle_queue_event` final branch: `context.stop_reason = item.get("stop_reason")` (add `self.stop_reason: str | None = None` to `_StreamContext`). Pass `stop_reason=context.stop_reason` in `_finalize_stream`'s `save_message_to_db` call, and `stop_reason=self.final_results.get("stop_reason")` in the cleanup lambda.

- [ ] **Step 8: Response shapes** — in `build_stream_done_event` and `build_chat_response`: `stop_reason = getattr(assistant_msg, "stop_reason", None); if stop_reason: data["stop_reason"] = stop_reason`. In `serialize_messages_for_response`: `if m.stop_reason: msg_data["stop_reason"] = m.stop_reason`. The resume endpoint builds its own done event: in `src/api/helpers/stream_resume.py` `_done_event_from_message`, add `if getattr(msg, "stop_reason", None): done["stop_reason"] = msg.stop_reason` - a client that resumes a stopped turn must also see "Stopped". Cover it with a test in `tests/unit/test_stream_resume.py` following that file's existing done-event tests (saved message with `stop_reason="user"` → resumed done event carries it). Schemas (`MessageResponse`, `ChatBatchResponse`):

```python
    stop_reason: Literal["user"] | None = Field(
        default=None, description="Why the reply ended early: 'user' = stopped by the user (offer Continue)"
    )
```

Then `make openapi > /tmp/o.log 2>&1; echo $?` and `make types > /tmp/ty.log 2>&1; echo $?` → both `0`.

- [ ] **Step 9: Run, verify pass** — Step 2 command → `0`; then `make test > /tmp/t.log 2>&1; echo $?` → `0`.

- [ ] **Step 10: Commit**

```bash
git add migrations/0055_add_message_stop_reason.py src/db/models src/api tests static/openapi.json web/src/types/generated-api.ts
git commit -m "feat(chat): end stopped turns server-side and persist stop_reason"
```

---

### Task 5: Interrupt execute_code and browser batches

**Files:**
- Modify: `src/agent/tools/code_execution.py` (around `session.run(wrapped_code)`)
- Modify: `src/agent/tools/browser_steps.py` (`run_batch`)
- Test: `tests/unit/test_code_execution.py`, `tests/unit/test_browser_batch.py`, `tests/integration/test_code_sandbox_cancel.py`

**Interfaces:**
- Consumes: `on_cancel`, `raise_if_cancelled`, `is_cancelled`, `register_token` (Task 1).
- Produces: `_kill_user_code(session: Any) -> None` in code_execution.py; `run_batch` returns a failure summary with `error == "Stopped by the user."` when cancelled.

- [ ] **Step 1: Failing tests**

`tests/unit/test_browser_batch.py` (uses the existing `worker` fixture and `LOGIN_STEPS`):

```python
    def test_stops_between_steps_when_cancelled(self, worker: MagicMock) -> None:
        from src.agent import cancellation
        from src.agent.tool_results import set_current_request_id

        set_current_request_id("req-batch")
        token = cancellation.register_token("req-batch")

        def execute(fn: str, **kw: Any) -> dict[str, Any]:
            if fn == "type":
                token.cancel()
            return _ok()

        worker.execute.side_effect = execute
        try:
            result = json.loads(browser.invoke({"actions": LOGIN_STEPS}))
        finally:
            cancellation.unregister_token("req-batch")
            set_current_request_id(None)

        assert _fn_names(worker) == ["navigate", "type"]
        assert result["failed_step"] == 2
        assert result["error"] == "Stopped by the user."
```

`tests/unit/test_code_execution.py`:

```python
class TestCancelKillsUserCode:
    def test_cancel_during_run_kills_the_user_process(self) -> None:
        from src.agent import cancellation
        from src.agent.tool_results import set_current_request_id

        set_current_request_id("req-code")
        token = cancellation.register_token("req-code")
        session = MagicMock()

        def run(_code: str) -> MagicMock:
            token.cancel()  # Stop pressed while the code runs
            return MagicMock(exit_code=137, stdout="", stderr="")

        session.run.side_effect = run
        pool = MagicMock()
        pool.session.return_value.__enter__.return_value = session
        try:
            with (
                patch("src.agent.tools.code_execution._check_docker_available", return_value=True),
                patch("src.agent.tools.code_execution.get_sandbox_pool", return_value=pool),
                patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True),
            ):
                execute_code.invoke({"code": "import time; time.sleep(30)"})
        finally:
            cancellation.unregister_token("req-code")
            set_current_request_id(None)

        kill_call = session.container.exec_run.call_args
        assert kill_call.kwargs["user"] == "root"
```

(Check the real names of the Docker-availability helper and pool accessor in `code_execution.py` and patch those; keep the assertion.)

`tests/integration/test_code_sandbox_cancel.py` (live, skips like the isolation test):

```python
"""Live: Stop kills a running sandbox program; the session and /work survive."""

import json
import threading
import time

import pytest

from src.agent import cancellation
from src.agent.tool_results import set_current_request_id
from src.agent.tools.context import set_conversation_context
from tests.integration.test_code_sandbox_isolation import _sandbox_runnable


@pytest.mark.skipif(not _sandbox_runnable(), reason="Docker or sandbox image unavailable")
def test_stop_kills_sleep_and_keeps_work_dir() -> None:
    from src.agent.tools.code_execution import execute_code

    set_conversation_context("conv-cancel-test", "user-cancel-test")
    set_current_request_id("req-live")
    token = cancellation.register_token("req-live")
    try:
        execute_code.invoke({"code": "open('/work/keep.txt','w').write('kept')"})
        threading.Timer(2.0, token.cancel).start()
        started = time.monotonic()
        execute_code.invoke({"code": "import time; time.sleep(30)"})
        elapsed = time.monotonic() - started
    finally:
        cancellation.unregister_token("req-live")

    set_current_request_id("req-live-2")
    after = json.loads(execute_code.invoke({"code": "print(open('/work/keep.txt').read())"}))
    assert elapsed < 10
    assert "kept" in after["stdout"]
```

(Use the real conversation-context setter from `src/agent/tools/context.py`; the pool keys sessions by conversation id.)

- [ ] **Step 2: Run, verify failure** — `.venv/bin/pytest tests/unit/test_browser_batch.py tests/unit/test_code_execution.py tests/integration/test_code_sandbox_cancel.py -q > /tmp/t.log 2>&1; echo $?` → non-zero.

- [ ] **Step 3: Implement**

`browser_steps.run_batch`, first check inside the loop (import `is_cancelled` from `src.agent.cancellation`):

```python
        if is_cancelled():
            return _batch_summary(done, last, failed=(index, "Stopped by the user."))
```

`code_execution.py`:

```python
# Kills the user's program inside a live session container without touching
# PID 1 or the container: /work must survive a Stop. No procps in the slim
# image, so scan /proc from Python (always present in the image).
_KILL_USER_CODE = (
    "import os\n"
    "me = os.getpid()\n"
    "for p in filter(str.isdigit, os.listdir('/proc')):\n"
    "    try:\n"
    "        if int(p) != me and b'/sandbox/' in open(f'/proc/{p}/cmdline', 'rb').read():\n"
    "            os.kill(int(p), 9)\n"
    "    except OSError:\n"
    "        pass\n"
)


def _kill_user_code(session: Any) -> None:
    """Cancel callback: SIGKILL the running user program (Stop pressed)."""
    logger.info("Stop requested - killing sandbox user code")
    session.container.exec_run(["python", "-c", _KILL_USER_CODE], user="root")
```

Around the run:

```python
            raise_if_cancelled()
            with cancellation.on_cancel(lambda: _kill_user_code(session)):
                result = session.run(wrapped_code)
```

- [ ] **Step 4: Run, verify pass** — Step 2 command → `0` (the live test needs Docker + `make sandbox-image`; run `docker info` first and start Docker Desktop if it is down, as the live test is the only proof the kill works).

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools/code_execution.py src/agent/tools/browser_steps.py tests/unit/test_code_execution.py tests/unit/test_browser_batch.py tests/integration/test_code_sandbox_cancel.py
git commit -m "feat(agent): Stop kills running sandbox code and ends browser batches"
```

---

### Task 6: Frontend - server stop, grace abort, "Stopped" note

**Files:**
- Modify: `web/src/config.ts` (`STOP_DONE_GRACE_MS`), `web/src/api/conversations.ts` (`stop`), `web/src/core/active-requests.ts` (`onStop` hook), `web/src/core/stream-session.ts` (`StreamingState.stopRequested`, `stopTimer`), `web/src/core/stream-send.ts` (register the hook; abort branch keeps partial), `web/src/core/stream-done.ts` (`stop_reason`), `web/src/components/messages/stopped-early.ts` (reason-aware label), `web/src/components/messages/render.ts`, `web/src/types/api.ts` (`stop_reason` on `Message`, `StreamDoneEvent`)
- Test: `web/tests/unit/active-requests.test.ts`, `web/tests/unit/stopped-early.test.ts`, `web/tests/unit/stream-done.test.ts`

**Interfaces:**
- Consumes: `POST /api/conversations/<id>/chat/stop` (Task 2); `stop_reason` on done events and messages (Task 4).
- Produces:
  - `conversations.stop(id: string): Promise<void>`
  - `ActiveRequest.onStop?: () => boolean` - returns true when it started a graceful server stop
  - `setStopHandler(convId: string, handler: () => boolean): void` in active-requests.ts
  - `appendStoppedEarlyNote(contentWrapper, messageId, reason: 'round_cap' | 'user' = 'round_cap')`
  - `STOP_DONE_GRACE_MS = 5 * MS_PER_SECOND`

- [ ] **Step 1: Failing unit tests**

`web/tests/unit/active-requests.test.ts`:

```typescript
  it('lets the stream stop gracefully when its handler accepts', () => {
    const controller = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: controller });
    const handler = vi.fn(() => true);
    setStopHandler('c1', handler);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(handler).toHaveBeenCalledTimes(1);
    expect(controller.signal.aborted).toBe(false);
  });

  it('aborts immediately when the turn has not started', () => {
    const controller = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: controller });
    setStopHandler('c1', () => false);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(controller.signal.aborted).toBe(true);
  });
```

`web/tests/unit/stopped-early.test.ts`:

```typescript
  it('labels a user stop as stopped, still offering Continue', () => {
    const el = wrapper();
    appendStoppedEarlyNote(el, 'm1', 'user');
    const note = el.querySelector('.message-stopped-early');
    expect(note?.textContent).toContain('Stopped.');
    expect(note?.textContent).not.toContain('tool-step limit');
    expect(el.querySelector('.message-stopped-early-continue')).not.toBeNull();
  });
```

`web/tests/unit/stream-done.test.ts`:

```typescript
  it('carries stop_reason into the store message', () => {
    const msg = assistantMessageFromDone(
      { type: 'done', id: 'm1', created_at: '2026-09-30T10:00:00', content: 'Partial', stop_reason: 'user' },
      'Partial'
    );
    expect(msg.stop_reason).toBe('user');
  });
```

- [ ] **Step 2: Run, verify failure** — `cd web && npx vitest run tests/unit/active-requests.test.ts tests/unit/stopped-early.test.ts tests/unit/stream-done.test.ts > /tmp/v.log 2>&1; echo $?` → non-zero.

- [ ] **Step 3: Implement**

`web/src/config.ts`:

```typescript
/** After a server-side Stop, how long to wait for the done event before aborting the reader */
export const STOP_DONE_GRACE_MS = 5 * MS_PER_SECOND;
```

`web/src/api/conversations.ts` (next to `interject`):

```typescript
  /** Ask the running turn to stop server-side (partial reply is kept). */
  async stop(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/chat/stop`, { method: 'POST' });
  },
```

`web/src/core/active-requests.ts`: add `onStop?: () => boolean;` to `ActiveRequest`, and

```typescript
/** Give the conversation's live stream a graceful-stop handler (server stop). */
export function setStopHandler(convId: string, handler: () => boolean): void {
  for (const request of activeRequests.values()) {
    if (request.conversationId === convId && request.type === 'stream') {
      request.onStop = handler;
    }
  }
}
```

and in `handleStopStreaming`, before `abortStreamingRequest`:

```typescript
    const live = [...activeRequests.values()].find(
      (r) => r.conversationId === currentConvId && r.type === 'stream'
    );
    if (live?.onStop?.()) return;
```

`web/src/core/stream-session.ts` `StreamingState`: add

```typescript
  /** Stop was sent to the server; the done event (stop_reason 'user') is expected */
  stopRequested?: boolean;
  /** Grace timer that aborts the reader if the done event never arrives */
  stopTimer?: ReturnType<typeof setTimeout>;
```

and in `cleanupStreamingRequest` clear it: `if (state.stopTimer) clearTimeout(state.stopTimer);` (pass the state if the function does not receive it yet - follow its current signature).

`web/src/core/stream-send.ts`, right after the request is registered for this send:

```typescript
/**
 * Stop pressed: once the server has the turn (user_message_saved gave us the
 * assistant id), ask it to stop and keep reading - the done event brings the
 * saved partial. Before that, fall back to aborting the reader (returns false).
 */
function requestServerStop(send: StreamSend): boolean {
  const { convId, state } = send;
  if (!state.expectedAssistantMessageId || state.stopRequested) return Boolean(state.stopRequested);
  state.stopRequested = true;
  conversations.stop(convId).catch((error: unknown) => {
    log.warn('Server stop request failed - aborting reader', { conversationId: convId, error });
    state.activeAbortController?.abort();
  });
  state.stopTimer = setTimeout(() => state.activeAbortController?.abort(), STOP_DONE_GRACE_MS);
  return true;
}
```

register with `setStopHandler(convId, () => requestServerStop(send));`. In `handleStreamFailure`'s AbortError branch, before `markSendFailed`:

```typescript
    if (state.stopRequested) {
      // Server-side stop whose done event never arrived: the partial is (or
      // will be) saved - keep the bubble; sync replaces it with the saved one
      state.messageEl.classList.add('message-incomplete');
      toast.info('Response stopped.');
      clearPendingRecovery(convId);
      return;
    }
```

`web/src/core/stream-done.ts`: add `stop_reason?: 'user';` to `StreamDoneEvent`, map it in `assistantMessageFromDone`, and in `finalizeDoneBubble` replace the `stopped_early` block with:

```typescript
  const reason = event.stop_reason === 'user' ? 'user' : event.stopped_early ? 'round_cap' : null;
  if (reason) {
    const wrapper = messageEl.querySelector<HTMLElement>('.message-content-wrapper');
    if (wrapper) appendStoppedEarlyNote(wrapper, event.id, reason);
  }
```

and in `handleStreamDone`, when `state.stopRequested`: `toast.info('Response stopped.')`.

`web/src/components/messages/stopped-early.ts`:

```typescript
const NOTE_TEXT: Record<'round_cap' | 'user', string> = {
  round_cap: 'Stopped at the tool-step limit - this answer may be incomplete.',
  user: 'Stopped.',
};

export function appendStoppedEarlyNote(
  contentWrapper: HTMLElement,
  messageId: string,
  reason: 'round_cap' | 'user' = 'round_cap'
): void {
  ...
  text.textContent = NOTE_TEXT[reason];
  ...
}
```

(update the module docstring: the note also marks replies the user stopped). `render.ts`: `if (message.role === 'assistant' && (message.stop_reason === 'user' || message.stopped_early)) appendStoppedEarlyNote(contentWrapper, message.id, message.stop_reason === 'user' ? 'user' : 'round_cap');`. `types/api.ts`: `stop_reason?: 'user';` on `Message` and the stream-done payload type.

- [ ] **Step 4: Run, verify pass** — Step 2 command → `0`; `cd web && npx tsc --noEmit > /tmp/tsc.log 2>&1; echo $?` → `0`.

- [ ] **Step 5: Commit**

```bash
git add web/src web/tests/unit
git commit -m "feat(web): Stop ends the turn server-side and keeps the partial reply"
```

---

### Task 7: E2E, docs, full verification

**Files:**
- Modify: `tests/e2e-server.py` (`mock_stream_chat_events` honours cancellation)
- Modify: `web/tests/e2e/chat/streaming.spec.ts` (stop test), `web/tests/e2e/stream-resume.spec.ts` (resumed-turn stop test, if its expectations change)
- Modify: `docs/features/chat-and-streaming.md` ("Stop Streaming"), `docs/architecture/agent-graph.md` (checkpoints), `docs/features/code-execution.md` (Stop kills user code), `TODO.md` (remove "Server-side tool-call cancellation")

- [ ] **Step 1: Mock honours Stop** — in `mock_stream_chat_events`, the token loop:

```python
        from src.agent.cancellation import STOP_REASON_USER, is_cancelled

        streamed = ""
        stop_reason = None
        for i, word in enumerate(words):
            if is_cancelled():
                stop_reason = STOP_REASON_USER
                break
            token = f" {word}" if i > 0 else word
            streamed += token
            yield {"type": "token", "text": token}
            time.sleep(delay_s)

        final = {
            "type": "final",
            "content": streamed if stop_reason else response_text,
            "metadata": {},
            "tool_results": [],
            "usage_info": usage_info,
        }
        if stop_reason:
            final["stop_reason"] = stop_reason
        yield final
```

- [ ] **Step 2: Rewrite the E2E stop test** (`streaming.spec.ts`, "clicking stop button aborts stream and shows toast" → "stop keeps the partial reply with a Stopped note"):

```typescript
  test('stop keeps the partial reply with a Stopped note', async ({ page }) => {
    await page.fill('#message-input', 'Tell me a very long story please');
    await page.click('#send-btn');
    const assistant = page.locator('.message.assistant');
    await expect(assistant).toBeVisible({ timeout: 5000 });
    await expect(assistant.locator('.message-content')).not.toBeEmpty({ timeout: 5000 });

    await page.click('#send-btn.btn-stop', { timeout: 5000, force: true });

    await expect(page.locator('.toast-info')).toContainText('Response stopped');
    const note = assistant.locator('.message-stopped-early');
    await expect(note).toContainText('Stopped.', { timeout: 5000 });
    await expect(note.locator('.message-stopped-early-continue')).toBeVisible();
    await expect(page.locator('#send-btn')).toHaveClass(/btn-send/);

    const partial = await assistant.locator('.message-content').innerText();
    await page.reload();
    const reloaded = page.locator('.message.assistant');
    await expect(reloaded.locator('.message-stopped-early')).toContainText('Stopped.');
    await expect(reloaded.locator('.message-content')).toHaveText(partial);
  });
```

Run it on both viewports the suite uses (desktop + the mobile project) and both engines: `cd web && npx playwright test tests/e2e/chat/streaming.spec.ts --project=chromium --project=webkit > /tmp/e2e.log 2>&1; echo $?` after `make build`. Then run `stream-resume.spec.ts` the same way and update "stop button aborts a reload-resumed turn without recovery" to the new behaviour (partial kept with the note) if it fails for that reason - and only for that reason.

- [ ] **Step 3: Docs** — `chat-and-streaming.md` "Stop Streaming": replace steps 3-5 and the "Note on partial messages" with the server-stop flow (route, kv flag, poller, checkpoints, `stop_reason`, grace abort, "Stopped · Continue"); `agent-graph.md`: a "Stop checkpoints" subsection listing `chat_node`/`check_tool_results`/token stream and the `_handle_tool_errors` rule; `code-execution.md`: Stop kills the user program, `/work` survives; delete the TODO item. Run `.venv/bin/pytest tests/unit/test_docs_links.py -q > /tmp/d.log 2>&1; echo $?` → `0`.

- [ ] **Step 4: Full verification** — `make lint > /tmp/lint.log 2>&1; echo $?` → `0`; `make test-all > /tmp/all.log 2>&1; echo $?` → `0` (rebuilds before E2E).

- [ ] **Step 5: Commit, push, deploy**

```bash
git add tests/e2e-server.py web/tests/e2e docs TODO.md
git commit -m "test(e2e): Stop keeps the partial reply; docs for server-side Stop"
```

Push to main, deploy per the private deploy memory (migration 0055 applies on start - deploy once, wait for "Deploy healthy.", never twice in quick succession), watch CI.
