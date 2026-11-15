# Title Speed and Silence Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new chat's title no longer delays `done`, and each turn records its longest silence inside a model call.

**Architecture:** The title call moves to Flash-Lite with a 10 s timeout and no retries, still inside the save. `CancelOnToken` (already on every chat model call) tracks the gaps between chunks; `ModelTiming` keeps the turn's maximum, written into `turn_timing` as `max_silence_ms`.

**Tech Stack:** Python, LangChain Google GenAI.

**Spec:** docs/superpowers/specs/2026-11-15-title-speed-and-silence-design.md

## Global Constraints

- `TITLE_GENERATION_MODEL = "gemini-3.5-flash-lite"`, `TITLE_GENERATION_TIMEOUT_SECONDS = 10`, no retries; plain `Config` constants (no env vars, no `.env` changes).
- `generate_title` keeps its contract: None on any failure, never raises.
- `max_silence_ms` is a `turn_timing` JSON key, left out when no call streamed a chunk.
- Gate per task: `make lint` + `make test`; TDD; commit by explicit paths.

## Review Focus

- A title call that times out: the save completes, the default title stays, `done` carries no title (Task 1 test).
- A batch-mode turn (no chunks): no `max_silence_ms` key, not 0 (Task 2 test).
- A call that fails after some chunks: its silence so far still counts (Task 2 test).
- Thought chunks (list-of-dict tokens) count as chunks, not as silence (Task 2 test).

---

### Task 1: Titles on Flash-Lite with a time limit

**Files:**
- Modify: `src/config.py` (TITLE_*), `src/agent/title.py`
- Test: `tests/unit/test_agent_title.py`

- [ ] Step 1: tests - `generate_title` builds its model with `chat_model(Config.TITLE_GENERATION_MODEL, temperature=..., timeout=Config.TITLE_GENERATION_TIMEOUT_SECONDS, max_retries=0)`; `Config.TITLE_GENERATION_MODEL == "gemini-3.5-flash-lite"`; a call that raises (timeout) returns None; the log line "Conversation title generated" carries `elapsed_ms` and `ok` (True on success, False on failure).
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; one info line per call (replaces the debug "Title generated"; the failure warning stays).
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `perf(chat): a new chat's title comes from Flash-Lite in under a second`.

### Task 2: The longest silence inside a model call

**Files:**
- Modify: `src/agent/cancellation.py` (`CancelOnToken`), `src/agent/turn_usage.py` (`ModelTiming.record`, `TurnClock.timing`), `src/agent/chat_node.py` (`_invoke_model`)
- Test: `tests/unit/test_turn_timing.py`, `tests/unit/test_cancellation.py`

**Interfaces:**
- Produces: `CancelOnToken.longest_gap_s(now: float) -> float | None` (None when no chunk arrived); `ModelTiming.record(started, response, silence_s: float | None = None)`; `ModelTiming.max_silence_ms: int | None`.

- [ ] Step 1: tests (patch the clock) - chunks at +2, +3, +9 s of a call started at 0 and ended at 10 → longest gap 6 s; a list-of-dict (thought) token counts as a chunk; no chunk → None; `ModelTiming` keeps the max over calls; `timing()` includes `max_silence_ms` only when set; a call that raised after chunks still records its gap.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; the handler notes `started` at construction and each chunk's time (an empty-string token counts too: the stream is alive).
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs - `docs/regular-review.md` (title `elapsed_ms` median/p90 and failures; `max_silence_ms` distribution), the reply-speed items in TODO.md (title done → removed, the title-after-`done` option parked, the watchdog item re-worded to "decide from `max_silence_ms` ~Nov 22"); commit `feat(agent): record the longest silence inside a turn's model calls`.
