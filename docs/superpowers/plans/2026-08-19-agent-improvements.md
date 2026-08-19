# Agent Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship six agent improvements (persistent sandbox sessions, planning removal + thinking plumbing, research tool + search provider, delegate subagent tool, tiered memory + embeddings, eval harness) plus small fixes, as phased commits to `main`.

**Architecture:** Each phase is an independently shippable commit series against the existing LangGraph agent (`src/agent/`). New capabilities are new tool modules following the `@tool` + registration pattern; cross-cutting changes (cost, prompts, config) extend existing seams.

**Tech Stack:** Python 3.14 / Flask / LangGraph / langchain-google-genai 4.3.2 / llm-sandbox / httpx / sqlite (yoyo migrations) / pytest.

**Spec:** docs/superpowers/specs/2026-08-19-agent-improvements-design.md

## Global Constraints

- Conventional Commits: `type(scope): description`.
- `make lint` + `make test` must pass before every commit (skip the pre-commit agent when both already ran in-session).
- Type hints everywhere; files ≤500 lines; functions <100 lines; max 3 nesting levels.
- New env vars: add to `src/config.py` with defaults AND `.env.example`, document in `docs/features/`.
- New constants use `SCREAMING_SNAKE_CASE` with units (`_SECONDS`, `_CHARS`).
- Auto-format hook runs after every Edit/Write; imports can be moved inside function bodies if the hook strips module-level ones between edits.
- Never introduce module-level per-user mutable state (4 gunicorn workers in prod) — cross-request state goes to DB/kv_store; in-process pools (sandbox/browser sessions) are per-worker by design and must tolerate that.

---

## Phase 0 — TODO entries + small fixes

### Task 1: TODO.md deferred entries

**Files:**
- Modify: `TODO.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Edit TODO.md**

Under `## AI-Agent Best Practices` add:

```markdown
- [ ] **Browser action batching** - `browser.py` allows one action per LLM round-trip, so "log in and check X" costs 6+ full model rounds. Accept an `actions: []` batch for mechanical sequences and return richer post-action state (URL + title + element summary) to cut observation rounds. Longer term: a11y-tree snapshots with stable element refs instead of text extraction.
- [ ] **Cross-turn tool digests** - history rebuilds assistant turns as plain text; prior turns' tool results are dropped (only `tools_used`/`tool_summary` survive), so "what did that article say?" forces a re-fetch. Persist a compact per-turn digest (~300 chars: URLs fetched + key facts) in message metadata and surface it via `MSG_CONTEXT`.
- [ ] **Mid-run steering** - no way to redirect a running multi-round turn ("stop, wrong ticker"). Cheap approximation: per-request cancel/interject flag checked between graph rounds (`check_tool_results` is the natural seam), injecting the user's interjection as guidance. Needs a small frontend affordance next to the stop button.
- [ ] **MSG_CONTEXT migration** - the ~60-line multi-chunk echo-stripping state machine in `agent.py:stream_chat_events` exists because metadata is inlined into message content as HTML comments. If Gemini's API grows first-class per-message metadata, migrate and delete the stripping.
```

In the existing `Model routing / tiering` entry, fix the stale model name `gemini-3.5-flash` → `gemini-3.7-flash` and stale pricing note (rates live in `Config.MODEL_PRICING`).

- [ ] **Step 2: Commit**

```bash
git add TODO.md && git commit -m "chore(todo): add deferred agent-improvement items from Aug 2026 agent review"
```

### Task 2: Narrow transient-error detection in retry.py

**Files:**
- Modify: `src/agent/retry.py`
- Test: `tests/unit/test_retry.py` (extend existing or create)

**Interfaces:**
- Produces: `is_transient_error(error: Exception) -> bool` (same signature, better behavior).

- [ ] **Step 1: Write failing tests**

```python
def test_transient_pattern_ignored_in_payload_tail() -> None:
    # A tool payload embedded in an exception message must not look transient
    err = ValueError("Unexpected tool output: " + "x" * 400 + " connection reset by peer")
    assert is_transient_error(err) is False

def test_transient_detected_via_cause_chain() -> None:
    inner = TimeoutError("read timed out")
    outer = RuntimeError("wrapped by SDK")
    outer.__cause__ = inner
    assert is_transient_error(outer) is True

def test_transient_pattern_near_message_start_still_matches() -> None:
    assert is_transient_error(Exception("429 Resource has been exhausted")) is True
```

- [ ] **Step 2: Run tests, verify the first two FAIL** (`pytest tests/unit/test_retry.py -v`)

- [ ] **Step 3: Implement**

In `retry.py`, add `_PATTERN_SCAN_CHARS = 300` and replace `is_transient_error`:

```python
def is_transient_error(error: Exception) -> bool:
    # Walk the cause chain: provider SDKs wrap transient errors in their own
    # exception types (e.g. ChatGoogleGenerativeAIError around a 429)
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TRANSIENT_EXCEPTIONS):
            return True
        current = current.__cause__ or current.__context__

    # Pattern-match only the start of the message: exception strings can embed
    # tool/page payloads whose text ("timeout", "connection reset") is data,
    # not an error condition
    error_msg = str(error)[:_PATTERN_SCAN_CHARS].lower()
    return any(pattern in error_msg for pattern in TRANSIENT_ERROR_PATTERNS)
```

- [ ] **Step 4: Run tests, verify PASS; run full suite + lint**
- [ ] **Step 5: Commit** — `fix(agent): walk cause chain and cap pattern scan in transient-error detection`

### Task 3: Wire trigger message through execute_agent

**Files:**
- Modify: `src/agent/executor.py`
- Test: `tests/unit/test_executor.py` (extend existing or create)

**Interfaces:**
- Produces: `_build_trigger_message(trigger_type: str, extra_message: str | None = None) -> str`; `execute_agent(..., extra_message: str | None = None)`; `AgentExecutor.run(message: str = "")` forwards it.

- [ ] **Step 1: Write failing tests**

```python
from src.agent.executor import _build_trigger_message

def test_trigger_message_includes_extra() -> None:
    msg = _build_trigger_message("agent_trigger", "Focus on AAPL earnings")
    assert msg.startswith("[Triggered by another agent at ")
    assert "Message from triggering agent: Focus on AAPL earnings" in msg

def test_trigger_message_ignores_default_continue() -> None:
    assert "Message from" not in _build_trigger_message("agent_trigger", "Continue")
    assert "Message from" not in _build_trigger_message("scheduled", None)
```

- [ ] **Step 2: Verify FAIL**
- [ ] **Step 3: Implement**

Extract the `trigger_messages` dict (executor.py:250-255) into:

