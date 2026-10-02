# Grounding Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a turn that used web tools, a cheap verifier lists the specifics the
answer states that the turn's sources don't support, and a one-line note naming them
is appended to the answer.

**Architecture:** A new module, `src/agent/grounding_check.py`, collects the turn's
web tool results, calls `gemini-3.5-flash-lite` with structured output, filters and
caps the items, and formats the note. `ChatAgent` calls it in both the non-streaming
path (`chat_batch`) and the streaming path (`stream_chat_events`, on the `final`
event), so users and evals see the same text. The verifier's token usage travels in
`usage_info["grounding_usage"]` and is priced into the message cost.

**Tech Stack:** Python 3.14, LangChain `ChatGoogleGenerativeAI` with
`with_structured_output`, Pydantic, pytest, and the eval harness (`evals/run.py`).

**Spec:** [docs/superpowers/specs/2026-10-02-grounding-check-design.md](../specs/2026-10-02-grounding-check-design.md)

## Global Constraints

- Web tools: `research`, `web_search`, `fetch_url`, `browser` (ToolMessage `name`),
  excluding results with `status == "error"`.
- Skip the check when the answer is empty, when `stop_reason` is set, or when the turn
  has no web results.
- Config, with defaults: `GROUNDING_CHECK_ENABLED=true`,
  `GROUNDING_CHECK_MODEL=gemini-3.5-flash-lite`,
  `GROUNDING_CHECK_MAX_SOURCE_CHARS=60000`, `GROUNDING_CHECK_MAX_ITEMS=5`,
  `GROUNDING_CHECK_TIMEOUT_SECONDS=8`.
- Pricing entry `gemini-3.5-flash-lite`: input 0.30, cached_input 0.03, output 2.50
  ($ per 1M tokens). It goes into the pricing table only, never into
  `Config.MODELS`.
- Note templates, used verbatim:
  - cs: `_Neověřeno ve zdrojích, které jsem teď četl: {items}._`
  - en: `_Not confirmed in the sources I read for this answer: {items}._`

  Czech answers get cs; every other language, or no detected language, gets en. The
  note is appended after one blank line.
- Fail open: any verifier error or timeout leaves the answer unchanged.
- One info log per check with `flagged_count`, `kinds`, `source_chars`,
  `duration_ms`.
- Tests never call the live API. `tests/conftest.py` and `tests/e2e-server.py` set
  `GROUNDING_CHECK_ENABLED=false` (same pattern as `EMBEDDINGS_ENABLED`).
- Repo rules: mypy strict, functions < 50 lines, ruff format. Conventional Commits.
- Each task: run `make lint` plus `make test` (backend only; nothing here touches the
  frontend) before its commit. Run `make test-all` once in Task 5, before push and
  deploy. Push and deploy only after Task 5.
- The repo is public: no infrastructure details in tracked files.

## Review Focus

1. **The verifier returns an item that isn't in the answer** (a hallucinated or
   paraphrased item). The user expects the note to name only things the answer
   actually says. Items are kept only if their text appears in the answer
   (case-insensitive). Tested in Task 2.
2. **`fetch_url` returned multimodal list content** (a PDF or image page). Only the
   text parts count as sources and nothing crashes. Tested in Task 1.
3. **A single source longer than the cap.** It is truncated to the cap instead of
   being dropped, so the answer is still checked. Tested in Task 1.
4. **A short or unclassifiable answer** (`detect_response_language` returns None).
   The English template is used and no exception is raised. Tested in Task 1.
5. **The verifier returns `parsed=None`** (schema miss) **with valid usage.** No
   note, but the tokens are still recorded so cost is accurate. Tested in Task 2.

---

### Task 1: Source collection, note formatting, config

**Files:**
- Create: `src/agent/grounding_check.py`
- Modify: `src/config.py` (next to the other model settings, near `DELEGATE_MODEL`
  ~line 397), `.env.example`
- Modify: `tests/conftest.py` (after the `EMBEDDINGS_ENABLED` line, ~line 26),
  `tests/e2e-server.py` (after `LOG_LEVEL`, ~line 41)
- Test: `tests/unit/test_grounding_check.py`

**Interfaces:**
- Produces:
  - `WEB_TOOL_NAMES: frozenset[str]`
  - `collect_web_sources(result_messages: list[BaseMessage], max_chars: int) -> str`
  - `append_unverified_note(answer: str, items: list[str], language: str | None) -> str`
  - Config attributes `GROUNDING_CHECK_ENABLED: bool`, `GROUNDING_CHECK_MODEL: str`,
    `GROUNDING_CHECK_MAX_SOURCE_CHARS: int`, `GROUNDING_CHECK_MAX_ITEMS: int`,
    `GROUNDING_CHECK_TIMEOUT_SECONDS: float`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the post-answer grounding check (src/agent/grounding_check.py)."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.grounding_check import append_unverified_note, collect_web_sources