```python
def _build_trigger_message(trigger_type: str, extra_message: str | None = None) -> str:
    """Build the synthetic user message that starts an autonomous run.

    extra_message carries instructions from a triggering agent (trigger_agent's
    `message` arg). "Continue" is the legacy default and means "no message".
    """
    now = datetime.now(UTC)
    templates = {
        "scheduled": f"[Scheduled run at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "manual": f"[Manual trigger at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
        "agent_trigger": f"[Triggered by another agent at {now.strftime('%Y-%m-%d %H:%M UTC')}]",
    }
    message = templates.get(trigger_type, f"[Triggered: {trigger_type}]")
    extra = (extra_message or "").strip()
    if extra and extra != "Continue":
        message += f"\n\nMessage from triggering agent: {extra}"
    return message
```

- `execute_agent(...)` gains `extra_message: str | None = None`, calls `_build_trigger_message(trigger_type, extra_message)`.
- `AgentExecutor.run(self, message: str = "")` passes `extra_message=message` to `execute_agent` and drops the "currently unused" docstring note.

- [ ] **Step 4: Verify PASS; full suite + lint**
- [ ] **Step 5: Commit** — `feat(agents): pass trigger_agent message through to the triggered agent`

---

## Phase 1 — Persistent sandbox sessions

### Task 4: Session pool module

**Files:**
- Create: `src/agent/tools/sandbox_sessions.py`
- Test: `tests/unit/test_sandbox_sessions.py`

**Interfaces:**
- Produces: `SandboxSessionPool(factory, max_sessions, ttl_seconds)` with `.session(key: str | None)` contextmanager, `.cleanup_expired() -> int`, `.close_all() -> None`; module singleton `get_sandbox_pool() -> SandboxSessionPool` (lazily builds factory from Config, starts a 60s cleanup daemon thread using the double-checked-lock pattern from `tool_results.py`).

- [ ] **Step 1: Write failing tests** (fake session objects; no Docker)

```python
class FakeSession:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
    def open(self) -> None:
        self.opened = True
    def close(self) -> None:
        self.closed = True

def make_pool(**kw):
    from src.agent.tools.sandbox_sessions import SandboxSessionPool
    return SandboxSessionPool(factory=FakeSession, max_sessions=2, ttl_seconds=100, **kw)

def test_session_reused_for_same_key() -> None:
    pool = make_pool()
    with pool.session("conv-1") as s1:
        pass
    with pool.session("conv-1") as s2:
        pass
    assert s1 is s2 and s1.opened and not s1.closed

def test_ephemeral_session_for_none_key_closed_after_use() -> None:
    pool = make_pool()
    with pool.session(None) as s:
        pass
    assert s.closed

def test_lru_eviction_closes_oldest() -> None:
    pool = make_pool()
    with pool.session("a") as sa: pass
    with pool.session("b"): pass
    with pool.session("c"): pass  # evicts "a"
    assert sa.closed

def test_broken_session_replaced() -> None:
    pool = make_pool()
    with pytest.raises(RuntimeError):
        with pool.session("conv-1") as s1:
            raise RuntimeError("run failed")
    assert s1.closed
    with pool.session("conv-1") as s2:
        pass
    assert s2 is not s1

def test_ttl_cleanup() -> None:
    pool = make_pool()
    with pool.session("a") as sa: pass
    pool._entries["a"].last_used -= 1000  # age it
    assert pool.cleanup_expired() == 1
    assert sa.closed
```

- [ ] **Step 2: Verify FAIL (module missing)**
- [ ] **Step 3: Implement `sandbox_sessions.py`**

```python
"""Per-conversation Docker sandbox session pool.

execute_code used to create and tear down a container per call (~1-2s startup
each time). Reusing a per-conversation session makes repeated executions fast
and gives code a persistent filesystem (/work) across calls. Each run() is
still a fresh Python process - variables do NOT persist, files do.

Mirrors the browser.py session pattern: LRU cap + TTL + background cleanup.
Pools are per-gunicorn-worker by design (a conversation may hit a different
worker and get a fresh session - correctness never depends on reuse).
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 60


@dataclass
class _Entry:
    session: Any
    last_used: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class SandboxSessionPool:
    def __init__(
        self,
        factory: Callable[[], Any],
        max_sessions: int,
        ttl_seconds: float,
    ) -> None:
        self._factory = factory
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        self._pool_lock = threading.Lock()

    def _open_session(self) -> Any:
        session = self._factory()
        session.open()
        return session

    def _close_quietly(self, session: Any) -> None:
        try:
            session.close()
        except Exception:
            logger.warning("Failed to close sandbox session", exc_info=True)

    @contextmanager
    def session(self, key: str | None) -> Iterator[Any]:
        """Yield a session for `key`; None means ephemeral (open/close per call).

        A raise inside the with-block marks the pooled session broken: it is
        closed and removed so the next call gets a fresh one.
        """
        if key is None:
            session = self._open_session()
            try:
                yield session
            finally:
                self._close_quietly(session)
            return

        with self._pool_lock:
            entry = self._entries.pop(key, None)
            if entry is None:
                entry = _Entry(session=self._open_session(), last_used=time.monotonic())
            self._entries[key] = entry  # re-insert = move to MRU position
            self._evict_over_capacity_locked()

        with entry.lock:  # serialize runs against one container
            try:
                yield entry.session
                entry.last_used = time.monotonic()
            except Exception:
                with self._pool_lock:
                    if self._entries.get(key) is entry:
                        del self._entries[key]
                self._close_quietly(entry.session)
                raise

    def _evict_over_capacity_locked(self) -> None:
        while len(self._entries) > self._max_sessions:
            oldest_key = next(iter(self._entries))
            entry = self._entries.pop(oldest_key)
            logger.info("Evicting sandbox session (LRU)", extra={"key": oldest_key})
            self._close_quietly(entry.session)

    def cleanup_expired(self) -> int:
        now = time.monotonic()
        closed = 0
        with self._pool_lock:
            expired = [k for k, e in self._entries.items() if now - e.last_used > self._ttl_seconds]
            entries = [self._entries.pop(k) for k in expired]
        for entry in entries:
            self._close_quietly(entry.session)
            closed += 1
        if closed:
            logger.info("Cleaned up expired sandbox sessions", extra={"count": closed})
        return closed

    def close_all(self) -> None:
        with self._pool_lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            self._close_quietly(entry.session)
```

Singleton accessor (same file): `get_sandbox_pool()` builds `factory` as a closure creating `SandboxSession(image=Config.CODE_SANDBOX_IMAGE, runtime_configs=..., **_SANDBOX_SESSION_KWARGS)` — import those from `code_execution` **inside the function** (avoids a cycle; auto-format hook also can't strip it). Start one daemon cleanup thread (double-checked lock + `atexit.register(pool.close_all)`), looping `time.sleep(_CLEANUP_INTERVAL_SECONDS); pool.cleanup_expired()`.

- [ ] **Step 4: Verify PASS; lint**
- [ ] **Step 5: Commit** — `feat(sandbox): add per-conversation sandbox session pool`

### Task 5: Use the pool in execute_code + persistent /work

**Files:**
- Modify: `src/agent/tools/code_execution.py`, `src/config.py`, `.env.example`
- Test: `tests/unit/test_code_execution.py` (extend existing)

**Interfaces:**
- Consumes: `get_sandbox_pool().session(conversation_id)`.
- Config produced: `CODE_SANDBOX_MAX_SESSIONS: int = 2`, `CODE_SANDBOX_SESSION_TTL_SECONDS: int = 900`.

- [ ] **Step 1: Write failing tests**

```python
def test_wrapped_code_resets_output_and_creates_work() -> None:
    from src.agent.tools.code_execution import _wrap_user_code
    wrapped = _wrap_user_code("print('hi')")
    assert "shutil.rmtree('/output', ignore_errors=True)" in wrapped
    assert "os.makedirs('/work', exist_ok=True)" in wrapped

def test_execute_code_uses_pooled_session_for_conversation(monkeypatch) -> None:
    # Patch get_sandbox_pool to a stub pool; set conversation context;
    # assert pool.session() was called with the conversation id.
    ...
```

(Write the second test with a `MagicMock` pool whose `.session` is a contextmanager yielding a fake session with a canned `run()` result; assert `pool.session.call_args[0][0] == "conv-42"` after calling `execute_code.func("print(1)")` with `set_conversation_context("conv-42", "user-1")` and Docker availability patched true.)

- [ ] **Step 2: Verify FAIL**
- [ ] **Step 3: Implement**

1. `_wrap_user_code` preamble becomes:

```python
import os, shutil
shutil.rmtree('/output', ignore_errors=True)
os.makedirs('/output', exist_ok=True)
os.makedirs('/work', exist_ok=True)
```

2. In `execute_code`, replace the `with SandboxSession(...) as session:` block with:

```python
from src.agent.tools.context import get_conversation_context
from src.agent.tools.sandbox_sessions import get_sandbox_pool

conversation_id, _user_id = get_conversation_context()
with get_sandbox_pool().session(conversation_id) as session:
    result = session.run(wrapped_code)
    ...  # existing extraction logic unchanged
```

3. Docstring: under Limitations replace the two NO-network lines' surroundings with an added persistence note: "Files saved to `/work/` persist across execute_code calls within this conversation (variables do NOT persist — each call is a fresh process). `/output/` is cleared at the start of every call."
4. Config + `.env.example`: `CODE_SANDBOX_MAX_SESSIONS=2`, `CODE_SANDBOX_SESSION_TTL_SECONDS=900`.

- [ ] **Step 4: Verify PASS; full suite + lint; manual smoke** — `make dev`, ask the chat to save a file to /work then read it in a second execute_code call.
- [ ] **Step 5: Update docs** — `docs/features/agents.md` code-execution section: session reuse semantics + new env vars.
- [ ] **Step 6: Commit** — `feat(sandbox): reuse per-conversation sandbox sessions with persistent /work`

---

## Phase 2 — Remove planning subsystem, add thinking-level plumbing

### Task 6: Delete planning

**Files:**
- Modify: `src/agent/graph.py`, `src/config.py`, `.env.example`, `tests/unit/test_graph.py`, `tests/unit/test_chat_agent_helpers.py`
- Docs: `docs/features/agents.md` (or wherever planning is described), memory topic files mention it — update `docs/` only.

**Interfaces:**
- Removes: `should_plan`, `plan_node`, `PLANNING_PROMPT`, `PLANNING_DECISION_PROMPT`, `AgentState.plan`, `Config.AGENT_PLANNING_ENABLED`, `Config.AGENT_PLANNING_MIN_LENGTH`.
- Keeps: `AgentState.tool_retries`, `AgentState.tool_rounds`, `chat_node(state, model, use_cache)` minus plan handling, `CHAT_NODE_NAME` filtering in `agent.py` (harmless and still filters nothing-else).

- [ ] **Step 1: Delete planning tests** in `test_graph.py` / `test_chat_agent_helpers.py` (grep `should_plan|plan_node|AGENT_PLANNING|"plan"`), and add a regression test:

```python
def test_graph_entry_is_chat() -> None:
    graph = create_chat_graph("gemini-3.7-flash", with_tools=True, tools=[some_dummy_tool])
    compiled = compile_graph(graph)
    assert "plan" not in compiled.get_graph().nodes
```

- [ ] **Step 2: Implement removal**
  - `graph.py`: delete `should_plan`, `plan_node`, both prompt constants, the `plan: str` state field, plan-injection block in `chat_node` (lines 340-361) and plan-clearing (`result["plan"]`), the `plan` node registration + conditional entry edges; both branches now `graph.set_entry_point("chat")`.
  - `config.py`: delete `AGENT_PLANNING_ENABLED`, `AGENT_PLANNING_MIN_LENGTH` (and the comment block); `.env.example` likewise.
  - `agent.py`: no changes needed (verify `is_planning` flag is the planner-dashboard feature, NOT this subsystem — do not touch it).
- [ ] **Step 3: Full suite + lint** (`make test`, `make lint`).
- [ ] **Step 4: Update docs** — remove planning-node references from `docs/` pages and CLAUDE.md's agent description if present.
- [ ] **Step 5: Commit** — `refactor(agent): remove disabled planning subsystem (classifier + plan node)`

### Task 7: thinking_level plumbing

**Files:**
- Modify: `src/agent/graph.py` (`create_chat_model`), `src/config.py`
- Test: `tests/unit/test_graph.py`

**Interfaces:**
- Produces: `Config.MODELS[<id>].get("thinking_level")` honored by `create_chat_model`.

- [ ] **Step 1: Failing test**

```python
def test_create_chat_model_passes_thinking_level(monkeypatch) -> None:
    monkeypatch.setitem(Config.MODELS, "gemini-3.1-pro-preview",
                        {**Config.MODELS["gemini-3.1-pro-preview"], "thinking_level": "high"})
    model = create_chat_model("gemini-3.1-pro-preview", with_tools=False)
    assert model.thinking_level == "high"

def test_create_chat_model_defaults_no_thinking_level() -> None:
    model = create_chat_model("gemini-3.7-flash", with_tools=False)
    assert model.thinking_level is None
```

- [ ] **Step 2: Implement** — in `create_chat_model`, before building `kwargs`:

```python
thinking_level = Config.MODELS.get(model_name, {}).get("thinking_level")
if thinking_level:
    kwargs["thinking_level"] = thinking_level
```

Leave both `MODELS` entries WITHOUT the key for now (API defaults); add a comment documenting the knob. The user-facing thinking toggle stays in TODO.

- [ ] **Step 3: Verify PASS; suite + lint**
- [ ] **Step 4: Commit** — `feat(agent): honor per-model thinking_level from MODELS config`

---

## Phase 3 — Search provider + composite research tool

### Task 8: Pluggable search provider

**Files:**
- Create: `src/utils/search_provider.py`
- Modify: `src/agent/tools/web.py` (`_search_one`), `src/config.py`, `.env.example`
- Test: `tests/unit/test_search_provider.py`

**Interfaces:**
- Produces: `search_web(query: str, num_results: int) -> list[dict[str, str]]` (dicts with `title`, `url`, `snippet`), `SearchProviderError(Exception)` with `.retriable: bool`, `active_provider() -> str` ("brave" | "ddgs").
- Config: `BRAVE_SEARCH_API_KEY: str = ""` (empty → ddgs).

- [ ] **Step 1: Failing tests** — brave path (httpx mocked via `respx` or monkeypatched `httpx.get`) maps `web.results[].{title,url,description}` → contract dicts; ddgs path selected when key empty; brave 429 raises `SearchProviderError(retriable=True)`.
- [ ] **Step 2: Implement**

```python
"""Search provider abstraction: Brave Search API with DDGS fallback."""
import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_TIMEOUT_SECONDS = 15


class SearchProviderError(Exception):
    def __init__(self, message: str, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


def active_provider() -> str:
    return "brave" if Config.BRAVE_SEARCH_API_KEY else "ddgs"


def search_web(query: str, num_results: int) -> list[dict[str, str]]:
    """Return [{title, url, snippet}] or raise SearchProviderError."""
    if active_provider() == "brave":
        return _search_brave(query, num_results)
    return _search_ddgs(query, num_results)


def _search_brave(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        response = httpx.get(
            _BRAVE_ENDPOINT,
            params={"q": query, "count": num_results},
            headers={"X-Subscription-Token": Config.BRAVE_SEARCH_API_KEY,
                     "Accept": "application/json"},
            timeout=_BRAVE_TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            raise SearchProviderError("Brave Search rate limited", retriable=True)
        response.raise_for_status()
        items = response.json().get("web", {}).get("results", [])
        return [
            {"title": i.get("title", "No title"), "url": i.get("url", ""),
             "snippet": i.get("description", "")}
            for i in items[:num_results]
        ]
    except httpx.HTTPError as e:
        raise SearchProviderError(f"Brave Search failed: {e}") from e


def _search_ddgs(query: str, num_results: int) -> list[dict[str, str]]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        return [
            {"title": r.get("title", "No title"), "url": r.get("href", ""),
             "snippet": r.get("body", "")}
            for r in results
        ]
    except RatelimitException as e:
        raise SearchProviderError("Search rate limited", retriable=True) from e
    except TimeoutException as e:
        raise SearchProviderError("Search timed out", retriable=True) from e
    except DDGSException as e:
        raise SearchProviderError(str(e)) from e
```

Refactor `web.py:_search_one` to call `search_web` and map `SearchProviderError` → the existing `{"query", "results": [], "error": ...}` dict (tool JSON contract unchanged; keep the `retriable` flag in the error dict as `"retriable": e.retriable`). Delete the now-unused ddgs imports from web.py.

- [ ] **Step 3: Verify PASS (incl. existing web_search tests); lint**
- [ ] **Step 4: `.env.example` + docs** — `BRAVE_SEARCH_API_KEY=` with a comment ("free tier: 2k queries/mo; empty = DuckDuckGo").
- [ ] **Step 5: Commit** — `feat(search): pluggable search provider (Brave with DDGS fallback)`

### Task 9: Extract fetch_page_text from fetch_url

**Files:**
- Modify: `src/agent/tools/web.py`
- Test: `tests/unit/test_web_tools.py` (extend existing)

**Interfaces:**
- Produces: `_fetch_response(url: str) -> tuple[httpx.Response | None, str | None]` (response or error; owns SSRF validation + manual redirect loop) and `fetch_page_text(url: str, max_chars: int | None = None) -> tuple[str | None, str | None]` returning `(markdown_text, None)` for HTML/text, `(None, error)` otherwise (binary → `(None, "binary content: <mime> — use fetch_url")`). **No behavior change to `fetch_url`.**

- [ ] **Step 1: Tests first** — `fetch_page_text` happy path (mocked transport returning HTML), SSRF-blocked URL returns error, binary content returns error; existing `fetch_url` tests keep passing untouched.
- [ ] **Step 2: Implement** — move the client/redirect logic from `fetch_url` into `_fetch_response`; `fetch_url` calls it then branches by category exactly as today; `fetch_page_text` calls it and handles only html/text categories via `_extract_text_from_html` / plain text with the `max_chars` cap. Note: `web.py` is at 431 lines; if this pushes past 500, move `fetch_page_text` + `_fetch_response` + extraction helpers to a new `src/agent/tools/web_fetch.py` and have `web.py` re-import (no back-compat shims for *external* callers — update imports).
- [ ] **Step 3: Verify PASS; suite + lint**
- [ ] **Step 4: Commit** — `refactor(web): extract reusable fetch_page_text/_fetch_response`

### Task 10: research tool

**Files:**
- Create: `src/agent/tools/research.py`
- Modify: `src/agent/tools/__init__.py`, `src/agent/tool_display.py`, `src/agent/permissions.py` (`ALWAYS_SAFE_TOOLS`), `src/agent/prompts.py` (guidance in `TOOLS_SYSTEM_PROMPT_BASE`), `src/config.py`, `.env.example`
- Test: `tests/unit/test_research_tool.py`

**Interfaces:**
- Consumes: `search_web` (Task 8), `fetch_page_text` (Task 9), `wrap_untrusted_content`.
- Produces: `@tool research(question: str, queries: list[str] | None = None, max_sources: int = 0) -> str` returning JSON.
- Config: `RESEARCH_MAX_SOURCES=5`, `RESEARCH_PER_SOURCE_MAX_CHARS=4000`, `RESEARCH_FETCH_WORKERS=4`.

- [ ] **Step 1: Failing tests** — with `search_web` and `fetch_page_text` monkeypatched: (a) dedupes URLs across queries and interleaves by rank; (b) caps sources at `RESEARCH_MAX_SOURCES`; (c) failed fetches degrade to snippet-only entries with `"error"`; (d) result JSON has `question`, `sources[].{url,title,content|error}`, `unfetched[]`, `_warning`; (e) content is wrapped with untrusted markers.
- [ ] **Step 2: Implement**

```python
"""Composite research tool: search + fetch top sources in ONE tool round.

Each tool round re-invokes the model with the full accumulated context, so the
classic search -> read -> search -> read loop pays for the whole conversation
on every step. This tool collapses the common case into a single round.
Deterministic: no nested LLM call (delegate_task is the agentic variant).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.web import fetch_page_text, wrap_untrusted_content
from src.config import Config
from src.utils.logging import get_logger
from src.utils.search_provider import SearchProviderError, search_web

logger = get_logger(__name__)


def _ranked_unique_urls(queries: list[str], per_query: int) -> list[dict[str, str]]:
    """Interleave results by rank across queries, dedup by URL."""
    per_query_results: list[list[dict[str, str]]] = []
    for query in queries:
        try:
            per_query_results.append(search_web(query, per_query))
        except SearchProviderError as e:
            logger.warning("research: search failed", extra={"query": query, "error": str(e)})
            per_query_results.append([])
    seen: set[str] = set()
    ordered: list[dict[str, str]] = []
    for rank in range(per_query):
        for results in per_query_results:
            if rank < len(results) and results[rank]["url"] and results[rank]["url"] not in seen:
                seen.add(results[rank]["url"])
                ordered.append(results[rank])
    return ordered


@tool
def research(question: str, queries: list[str] | None = None, max_sources: int = 0) -> str:
    """Research a question: search the web AND read the top sources in one call.

    Prefer this over separate web_search + fetch_url rounds whenever a question
    needs information from multiple pages (comparisons, "what happened with X",
    current facts needing corroboration). One research call replaces an entire
    search->fetch->fetch loop.

    Args:
        question: The question you are trying to answer.
        queries: Optional search queries (different phrasings/angles). Defaults
            to the question itself. Capped at the web_search batch limit.
        max_sources: How many top pages to read (default from config, max 8).

    Returns:
        JSON: {question, sources: [{url, title, content|error}], unfetched:
        [{title, url, snippet}], _warning}. Content is external, untrusted data.
    """
    ...
```

Body: normalize `queries` (default `[question]`, strip/dedupe, cap `Config.WEB_SEARCH_MAX_BATCH_QUERIES`); `n_sources = max_sources or Config.RESEARCH_MAX_SOURCES`, clamp 1–8; `candidates = _ranked_unique_urls(queries, Config.WEB_SEARCH_DEFAULT_RESULTS)`; fetch first `n_sources` with `ThreadPoolExecutor(max_workers=Config.RESEARCH_FETCH_WORKERS)` calling `fetch_page_text(url, Config.RESEARCH_PER_SOURCE_MAX_CHARS)`; build `sources` (content wrapped via `wrap_untrusted_content(text, url)`, or `{"error": err}` entries) and `unfetched` = next 5 candidates as snippets; return `json.dumps({...,"_warning": _SEARCH_WARNING-equivalent})`. If every search errored: `{"error": "...", "retriable": true}`.

Registration:
- `tools/__init__.py`: import; add to `get_available_tools()` right after `web_search`; add to the two autonomous baselines (`get_tools_for_request` restricted branch and `get_tools_for_agent`) next to `web_search`; add `"research"` to `_TOOL_MAP`; add to `__all__`.
- `permissions.py`: add `"research"` to `ALWAYS_SAFE_TOOLS`.
- `tool_display.py`: `TOOL_METADATA["research"] = {"label": "Researching", "label_past": "Researched", "icon": "search"}`; `extract_tool_detail` returns the `question` arg (mirror the `web_search` query case).
- `prompts.py` `TOOLS_SYSTEM_PROMPT_BASE`: add one bullet: "For questions needing multiple sources, use `research` (search + reads top pages in one step) instead of separate web_search/fetch_url rounds." (This changes the static prompt → context cache re-creates itself via content hash; no action needed.)

- [ ] **Step 3: Verify PASS; suite + lint; manual smoke via `make dev`** — ask a multi-source question, confirm one `research` round replaces the search/fetch loop.
- [ ] **Step 4: Docs** — `docs/features/agents.md` tool table + research description.
- [ ] **Step 5: Commit** — `feat(tools): add composite research tool (search + fetch in one round)`

---

## Phase 4 — Delegate subagent tool

### Task 11: ChatAgent overrides (cache opt-out + system prompt)

**Files:**
- Modify: `src/agent/agent.py`
- Test: `tests/unit/test_chat_agent_helpers.py`

**Interfaces:**
- Produces: `ChatAgent(..., enable_context_cache: bool = True, system_prompt_override: str | None = None)`. Override implies uncached mode; `_build_messages` uses `SystemMessage(system_prompt_override)` instead of `get_system_prompt(...)` when set.

- [ ] **Step 1: Failing tests** — (a) `ChatAgent(enable_context_cache=False)._cached_content_name is None` (patch `get_cached_content_name` to fail the test if called); (b) with `system_prompt_override="You are a test."`, `_build_messages("hi")[0]` is a `SystemMessage` with exactly that content.
- [ ] **Step 2: Implement** — store both params; in `__init__`, skip the cache-profile block when `not enable_context_cache or system_prompt_override`; in `_build_messages`, branch at the top of the system-prompt section.
- [ ] **Step 3: Verify PASS; suite + lint**
- [ ] **Step 4: Commit** — `feat(agent): ChatAgent cache opt-out and system prompt override`

### Task 12: delegate_task tool

**Files:**
- Create: `src/agent/tools/delegate.py`
- Modify: `src/agent/prompts.py` (add `DELEGATE_SYSTEM_PROMPT` + one bullet in `TOOLS_SYSTEM_PROMPT_BASE`), `src/agent/tools/__init__.py`, `src/agent/tool_display.py`, `src/config.py`, `.env.example`
- Test: `tests/unit/test_delegate_tool.py`

**Interfaces:**
- Consumes: `ChatAgent` (Task 11), `research`/`web_search`/`fetch_url`/`cite_sources` tools, `extract_cited_sources`, `check_autonomous_permission`.
- Produces: `@tool delegate_task(task: str, expected_output: str = "") -> str` returning JSON `{result, sources, _delegate_usage: {model, input_tokens, output_tokens, cached_input_tokens, tool_rounds}}`.
- Config: `DELEGATE_MODEL = DEFAULT_MODEL`.

- [ ] **Step 1: Failing tests** — with `ChatAgent` patched (mock `chat_batch` returning the standard 4-tuple): (a) result JSON carries text, sources extracted from `result_messages`, `_delegate_usage` mirrors `usage_info` + model; (b) nested delegation returns an error JSON without constructing ChatAgent; (c) empty task rejected.
- [ ] **Step 2: Implement**

```python
"""Delegate a research task to a scoped subagent (context isolation).

The subagent runs its own multi-round tool loop (research/web/fetch) in a
FRESH context: the 15k-char page dumps it reads never enter the main
conversation's history - only its final digest does. This is both a quality
lever (deep multi-page work without blowing the main round cap) and the
biggest cost lever (the main conversation re-bills its whole history every
round; the subagent's history starts empty).
"""
import contextvars
import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_in_delegate: contextvars.ContextVar[bool] = contextvars.ContextVar("_in_delegate", default=False)


@tool
def delegate_task(task: str, expected_output: str = "") -> str:
    """Delegate a self-contained research task to a focused subagent.

    Use for DEEP research (3+ sources, multi-step digging, comparisons needing
    verification) so the bulky intermediate pages stay out of this
    conversation. The subagent can search the web and read pages; it returns a
    digest with sources. Give it a complete, self-contained brief - it cannot
    see this conversation.

    Args:
        task: Complete description of what to find out (include all context).
        expected_output: Optional description of the desired answer format.

    Returns:
        JSON: {result, sources: [{title, url}]}.
    """
    check_autonomous_permission("delegate_task", {"task": task[:200]})
    if _in_delegate.get():
        return json.dumps({"error": "Nested delegation is not allowed.", "retriable": False})
    if not task or not task.strip():
        return json.dumps({"error": "task must not be empty.", "retriable": False})

    from src.agent.agent import ChatAgent
    from src.agent.content import extract_cited_sources
    from src.agent.prompts import DELEGATE_SYSTEM_PROMPT
    from src.agent.tools import cite_sources, fetch_url, research, web_search

    prompt = task.strip()
    if expected_output.strip():
        prompt += f"\n\nExpected output: {expected_output.strip()}"

    token = _in_delegate.set(True)
    try:
        agent = ChatAgent(
            model_name=Config.DELEGATE_MODEL,
            with_tools=True,
            tools=[research, web_search, fetch_url, cite_sources],
            enable_context_cache=False,
            system_prompt_override=DELEGATE_SYSTEM_PROMPT,
        )
        response_text, _tool_results, usage_info, result_messages = agent.chat_batch(text=prompt)
    except Exception as e:
        logger.error("delegate_task failed", extra={"error": str(e)}, exc_info=True)
        return json.dumps({"error": f"Delegated task failed: {e}"})
    finally:
        _in_delegate.reset(token)

    sources = extract_cited_sources(result_messages)
    payload: dict[str, Any] = {
        "result": response_text or "(subagent produced no text)",
        "sources": sources,
        # Read by the cost pipeline (calculate_and_save_message_cost), not the LLM-
        # relevant part of the result; kept at top level so it survives
        # _full_result stripping and lands in the saved tool results.
        "_delegate_usage": {
            "model": Config.DELEGATE_MODEL,
            "input_tokens": usage_info.get("input_tokens", 0),
            "output_tokens": usage_info.get("output_tokens", 0),
            "cached_input_tokens": usage_info.get("cached_input_tokens", 0),
            "tool_rounds": usage_info.get("tool_rounds", 0),
        },
    }
    return json.dumps(payload)
```

`DELEGATE_SYSTEM_PROMPT` (prompts.py, ~15 lines): focused research assistant; you have research/web_search/fetch_url; be thorough but efficient (prefer one `research` call); ALWAYS call cite_sources with the URLs you actually used; final answer = dense digest of findings, no filler; if you cannot find something, say so explicitly.

Registration: `get_available_tools()` (interactive incl. anonymous — its tools are read-only web); `_TOOL_MAP["delegate_task"]` (agents get it only via explicit grant — NOT added to autonomous baselines; `check_autonomous_permission` enforces); `TOOL_METADATA["delegate_task"] = {"label": "Delegating research", "label_past": "Delegated research", "icon": "sparkles"}`; `extract_tool_detail` → `task` arg truncated to the same length web_search uses. `TOOLS_SYSTEM_PROMPT_BASE` bullet: "For deep research (3+ sources or multi-step digging) use `delegate_task` — a subagent does the reading and returns a digest, keeping this conversation small."

- [ ] **Step 3: Verify PASS; suite + lint; manual smoke** — delegate a research question in `make dev`, confirm tool chip + digest + sources.
- [ ] **Step 4: Commit** — `feat(tools): add delegate_task subagent for context-isolated research`

### Task 13: Delegate cost accounting

**Files:**
- Modify: `src/api/utils.py`, `src/utils/costs.py`
- Test: `tests/unit/test_costs.py` (extend)

**Interfaces:**
- Produces: `calculate_total_cost(..., tool_llm_cost: float = 0.0)` adds the component into the returned USD total; `calculate_delegate_cost_from_tool_results(tool_results) -> float` in `api/utils.py` (scans tool result JSON for top-level `_delegate_usage`, prices via `calculate_token_cost(usage["model"], ...)`); `calculate_and_save_message_cost` passes it.

- [ ] **Step 1: Failing tests** — tool_results containing a `_delegate_usage` entry yields the correctly priced extra cost; results without it yield 0.0; malformed JSON ignored.
- [ ] **Step 2: Implement** (mirror `calculate_image_generation_cost_from_tool_results` structure directly above it).
- [ ] **Step 3: Verify PASS; suite + lint**
- [ ] **Step 4: Commit** — `feat(costs): account delegated-subagent token spend in message cost`

---

## Phase 5 — Tiered memory + embeddings

### Task 14: Embeddings storage (migration + mixin)

**Files:**
- Create: `migrations/0049_add_embeddings.py`, `src/db/models/embeddings.py`
- Modify: `src/db/models/__init__.py` (mixin into `Database`, no dataclass needed)
- Test: `tests/unit/test_embeddings_db.py`

**Interfaces:**
- Produces: `db.upsert_embedding(user_id, kind, ref_id, model, dim, vector: bytes)`, `db.get_embeddings(user_id, kind) -> list[tuple[str, int, bytes]]` (ref_id, dim, vector), `db.delete_embedding(kind, ref_id)`, `db.count_embeddings(user_id, kind) -> int`, `db.get_message_rows_for_ids(user_id, message_ids) -> list[...]` (id, conversation_id, content, created_at, conversation_title — for semantic search rendering).

- [ ] **Step 1: Migration**

```python
"""Embeddings for semantic recall over memories and messages.

Brute-force cosine at family scale (a few thousand vectors) - no vector index.
kind: 'memory' | 'message'; ref_id: the source row id; vector: packed float32.
"""
from yoyo import step

__depends__ = {"0048_upgrade_fast_model"}

steps = [
    step(
        """
        CREATE TABLE embeddings (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(kind, ref_id)
        )
        """,
        "DROP TABLE embeddings",
    ),
    step(
        "CREATE INDEX idx_embeddings_user_kind ON embeddings(user_id, kind)",
        "DROP INDEX IF EXISTS idx_embeddings_user_kind",
    ),
]
```

- [ ] **Step 2: Failing tests** against a temp `Database` (existing test fixtures show the pattern in `tests/unit/test_*_db.py` — reuse their tmp-db fixture): upsert twice → one row, second wins; get/count scoped by user+kind; delete removes.
- [ ] **Step 3: Implement `EmbeddingsMixin`** following `MemoryMixin`'s `self._pool.get_connection()` / `self._execute_with_timing` pattern (UPSERT `ON CONFLICT(kind, ref_id) DO UPDATE SET vector=..., model=..., dim=..., created_at=...`). Wire into `class Database(...)` bases in `__init__.py`.
- [ ] **Step 4: Verify PASS (run migration in test fixture the same way existing db tests do); suite + lint**
- [ ] **Step 5: Commit** — `feat(db): embeddings table + mixin for semantic recall`

### Task 15: Embedding utility

**Files:**
- Create: `src/utils/embeddings.py`
- Modify: `src/config.py`, `.env.example`
- Test: `tests/unit/test_embeddings_util.py`

**Interfaces:**
- Produces: `embed_text(text: str) -> list[float] | None` (None on any failure — callers degrade gracefully), `pack_vector(vec: list[float]) -> bytes` / `unpack_vector(blob: bytes) -> list[float]` (float32 via `struct`), `cosine_similarity(a: list[float], b: list[float]) -> float`, `top_k_similar(query_vec, candidates: list[tuple[str, bytes]], k) -> list[tuple[str, float]]`, `embed_and_store_async(user_id, kind, ref_id, text) -> None` (daemon thread; embeds, packs, `db.upsert_embedding`; swallows+logs failures).
- Config: `EMBEDDING_MODEL = "gemini-embedding-001"`, `EMBEDDING_DIM = 768`, `EMBEDDINGS_ENABLED: bool = true` env-gated.

- [ ] **Step 1: Failing tests** — pack/unpack roundtrip; cosine of identical=1.0, orthogonal=0.0; `top_k_similar` ordering; `embed_text` returns None when the client raises (patch it).
- [ ] **Step 2: Implement** — genai client (same one context_cache uses; confirm at impl: `from google import genai; client = genai.Client(api_key=Config.GEMINI_API_KEY)`), `client.models.embed_content(model=..., contents=text[:8000], config={"output_dimensionality": Config.EMBEDDING_DIM})`, take `resp.embeddings[0].values`. Client cached module-level behind a lock.
- [ ] **Step 3: Verify PASS; lint**
- [ ] **Step 4: Commit** — `feat(embeddings): text embedding utility (pack/cosine/async store)`

### Task 16: Tiered memory injection + search_memory tool

**Files:**
- Modify: `src/agent/prompts.py` (`get_user_memories_list_prompt`, `MEMORY_SYSTEM_PROMPT`), `src/agent/tools/memory.py` (add `search_memory`), `src/agent/tools/__init__.py`, `src/agent/tool_display.py`, `src/config.py`, `.env.example`
- Test: `tests/unit/test_prompts_memory.py`, `tests/unit/test_memory_tool.py` (extend)

**Interfaces:**
- Config: `MEMORY_INJECT_FULL_MAX = 60`, `MEMORY_INJECT_RECENT_COUNT = 15`.
- Produces: `@tool search_memory(query: str) -> str`; tiered `get_user_memories_list_prompt` (same signature).

- [ ] **Step 1: Failing tests**
  - ≤ threshold: prompt contains every memory (current behavior preserved).
  - &gt; threshold: contains all protected/preference/goal entries; contains the most recently updated `MEMORY_INJECT_RECENT_COUNT` others; contains a line matching `r"\d+ more memories exist.*search_memory"`; omits the oldest non-core fact.
  - `search_memory`: substring hit returns id+category+content lines; no hits returns guidance; with embeddings present (patched `embed_text` + seeded vectors), a semantically-near memory ranks in results.
- [ ] **Step 2: Implement**
  - `get_user_memories_list_prompt`: after loading memories, if `len(memories) > Config.MEMORY_INJECT_FULL_MAX`: core = protected or category in {"preference","goal"}; rest sorted by `updated_at` desc, take `MEMORY_INJECT_RECENT_COUNT`; shown = core + recent (original order preserved); append `f"\n{hidden} more memories exist but are not shown. Use search_memory to find facts not listed here before saying you don't know something about the user."` Header shows `({shown_count} of {memory_count}/{limit} shown)`.
  - `search_memory` in `memory.py`: context via `get_conversation_context()`; substring match over `db.list_memories(user_id)` (content + category, casefolded); if `Config.EMBEDDINGS_ENABLED`, also `embed_text(query)` + `top_k_similar` over `db.get_embeddings(user_id, "memory")`, merge by id (substring hits first), cap 10; format like the injected JSON entries. Returns are the user's own data — no untrusted wrapper needed.
  - `MEMORY_SYSTEM_PROMPT`: add a short paragraph: above the injection threshold only core+recent memories are shown; use `search_memory` before concluding a fact is unknown.
  - Registration: `get_available_tools()` next to `manage_memory`; `_ANONYMOUS_EXCLUDED_TOOLS` += `"search_memory"`; `_TOOL_MAP` += entry; `TOOL_METADATA["search_memory"] = {"label": "Searching memory", "label_past": "Searched memory", "icon": "brain"}`.
- [ ] **Step 3: Verify PASS; suite + lint**
- [ ] **Step 4: Commit** — `feat(memory): tiered injection above threshold + search_memory tool`

### Task 17: Embedding write paths + backfill

**Files:**
- Modify: `src/agent/tools/memory.py` (`_apply_add`, `_apply_update`), `src/api/utils.py` (`save_message_to_db`), `src/agent/executor.py` (after `db.add_message` for the assistant response)
- Create: `scripts/backfill_embeddings.py`
- Test: `tests/unit/test_memory_tool.py` (extend)

**Interfaces:**
- Consumes: `embed_and_store_async(user_id, kind, ref_id, text)`.

- [ ] **Step 1: Failing test** — `_apply_add` schedules `embed_and_store_async(user_id, "memory", <new id>, content)` (patch it, assert called); `_apply_update` likewise; both no-op when `EMBEDDINGS_ENABLED` false.
- [ ] **Step 2: Implement** — one-line calls after successful DB writes (guarded by `Config.EMBEDDINGS_ENABLED`). In `save_message_to_db` and executor: embed the saved user message and assistant response (`kind="message"`, ref_id = message id, text = content[:8000], skip empty/whitespace). Backfill script: iterate users → memories + messages lacking embeddings (`LEFT JOIN embeddings`), embed with a small sleep (rate-limit courtesy), print progress; `--dry-run` flag.
- [ ] **Step 3: Verify PASS; suite + lint; run backfill against dev DB once**
- [ ] **Step 4: Commit** — `feat(embeddings): embed memories and messages at write time + backfill script`

### Task 18: Semantic search_conversations

**Files:**
- Modify: `src/agent/tools/conversation_search.py`
- Test: `tests/unit/test_conversation_search.py` (extend)

**Interfaces:**
- Consumes: `embed_text`, `top_k_similar`, `db.get_embeddings(user_id, "message")`, `db.get_message_rows_for_ids`.

- [ ] **Step 1: Failing test** — with FTS returning nothing and a seeded message embedding near the query vector (patch `embed_text`), `search_conversations` returns that conversation labelled `(semantic match)`; when `embed_text` returns None, FTS-only behavior is unchanged.
- [ ] **Step 2: Implement** — in `search_conversations`, after the FTS block: if `Config.EMBEDDINGS_ENABLED`, embed the query; `top_k_similar` over message embeddings (k = limit); drop ids already covered by FTS results and the current conversation; fetch rows via `db.get_message_rows_for_ids`; append rendered entries with a 200-char content snippet and `(semantic match)` marker. Update the tool docstring ("matches meaning as well as keywords").
- [ ] **Step 3: Verify PASS; suite + lint; manual smoke** — search an old conversation by paraphrase.
- [ ] **Step 4: Docs** — memory/search behavior in `docs/features/` memory page; note embeddings env vars.
- [ ] **Step 5: Commit** — `feat(search): semantic conversation search via embeddings`

---

## Phase 6 — Eval harness

### Task 19: Runner + seed cases

**Files:**
- Create: `evals/run.py`, `evals/cases/` (~8 YAML files), `evals/README.md`
- Modify: `Makefile` (`eval` target), `.gitignore` (`evals/results/`), `src/config.py` (`EVAL_JUDGE_MODEL = "gemini-3.1-pro-preview"`)
- Test: `tests/unit/test_eval_harness.py` (case loading + judge-response parsing only; no live API in CI)

**Interfaces:**
- Case schema (YAML): `id`, `description`, `user` (message str), optional `requires: [code_sandbox|browser|places]`, `expect: {rubric: str, required_tools?: [str], forbidden_tools?: [str], max_tool_rounds?: int}`.
- `evals/run.py --cases evals/cases --only <id>` → writes `evals/results/<timestamp>.json` + prints a markdown table; exit 0 always (informational).

- [ ] **Step 1: Failing tests** — `load_cases()` parses YAML into `EvalCase` dataclass and rejects missing `rubric`; `parse_judge_response('{"score": 4, "pass": true, "reasoning": "..."}')` → tuple; deterministic checks (`required_tools`/`max_tool_rounds`) evaluated from `usage_info`/tool names without any LLM.
- [ ] **Step 2: Implement `run.py`** —
  - MUST set `DATABASE_PATH` env to a fresh temp file and apply yoyo migrations (`from yoyo import get_backend, read_migrations`) BEFORE importing `src.*` (config reads env at import).
  - Per case: create eval user row, `ChatAgent(model_name=Config.DEFAULT_MODEL).chat_batch(text=case.user, user_id=..., user_name="Eval User")`; capture response, tool names (from `result_messages` ToolMessages), `usage_info`.
  - Deterministic checks first; then judge: one Flash-priced call to `EVAL_JUDGE_MODEL` with rubric + user message + response, forced-JSON instruction, `parse_judge_response`.
  - Output row: id, pass, score, tool_rounds, tokens, judge reasoning (first 120 chars).
  - Skips: case `requires` not satisfied → SKIPPED.
- [ ] **Step 3: Seed 8 cases** — `no_tool_simple` (capital question; forbidden_tools: [web_search, research]), `web_lookup_cited` (current-fact question; required_tools any-of research/web_search; rubric checks citation), `research_multi_source` (comparison; rubric: ≥2 sources), `memory_write` ("remember I'm vegetarian"; required_tools: [manage_memory]), `memory_respect` (pre-seeded memory; rubric: answer uses it without tools), `code_exec` (compound-interest calc; requires code_sandbox; required_tools: [execute_code]), `czech_reply` (Czech question; rubric: fluent Czech answer), `title_set` (first message; required_tools: [set_conversation_title]).
- [ ] **Step 4: Makefile** — `eval: ## Run agent eval harness (hits live Gemini API)` → `$(VENV_PYTHON) evals/run.py` (match existing Makefile venv conventions).
- [ ] **Step 5: Run `make eval` live once; fix obvious harness bugs; suite + lint**
- [ ] **Step 6: Commit** — `feat(evals): golden-case eval harness with LLM judge`

### Task 20: Docs + TODO closure

**Files:**
- Modify: `TODO.md` (replace the A3 entry: harness shipped, remaining = per-turn observability), `docs/README.md` + new `docs/testing/evals.md` (how to add cases, when to run: before/after prompt or tool-description changes), `CLAUDE.md` (one line in Quick Reference: `make eval`), `docs/features/agents.md` (delegate/research/memory-tier summaries if not already done in-phase).

- [ ] **Step 1: Write docs; run docs-updater agent to verify coverage of all six phases**
- [ ] **Step 2: Full suite + lint one last time**
- [ ] **Step 3: Commit** — `docs: document agent improvements (sandbox sessions, research, delegate, memory tiers, evals)`

---

## Self-Review Notes

- Spec coverage: Phase 0→Tasks 1-3, Phase 1→4-5, Phase 2→6-7, Phase 3→8-10, Phase 4→11-13, Phase 5→14-18, Phase 6→19-20. ✔
- Type consistency: `search_web` returns `list[dict[str,str]]` consumed by Task 10; `fetch_page_text` tuple contract consumed by Task 10; `_delegate_usage` key consumed by Task 13; `embed_and_store_async` signature consumed by Task 17. ✔
- Known impl-time verifications (flagged, not placeholders): exact genai embed API call shape (Task 15), existing tmp-db test fixture name (Task 14), Makefile venv variable name (Task 19).