def _tool(name: str, content: object, status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=f"id-{name}", name=name, status=status)


class TestCollectWebSources:
    def test_only_successful_web_tool_results_count(self) -> None:
        messages = [
            HumanMessage(content="where to buy"),
            _tool("web_search", "Shop A sells it for 100 CZK"),
            _tool("garmin_connect", '{"hrv": 41}'),
            _tool("fetch_url", "Error: 404", status="error"),
            AIMessage(content="answer"),
        ]

        assert collect_web_sources(messages, 1000) == "Shop A sells it for 100 CZK"

    def test_no_web_results_gives_empty_string(self) -> None:
        assert collect_web_sources([_tool("execute_code", "42")], 1000) == ""

    def test_multimodal_content_contributes_its_text_parts(self) -> None:
        content = [
            {"type": "text", "text": "PDF page: open 9-17"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

        assert collect_web_sources([_tool("fetch_url", content)], 1000) == "PDF page: open 9-17"

    def test_cap_keeps_the_most_recent_results(self) -> None:
        messages = [_tool("web_search", "old " * 50), _tool("research", "newest result")]

        sources = collect_web_sources(messages, 20)

        # Filled newest-first (13 chars), the older result gets the remaining 7;
        # kept parts come back in original order
        assert sources == "old old" + "\n\n---\n\n" + "newest result"

    def test_single_result_longer_than_cap_is_truncated_not_dropped(self) -> None:
        sources = collect_web_sources([_tool("research", "x" * 500)], 100)

        assert sources == "x" * 100


class TestAppendUnverifiedNote:
    def test_no_items_leaves_answer_unchanged(self) -> None:
        assert append_unverified_note("Answer.", [], "cs") == "Answer."

    def test_czech_note(self) -> None:
        result = append_unverified_note("Odpověď.\n", ["VeloRama", "12 990 Kč"], "cs")

        assert result == "Odpověď.\n\n_Neověřeno ve zdrojích, které jsem teď četl: VeloRama, 12 990 Kč._"

    def test_english_note_for_other_and_unknown_languages(self) -> None:
        for language in ("en", "de", None):
            result = append_unverified_note("Answer.", ["VeloRama"], language)

            assert result == "Answer.\n\n_Not confirmed in the sources I read for this answer: VeloRama._"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.agent.grounding_check'`

- [ ] **Step 3: Add the config**

In `src/config.py`, right after the `DELEGATE_MODEL` line:

```python
    # Post-answer grounding check (docs/features/agent-tools.md): after a turn
    # that used web tools, a cheap model lists answer specifics the turn's
    # sources don't support, and a one-line note names them.
    GROUNDING_CHECK_ENABLED: bool = os.getenv("GROUNDING_CHECK_ENABLED", "true").lower() == "true"
    GROUNDING_CHECK_MODEL: str = os.getenv("GROUNDING_CHECK_MODEL") or "gemini-3.5-flash-lite"
    GROUNDING_CHECK_MAX_SOURCE_CHARS: int = int(
        os.getenv("GROUNDING_CHECK_MAX_SOURCE_CHARS", "60000")
    )
    GROUNDING_CHECK_MAX_ITEMS: int = int(os.getenv("GROUNDING_CHECK_MAX_ITEMS", "5"))
    GROUNDING_CHECK_TIMEOUT_SECONDS: float = float(
        os.getenv("GROUNDING_CHECK_TIMEOUT_SECONDS", "8")
    )
```

Match how nearby boolean env vars are parsed (look at how `EMBEDDINGS_ENABLED` is
read and copy that idiom exactly if it differs).

In `.env.example`, next to the other model settings:

```bash
# Post-answer grounding check: after a web-tool turn, a cheap model flags answer
# specifics (shops, prices, hours...) the turn's sources don't support, and a
# one-line note names them. ~$0.004 per web turn.
GROUNDING_CHECK_ENABLED=true
GROUNDING_CHECK_MODEL=gemini-3.5-flash-lite
# Source text sent to the checker, most recent results first (default: 60000)
GROUNDING_CHECK_MAX_SOURCE_CHARS=60000
GROUNDING_CHECK_MAX_ITEMS=5
GROUNDING_CHECK_TIMEOUT_SECONDS=8
```

In `tests/conftest.py` after the `EMBEDDINGS_ENABLED` line, and in
`tests/e2e-server.py` after the `LOG_LEVEL` line:

```python
# The post-answer grounding check must never call the live API from tests;
# its own tests opt back in via monkeypatch on Config.
os.environ["GROUNDING_CHECK_ENABLED"] = "false"
```

- [ ] **Step 4: Write the module (source collection and note only)**

`src/agent/grounding_check.py`:

```python
"""Post-answer grounding check.

The Sep 2026 conversation sweep's most common correction was stale or invented
specifics, and prompt rules (GROUNDING_DIRECTIVE, the unverified-specifics rule)
were measured to have no effect. So after a turn that used web tools, a cheap
model compares the answer with what the turn actually read, and a one-line note
names the specifics the sources don't support. See
docs/superpowers/specs/2026-10-02-grounding-check-design.md.
"""

from langchain_core.messages import BaseMessage, ToolMessage

from src.agent.content import extract_text_content

WEB_TOOL_NAMES = frozenset({"research", "web_search", "fetch_url", "browser"})

_SOURCE_SEPARATOR = "\n\n---\n\n"

_NOTE_TEMPLATES = {
    "cs": "_Neověřeno ve zdrojích, které jsem teď četl: {items}._",
    "en": "_Not confirmed in the sources I read for this answer: {items}._",
}


def collect_web_sources(result_messages: list[BaseMessage], max_chars: int) -> str:
    """Text of the turn's successful web tool results, newest first, capped.

    Later results usually matter most (a research round after a search), so the
    cap is filled from the end of the turn backwards; the kept parts are then
    returned in their original order.
    """
    parts: list[str] = []
    total = 0
    for msg in reversed(result_messages):
        if not isinstance(msg, ToolMessage) or msg.name not in WEB_TOOL_NAMES:
            continue
        if msg.status == "error":
            continue
        text = extract_text_content(msg.content).strip()
        remaining = max_chars - total
        if not text or remaining <= 0:
            continue
        parts.append(text[:remaining])
        total += len(parts[-1])
    return _SOURCE_SEPARATOR.join(reversed(parts))


def append_unverified_note(answer: str, items: list[str], language: str | None) -> str:
    """The answer plus a one-line note naming unverified items (none: unchanged)."""
    if not items:
        return answer
    template = _NOTE_TEMPLATES.get(language or "", _NOTE_TEMPLATES["en"])
    return f"{answer.rstrip()}\n\n{template.format(items=', '.join(items))}"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Lint, backend suite, commit**

```bash
make lint > /tmp/gc-lint.log 2>&1; echo "lint exit=$?"
make test > /tmp/gc-test.log 2>&1; echo "test exit=$?"
```

Both must print `exit=0`. Branch on the exit code, never on a grep through a pipe.

```bash
git add src/agent/grounding_check.py src/config.py .env.example tests/conftest.py tests/e2e-server.py tests/unit/test_grounding_check.py
git commit -m "feat(agent): grounding check - web source collection and unverified note"
```

---

### Task 2: The verifier call

**Files:**
- Create: `src/agent/prompt_texts/grounding.py`
- Modify: `src/agent/grounding_check.py`
- Modify: `src/config.py` (`MODEL_PRICING`, next to the `gemini-3.8-flash` entry
  ~line 142)
- Test: `tests/unit/test_grounding_check.py`

**Interfaces:**
- Consumes: `collect_web_sources`, `Config.GROUNDING_CHECK_*`
- Produces:
  - `class UnverifiedItem(BaseModel)`: `text: str`,
    `kind: Literal["shop","place","price","hours","date","figure","other"]`
  - `class GroundingVerdict(BaseModel)`: `unsupported: list[UnverifiedItem]`
  - `@dataclass class GroundingResult`: `items: list[str]`, `kinds: list[str]`,
    `usage: dict[str, Any] | None`
  - `find_unverified(answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None) -> GroundingResult`
  - `usage` shape: `{"model": str, "input_tokens": int, "output_tokens": int, "cached_input_tokens": int}`

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_grounding_check.py`)

```python
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent import grounding_check
from src.agent.grounding_check import GroundingVerdict, UnverifiedItem, find_unverified
from src.config import Config


def _verdict(*items: tuple[str, str]) -> GroundingVerdict:
    return GroundingVerdict(unsupported=[UnverifiedItem(text=t, kind=k) for t, k in items])  # type: ignore[arg-type]


@pytest.fixture
def fake_verifier(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the LLM call; tests set .return_value or .side_effect."""
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(
        return_value=(_verdict(), {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0})
    )
    monkeypatch.setattr(grounding_check, "_run_verifier", fake)
    return fake


_WEB_TURN = [_tool("research", "Kolo Brompton C Line stojí 32 990 Kč u Bike Prague.")]
_ANSWER = "Brompton koupíte u Bike Prague (32 990 Kč) nebo ve VeloRama za 29 990 Kč."


class TestFindUnverified:
    def test_flags_items_the_verifier_returns(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            _verdict(("VeloRama", "shop"), ("29 990 Kč", "price")),
            {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0},
        )

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == ["VeloRama", "29 990 Kč"]
        assert result.kinds == ["shop", "price"]
        assert result.usage == {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}

    def test_drops_items_not_in_the_answer(self, fake_verifier: MagicMock) -> None:
        # The verifier paraphrased or invented an item: the note must only
        # ever name things the answer actually says
        fake_verifier.return_value = (_verdict(("Velo Rama s.r.o.", "shop"), ("velorama", "shop")), None)

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["velorama"]

    def test_dedupes_and_caps_items(self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_ITEMS", 1)
        fake_verifier.return_value = (_verdict(("VeloRama", "shop"), ("VeloRama", "shop"), ("29 990 Kč", "price")), None)

        assert find_unverified(_ANSWER, _WEB_TURN).items == ["VeloRama"]

    @pytest.mark.parametrize(
        ("answer", "messages", "stop_reason"),
        [
            ("", _WEB_TURN, None),
            (_ANSWER, _WEB_TURN, "user"),
            (_ANSWER, [_tool("execute_code", "42")], None),
        ],
    )
    def test_skips_without_calling_the_verifier(
        self, fake_verifier: MagicMock, answer: str, messages: list[Any], stop_reason: str | None
    ) -> None:
        result = find_unverified(answer, messages, stop_reason)

        assert result.items == [] and result.usage is None
        fake_verifier.assert_not_called()

    def test_disabled_skips(self, fake_verifier: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", False)

        assert find_unverified(_ANSWER, _WEB_TURN).items == []
        fake_verifier.assert_not_called()

    def test_verifier_error_fails_open(self, fake_verifier: MagicMock) -> None:
        fake_verifier.side_effect = TimeoutError("deadline exceeded")

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == [] and result.usage is None

    def test_schema_miss_keeps_usage(self, fake_verifier: MagicMock) -> None:
        usage = {"model": "m", "input_tokens": 900, "output_tokens": 5, "cached_input_tokens": 0}
        fake_verifier.return_value = (None, usage)

        result = find_unverified(_ANSWER, _WEB_TURN)

        assert result.items == []
        assert result.usage == usage


class TestRunVerifier:
    def test_builds_structured_call_and_reads_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = MagicMock(usage_metadata={"input_tokens": 120, "output_tokens": 8, "input_token_details": {"cache_read": 20}})
        structured = MagicMock()
        structured.invoke.return_value = {"raw": raw, "parsed": _verdict(("VeloRama", "shop")), "parsing_error": None}
        model = MagicMock()
        model.with_structured_output.return_value = structured
        llm_cls = MagicMock(return_value=model)
        monkeypatch.setattr(grounding_check, "ChatGoogleGenerativeAI", llm_cls)

        verdict, usage = grounding_check._run_verifier("the answer", "the sources")

        kwargs = llm_cls.call_args.kwargs
        assert kwargs["model"] == Config.GROUNDING_CHECK_MODEL
        assert kwargs["temperature"] == 0
        assert kwargs["timeout"] == Config.GROUNDING_CHECK_TIMEOUT_SECONDS
        assert kwargs["max_retries"] == 0
        model.with_structured_output.assert_called_once_with(GroundingVerdict, include_raw=True)
        prompt = structured.invoke.call_args.args[0]
        assert "the answer" in prompt and "the sources" in prompt
        assert verdict is not None and verdict.unsupported[0].text == "VeloRama"
        assert usage == {
            "model": Config.GROUNDING_CHECK_MODEL,
            "input_tokens": 120,
            "output_tokens": 8,
            "cached_input_tokens": 20,
        }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v`
Expected: FAIL with `ImportError: cannot import name 'GroundingVerdict'`

- [ ] **Step 3: Add the prompt text**

`src/agent/prompt_texts/grounding.py`:

```python
"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Precision first: a false flag puts a wrong "not confirmed" note under a
# correct answer, which is worse than missing a real one. Formatted with
# str.format - keep literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the web SOURCES it read this turn.

List the concrete, checkable specifics in the ANSWER that the SOURCES do not contain, or that the SOURCES contradict:
- names of shops, dealers, places, venues, restaurants, products or people
- prices, opening hours, dates, schedules and other figures

Do NOT list:
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- a specific the SOURCES state in other words, other formatting or another language

When unsure, do not list it. Copy each item exactly as it is written in the ANSWER.
Return an empty list when everything is supported.

SOURCES:
{sources}

ANSWER:
{answer}
"""
```

- [ ] **Step 4: Add the verifier to `src/agent/grounding_check.py`**

Add the imports at the top (keep the existing ones):

```python
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)
```

Add after `_NOTE_TEMPLATES`:

```python
class UnverifiedItem(BaseModel):
    """One specific in the answer that the sources don't support."""

    text: str = Field(..., description="The specific exactly as written in the answer")
    kind: Literal["shop", "place", "price", "hours", "date", "figure", "other"] = "other"


class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    unsupported: list[UnverifiedItem] = Field(default_factory=list)


@dataclass
class GroundingResult:
    """Items to name in the note, their kinds (logged only), and verifier usage."""

    items: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None


def _run_verifier(answer: str, sources: str) -> tuple[GroundingVerdict | None, dict[str, Any] | None]:
    """One structured call to the checker model. Raises on API errors/timeouts."""
    model = ChatGoogleGenerativeAI(
        model=Config.GROUNDING_CHECK_MODEL,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=0,
        timeout=Config.GROUNDING_CHECK_TIMEOUT_SECONDS,
        max_retries=0,
    )
    structured = model.with_structured_output(GroundingVerdict, include_raw=True)
    out = structured.invoke(GROUNDING_CHECK_PROMPT.format(sources=sources, answer=answer))
    metadata = getattr(out["raw"], "usage_metadata", None) or {}
    usage = {
        "model": Config.GROUNDING_CHECK_MODEL,
        "input_tokens": int(metadata.get("input_tokens", 0)),
        "output_tokens": int(metadata.get("output_tokens", 0)),
        "cached_input_tokens": int((metadata.get("input_token_details") or {}).get("cache_read", 0)),
    }
    parsed = out.get("parsed")
    return (parsed if isinstance(parsed, GroundingVerdict) else None), usage


def _keep_items(verdict: GroundingVerdict | None, answer: str) -> tuple[list[str], list[str]]:
    """Items that literally appear in the answer, de-duplicated, capped."""
    if verdict is None:
        return [], []
    haystack = answer.casefold()
    items: list[str] = []
    kinds: list[str] = []
    for item in verdict.unsupported:
        text = item.text.strip()
        if not text or text.casefold() not in haystack or text in items:
            continue
        items.append(text)
        kinds.append(item.kind)
        if len(items) >= Config.GROUNDING_CHECK_MAX_ITEMS:
            break
    return items, kinds


def find_unverified(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> GroundingResult:
    """Specifics in a web-tool turn's answer that its sources don't support.

    Fails open: any verifier error returns an empty result, so the answer goes
    out unchanged.
    """
    if not Config.GROUNDING_CHECK_ENABLED or stop_reason or not answer.strip():
        return GroundingResult()
    sources = collect_web_sources(result_messages, Config.GROUNDING_CHECK_MAX_SOURCE_CHARS)
    if not sources:
        return GroundingResult()
    started = time.monotonic()
    try:
        verdict, usage = _run_verifier(answer, sources)
    except Exception:
        logger.warning("Grounding check failed", exc_info=True, extra={"source_chars": len(sources)})
        return GroundingResult()
    items, kinds = _keep_items(verdict, answer)
    logger.info(
        "Grounding check",
        extra={
            "flagged_count": len(items),
            "kinds": kinds,
            "source_chars": len(sources),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "parsed": verdict is not None,
        },
    )
    return GroundingResult(items=items, kinds=kinds, usage=usage)
```

`test_drops_items_not_in_the_answer`: `"velorama"` matches case-insensitively and is
kept as the verifier wrote it. That is intended; the de-dup check compares exact
text.

- [ ] **Step 5: Add the pricing entry**

In `src/config.py` `MODEL_PRICING`, after the `gemini-3.8-flash` entry:

```python
        # Grounding check model (GROUNDING_CHECK_MODEL) - priced only, never
        # user-selectable, so not in MODELS
        "gemini-3.5-flash-lite": {
            "input": 0.30,  # $0.30 per million input tokens
            "cached_input": 0.03,
            "output": 2.50,  # $2.50 per million output tokens
        },
```

If a test asserts that every `MODEL_PRICING` key is in `MODELS`, run
`grep -rn "MODEL_PRICING" tests/` and add an explicit exemption for
`Config.GROUNDING_CHECK_MODEL` there, with a comment.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_check.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 7: Lint, backend suite, commit**

```bash
make lint > /tmp/gc-lint.log 2>&1; echo "lint exit=$?"
make test > /tmp/gc-test.log 2>&1; echo "test exit=$?"
git add src/agent/grounding_check.py src/agent/prompt_texts/grounding.py src/config.py tests/unit/test_grounding_check.py
git commit -m "feat(agent): grounding check verifier on gemini-3.5-flash-lite"
```

---

### Task 3: Hook into both agent paths

**Files:**
- Modify: `src/agent/grounding_check.py` (add `apply_grounding`)
- Modify: `src/agent/agent.py`:
  - `chat_batch`, after `usage_info = batch_usage_info(...)` (~line 323);
  - `stream_chat_events`, the last line `yield from processor.finish(...)` (~line 505).
- Test: `tests/unit/test_grounding_hooks.py`

**Interfaces:**
- Consumes: `find_unverified`, `append_unverified_note`, `GroundingResult`,
  `detect_response_language` (`src/agent/content.py`)
- Produces:
  `apply_grounding(answer: str, result_messages: list[BaseMessage], usage_info: dict[str, Any], stop_reason: str | None = None) -> str`.
  It mutates `usage_info` by adding `"grounding_usage"` when the verifier ran.

`agent.py` is already 505 lines (over the 500 convention). Keep the additions to
these few lines and put all logic in `grounding_check.py`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_grounding_hooks.py`:

```python
"""ChatAgent applies the grounding check in both the batch and stream paths."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.agent import grounding_check
from src.agent.grounding_check import GroundingResult, apply_grounding
from src.config import Config

_USAGE = {"model": "m", "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}


@pytest.fixture
def flag(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(return_value=GroundingResult(items=["VeloRama"], kinds=["shop"], usage=_USAGE))
    monkeypatch.setattr(grounding_check, "find_unverified", fake)
    return fake


class TestApplyGrounding:
    def test_appends_note_and_records_usage(self, flag: MagicMock) -> None:
        usage_info: dict[str, Any] = {"input_tokens": 1}

        text = apply_grounding("Buy it at VeloRama, it is a good shop.", [], usage_info)

        assert text.endswith("_Not confirmed in the sources I read for this answer: VeloRama._")
        assert usage_info["grounding_usage"] == _USAGE

    def test_nothing_flagged_leaves_text_and_usage(self, flag: MagicMock) -> None:
        flag.return_value = GroundingResult()
        usage_info: dict[str, Any] = {}

        assert apply_grounding("All supported.", [], usage_info) == "All supported."
        assert "grounding_usage" not in usage_info

    def test_passes_stop_reason_through(self, flag: MagicMock) -> None:
        apply_grounding("x", [], {}, stop_reason="user")

        assert flag.call_args.args[2] == "user"


class TestAgentHooks:
    @staticmethod
    def _agent() -> Any:
        from src.agent.agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent.graph = MagicMock()
        agent._build_messages = MagicMock(return_value=[])  # type: ignore[method-assign]
        return agent

    def test_batch_answer_carries_the_note(self, flag: MagicMock) -> None:
        agent = self._agent()
        agent.graph.invoke.return_value = {
            "messages": [
                ToolMessage(content="Bike Prague", tool_call_id="1", name="research"),
                AIMessage(content="Buy it at VeloRama, it is a good shop."),
            ]
        }

        response, _tools, usage_info, _msgs = agent.chat_batch(text="where?")

        assert response.endswith("VeloRama._")
        assert usage_info["grounding_usage"] == _USAGE

    def test_stream_final_carries_the_note(self, flag: MagicMock) -> None:
        agent = self._agent()
        events = [
            (ToolMessage(content="Bike Prague", tool_call_id="1", name="research"), {"langgraph_node": "tools"}),
            (AIMessageChunk(content="Buy it at VeloRama, it is a good shop."), {"langgraph_node": "chat"}),
        ]
        agent.graph.stream.return_value = iter(("messages", e) for e in events)

        final = [e for e in agent.stream_chat_events(text="where?") if e["type"] == "final"][0]

        assert final["content"].endswith("VeloRama._")
        assert final["usage_info"]["grounding_usage"] == _USAGE
```

If `chat_batch` needs more arguments or setup than `text=` (check its signature at
`src/agent/agent.py:235` and the batch tests in `tests/unit/test_agent*.py`), mirror
the setup an existing batch test uses rather than inventing new mocks.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_hooks.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_grounding'`

- [ ] **Step 3: Add `apply_grounding` to `src/agent/grounding_check.py`**

Add `from src.agent.content import detect_response_language` to the content import,
then:

```python
def apply_grounding(
    answer: str,
    result_messages: list[BaseMessage],
    usage_info: dict[str, Any],
    stop_reason: str | None = None,
) -> str:
    """The answer with an unverified-specifics note if needed; records verifier usage.

    Called by ChatAgent for both batch and streamed turns so evals see exactly
    what users see. `find_unverified` is looked up on the module at call time,
    which keeps it patchable in tests.
    """
    result = find_unverified(answer, result_messages, stop_reason)
    if result.usage:
        usage_info["grounding_usage"] = result.usage
    return append_unverified_note(answer, result.items, detect_response_language(answer))
```

- [ ] **Step 4: Hook `chat_batch`**

In `src/agent/agent.py`, add the import next to the other `src.agent` imports:

```python
from src.agent.grounding_check import apply_grounding
```

In `chat_batch`, right after `usage_info = batch_usage_info(result_messages, turn_duration_ms)`:

```python
        response_text = apply_grounding(response_text, result_messages, usage_info)
```

Because of the top-level `from ... import apply_grounding`, the tests patch
`grounding_check.find_unverified`, not `apply_grounding`, so the patch still applies.

- [ ] **Step 5: Hook `stream_chat_events`**

Replace the last line `yield from processor.finish(turn_started, stop_reason=stop_reason)` with:

```python
        for event in processor.finish(turn_started, stop_reason=stop_reason):
            if event.get("type") == "final":
                event["content"] = apply_grounding(
                    event["content"],
                    event["result_messages"],
                    event["usage_info"],
                    event.get("stop_reason"),
                )
            yield event
```

- [ ] **Step 6: Run the hook tests and the existing agent tests**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_hooks.py tests/unit/test_agent_streaming.py tests/unit/test_agent_setup.py -v`
Expected: PASS. The existing streaming tests stay green because conftest disables the
check.

- [ ] **Step 7: Lint, backend suite, commit**

```bash
make lint > /tmp/gc-lint.log 2>&1; echo "lint exit=$?"
make test > /tmp/gc-test.log 2>&1; echo "test exit=$?"
git add src/agent/grounding_check.py src/agent/agent.py tests/unit/test_grounding_hooks.py
git commit -m "feat(agent): append the grounding note in batch and streamed turns"
```

---

### Task 4: Price the verifier into message cost and eval cost

**Files:**
- Modify: `src/api/utils.py`: add `calculate_grounding_cost`, and use it in
  `calculate_and_save_message_cost` (~line 315).
- Modify: `evals/run.py`, `_turn_cost` (~line 232).
- Test: `tests/unit/test_grounding_cost.py`

**Interfaces:**
- Consumes: `usage_info["grounding_usage"]` (shape from Task 2)
- Produces: `calculate_grounding_cost(usage_info: dict[str, Any]) -> float`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_grounding_cost.py`:

```python
"""The grounding verifier's tokens are priced at its own model's rates."""

from unittest.mock import patch

import pytest

from src.api.utils import calculate_and_save_message_cost, calculate_grounding_cost
from src.utils.costs import calculate_token_cost

_USAGE = {"model": "gemini-3.5-flash-lite", "input_tokens": 10_000, "output_tokens": 50, "cached_input_tokens": 0}


def test_prices_at_the_verifier_model() -> None:
    expected = calculate_token_cost("gemini-3.5-flash-lite", 10_000, 50)

    assert calculate_grounding_cost({"grounding_usage": _USAGE}) == pytest.approx(expected)
    assert expected == pytest.approx(10_000 * 0.30 / 1e6 + 50 * 2.50 / 1e6)


def test_no_grounding_usage_costs_nothing() -> None:
    assert calculate_grounding_cost({}) == 0.0
    assert calculate_grounding_cost({"grounding_usage": "garbage"}) == 0.0


def test_message_cost_includes_grounding() -> None:
    with patch("src.api.utils.db") as db:
        calculate_and_save_message_cost(
            "msg", "conv", "user", "gemini-3.8-flash",
            {"input_tokens": 0, "output_tokens": 0, "grounding_usage": _USAGE},
            [], 10,
        )

    saved_cost = db.save_message_cost.call_args.args[6]
    assert saved_cost == pytest.approx(calculate_grounding_cost({"grounding_usage": _USAGE}))
```

Check the positional index of `cost_usd` in the `db.save_message_cost(...)` call in
`src/api/utils.py`. It is the 7th argument (index 6) as of Oct 2 2026; adjust if the
call has changed.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_cost.py -v`
Expected: FAIL with `ImportError: cannot import name 'calculate_grounding_cost'`

- [ ] **Step 3: Implement**

In `src/api/utils.py`, after `calculate_delegate_cost_from_tool_results`:

```python
def calculate_grounding_cost(usage_info: dict[str, Any]) -> float:
    """Cost of the post-answer grounding check, priced at its own model.

    The verifier's usage rides in usage_info["grounding_usage"]
    (src/agent/grounding_check.py) - a different, cheaper model than the turn's.
    """
    from src.utils.costs import calculate_token_cost

    usage = usage_info.get("grounding_usage")
    if not isinstance(usage, dict):
        return 0.0
    return calculate_token_cost(
        str(usage.get("model", "")),
        int(usage.get("input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
    )
```

In `calculate_and_save_message_cost`, change the `tool_llm_cost=delegate_cost` argument
of `calculate_total_cost(...)` to:

```python
        tool_llm_cost=delegate_cost + calculate_grounding_cost(usage_info),
```

In `evals/run.py` `_turn_cost`, add `calculate_grounding_cost` to the
`from src.api.utils import (...)` list and change its `tool_llm_cost=` to:

```python
        tool_llm_cost=calculate_delegate_cost_from_tool_results(tool_results)
        + calculate_grounding_cost(usage),
```

Add one sentence to the `_turn_cost` docstring: "...and the post-answer grounding
check (priced at its own model)."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_grounding_cost.py tests/unit/test_eval_harness.py -v`
Expected: PASS

- [ ] **Step 5: Lint, backend suite, commit**

```bash
make lint > /tmp/gc-lint.log 2>&1; echo "lint exit=$?"
make test > /tmp/gc-test.log 2>&1; echo "test exit=$?"
git add src/api/utils.py evals/run.py tests/unit/test_grounding_cost.py
git commit -m "feat(costs): price the grounding check into message and eval cost"
```

---

### Task 5: Evals, docs, full gate, ship

**Files:**
- Create: `evals/cases/cz_grounded_no_note.yaml`
- Modify: `evals/cases/skill_product_where_to_buy.yaml` (the comment only, after
  measuring)
- Modify: `docs/testing/evals.md`, the feature doc that describes
  `GROUNDING_DIRECTIVE` (find it with `grep -rln GROUNDING_DIRECTIVE docs/`), `TODO.md`
- Docs via the `docs-updater` agent

- [ ] **Step 1: Add the precision case**

`evals/cases/cz_grounded_no_note.yaml`:

```yaml
id: cz_grounded_no_note
description: Grounding-check precision - a fully sourced answer gets no "not confirmed" note
user: "jaky je dnes kurz eura podle CNB?"
expect:
  rubric: >
    Gives today's (or the latest published) Czech National Bank EUR/CZK rate,
    taken from a source it read this turn. It FAILS if the answer ends with a
    "Neověřeno ve zdrojích..." or "Not confirmed in the sources..." note: a
    single rate read from the CNB page is fully supported, so such a note is a
    false flag.
  required_tools: [research, web_search, fetch_url]
  forbidden_tools: [delegate_task]
```

- [ ] **Step 2: Measure the target and the precision case** (live API; report cost)

```bash
for i in 1 2 3 4 5; do .venv/bin/python evals/run.py --only 'skill_product_where_to_buy,cz_grounded_no_note' --workers 2 > /tmp/gc-eval$i.log 2>&1; echo "run$i exit=$?"; grep -E "^(PASS|FAIL)|Cost:" /tmp/gc-eval$i.log; done
grep -h "Grounding check" /tmp/gc-eval*.log | head -20
```

Gate:
- `skill_product_where_to_buy` passes at least 4/5;
- `cz_grounded_no_note` passes at least 4/5;
- the "Grounding check" log lines show `parsed: true` and `duration_ms` mostly under
  3000.

If precision fails (spurious notes), first try `GROUNDING_CHECK_MODEL=gemini-3.8-flash`
for one 5-run round to tell model weakness from a prompt problem. Then tighten the
prompt. Report both results before changing the default.

- [ ] **Step 3: Full suite and spurious-note spot-check**

```bash
caffeinate -i .venv/bin/python evals/run.py > /tmp/gc-full.log 2>&1; echo "eval exit=$?"
grep -E "^FAIL|passed|Cost:" /tmp/gc-full.log
grep -E "Grounding check" /tmp/gc-full.log | grep -v '"flagged_count": 0' | head
```

Gate: the pass rate is unchanged from today's 58/61. The known failures are
`cz_batched_lookups` and the 1-in-6 noise of `cz_tool_output_recall`;
`skill_product_where_to_buy` should now pass. Rerun any new failure 5× before
blaming the change. For every non-zero `flagged_count`, check that the flagged case
(`cz_local_lookup`, `web_lookup_cited`, `skill_trip_*`, `alpine_trip_advice`) really
contained an unsupported specific. Report the full-suite cost and the grounding
share of it.

- [ ] **Step 4: Update the probe comment and TODO**

In `evals/cases/skill_product_where_to_buy.yaml`, replace the "Known-failing honesty
probe" comment with the measured result. For example: "Honesty probe: failed 1/5
until the post-answer grounding check (Oct 2026); now N/5."

In `TODO.md`, replace the **Stale or invented facts** sub-bullet with what remains:
answers from memory with no lookup (news, film plots) are not covered by the check.
Add the follow-up: review a week of `Grounding check` telemetry (flag rate, kinds,
`parsed`), then tune the model, cap or prompt.

- [ ] **Step 5: Docs**

Run the `docs-updater` agent with this summary: the new grounding check (module,
trigger, note, config, cost, fail-open, telemetry), the new eval case, and the
pricing entry. It updates the feature doc that covers `GROUNDING_DIRECTIVE`,
`docs/testing/evals.md` (the Sweep cases list gets `cz_grounded_no_note` and the
`skill_product_where_to_buy` result), and the docs index if a page is added. No
infrastructure details.

- [ ] **Step 6: Full gate**

```bash
make lint > /tmp/gc-lint.log 2>&1; echo "lint exit=$?"
caffeinate -i make test-all > /tmp/gc-all.log 2>&1; echo "test-all exit=$?"
```

Both must print `exit=0`.

- [ ] **Step 7: Commit, push, deploy, watch CI**

```bash
git add evals/cases/cz_grounded_no_note.yaml evals/cases/skill_product_where_to_buy.yaml TODO.md docs/
git commit -m "test(evals): grounding check precision case; docs and TODO"
git push origin main
```

Deploy per the private deploy workflow, never twice in quick succession. Watch the
Tests workflow, and if a run fails, fix the root cause and prune it. After deploy,
confirm one real web turn logs a `Grounding check` line.
