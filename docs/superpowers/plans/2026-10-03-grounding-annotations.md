# Grounding Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline `_(neověřeno)_` grounding markers with per-claim annotations (verdict, reason, source passage) stored next to clean message text, rendered as quiet underlines, source numbers, cards, a footer summary and a claims list.

**Architecture:** One numbered page list per turn feeds both the source popup and the Lite verifier, which now judges every specific claim. Validated claims ride `usage_info["grounding"]` into `save_message_to_db`, are stored in two new JSON columns, sent on every message read, and summarized into `MSG_CONTEXT`. The client anchors each claim in the rendered markdown by quote + prefix and adds the footer, card and sheet. Two migrations add the columns and convert the markers written since Oct 2.

**Tech Stack:** Python 3.14, Flask/APIFlask + Pydantic, LangChain Gemini (`with_structured_output`), SQLite + yoyo, vanilla TypeScript + Vite + Zustand, Vitest, Playwright.

**Spec:** [docs/superpowers/specs/2026-10-03-grounding-annotations-design.md](../specs/2026-10-03-grounding-annotations-design.md)

## Global Constraints

- Work on branch `feat/grounding-annotations` in the main checkout (`git switch -c feat/grounding-annotations`); merge to main only when `make lint` and `make test-all` are green.
- `messages.content` never contains grounding text; the answer text the verifier sees is the text that is saved and streamed.
- Fail open: any verifier error means no annotations, unchanged answer, no footer.
- A card never shows a `source_quote` that is not a literal (whitespace-normalised, case-insensitive) substring of the cited page's text.
- `source` is 1-based and indexes the message's `sources` list (the sources popup numbers 1..n in the same order).
- Verdicts are exactly `supported`, `partial`, `not_found`, `contradicted`; annotation `type` is `"claim"`.
- Grounding summary: `{"checked": true, "source_count": N}`; converted messages `{"checked": true, "legacy": true}`.
- Config: `GROUNDING_CHECK_MAX_CLAIMS` (default 20) replaces `GROUNDING_CHECK_MAX_ITEMS`; `GROUNDING_CHECK_MAX_QUOTE_CHARS` (default 120) replaces `GROUNDING_CHECK_MAX_ITEM_CHARS`; `GROUNDING_CHECK_MAX_FALSE_CLAIMS` removed; new `GROUNDING_CHECK_MAX_REASON_CHARS` (160), `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS` (240), `GROUNDING_CONTEXT_MAX_CHARS` (400). Every env var: `src/config.py` default, `.env.example`, `docs/features/` page.
- UI look "A1": dotted 1px underline, offset 4px, amber ~45% opacity (`contradicted`: soft red); source numbers grey, no background; card colours as tokens in `web/src/styles/variables.css` for both themes.
- UI strings in Czech when `message.language === 'cs'`, otherwise English.
- New SSE event `grounding_started` joins `_JOURNALED_EVENT_TYPES`.
- Hard rules from `CLAUDE.md`: check exit codes directly (redirect to a log, branch on `$?`), E2E runs the last `make build`, test desktop and mobile (768px breakpoint), Conventional Commits, no infra hostnames in tracked files.
- Never hand-edit `web/src/types/generated-api.ts` or `static/openapi.json`; run `make openapi && make types`.

## Review Focus

1. **Quotes whose rendered text differs from the markdown** (`**SPZ Služby**`, `[spzsluzby.cz](https://…)`, `` `registr-vozidel.cz` ``): the claim must still be underlined. Test in Task 8 (`anchors a quote written with markdown emphasis and links`).
2. **The same quote twice in one answer** ("800 Kč" under both agencies): the underline lands on the occurrence whose prefix matches. Test in Task 2 (prefix comes from the answer) and Task 8 (`picks the occurrence that matches the prefix`).
3. **A verifier reply that cites a page out of range, cites page 0, or paraphrases the passage:** the claim is downgraded to `not_found` with no passage, never a crash or an invented quote. Test in Task 2 (`downgrades_out_of_range_source` and `downgrades_paraphrased_passage`).
4. **A converted message whose quote can't be found in the rendered text:** footer still says "N bez zdroje", the claims list still lists it, no underline, no error. Test in Task 9 (`legacy footer counts claims that were not anchored`).
5. **The reply finishing while the user is in another conversation, or a reload during the check:** returning to the conversation renders the annotations from server data; a resumed stream shows "checking" and then the counts. Tests in Task 5 (journal replays `grounding_started`) and Task 9 (`addMessageToUI decorates server messages`).

---

### Task 1: One numbered page list per turn

**Files:**
- Create: `src/agent/source_pages.py`
- Modify: `src/agent/content.py:237-338` (move `_MAX_READ_SOURCES`, `_MAX_SEARCH_SOURCES`, `_json_object`, `_title_from_url`, `_search_results` and the body of `extract_read_sources` into the new module; `extract_read_sources` stays in `content.py` as a thin mapper)
- Test: `tests/unit/test_source_pages.py`

**Interfaces:**
- Produces: `SourcePage(title: str, url: str, text: str)` (frozen dataclass); `turn_pages(messages: list[BaseMessage]) -> list[SourcePage]`; `uncited_web_text(messages: list[BaseMessage]) -> str` (search snippets and web tool text that is not one of the numbered pages); `extract_read_sources(messages) -> list[dict[str, str]]` unchanged signature, now `[{"title": p.title, "url": p.url} for p in turn_pages(messages)]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the turn's numbered page list (src/agent/source_pages.py)."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.content import extract_read_sources
from src.agent.source_pages import SourcePage, turn_pages, uncited_web_text


def _call(name: str, call_id: str, args: dict[str, object] | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def _result(name: str, call_id: str, content: object) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name)


def _research(*pages: tuple[str, str, str | None]) -> str:
    sources = []
    for title, url, text in pages:
        source: dict[str, object] = {"title": title, "url": url}
        if text is not None:
            source["content"] = text
        sources.append(source)
    return json.dumps({"sources": sources})


def test_research_pages_carry_their_text_in_chip_order() -> None:
    messages = [
        _call("research", "r1"),
        _result(
            "research",
            "r1",
            _research(
                ("SPZ Služby", "https://spzsluzby.cz", "Vyřízení do 24 hodin."),
                ("Failed", "https://failed.cz", None),  # not fetched: not read
                ("Pomocnice", "https://pomocnice.cz/x", "Cena 1 590 Kč."),
            ),
        ),
    ]

    assert turn_pages(messages) == [
        SourcePage("SPZ Služby", "https://spzsluzby.cz", "Vyřízení do 24 hodin."),
        SourcePage("Pomocnice", "https://pomocnice.cz/x", "Cena 1 590 Kč."),
    ]
    assert extract_read_sources(messages) == [
        {"title": "SPZ Služby", "url": "https://spzsluzby.cz"},
        {"title": "Pomocnice", "url": "https://pomocnice.cz/x"},
    ]


def test_fetch_url_page_text_is_the_tool_output() -> None:
    messages = [
        _call("fetch_url", "f1", {"url": "https://www.example.cz/cenik"}),
        _result("fetch_url", "f1", "Ceník: přepis 1 590 Kč"),
    ]

    assert turn_pages(messages) == [
        SourcePage("example.cz/cenik", "https://www.example.cz/cenik", "Ceník: přepis 1 590 Kč")
    ]


def test_search_snippets_are_pages_only_when_nothing_was_read() -> None:
    search = json.dumps(
        {"results": [{"title": "A", "url": "https://a.cz", "snippet": "A sells it for 100 Kč"}]}
    )
    only_search = [_call("web_search", "s1"), _result("web_search", "s1", search)]

    assert turn_pages(only_search) == [SourcePage("A", "https://a.cz", "A sells it for 100 Kč")]
    assert uncited_web_text(only_search) == ""

    with_fetch = [
        *only_search,
        _call("fetch_url", "f1", {"url": "https://b.cz"}),
        _result("fetch_url", "f1", "B page"),
    ]
    assert [p.url for p in turn_pages(with_fetch)] == ["https://b.cz"]
    # The snippet still informs the verifier, it just can't be cited
    assert "A sells it for 100 Kč" in uncited_web_text(with_fetch)


def test_unparsed_web_tool_text_is_uncited() -> None:
    messages = [_result("research", "r1", "Kolo stojí 32 990 Kč u Bike Prague.")]

    assert turn_pages(messages) == []
    assert uncited_web_text(messages) == "Kolo stojí 32 990 Kč u Bike Prague."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_source_pages.py -q > $TMPDIR/t1.log 2>&1; echo $?; tail -5 $TMPDIR/t1.log`
Expected: exit 1, `ModuleNotFoundError: No module named 'src.agent.source_pages'`.

- [ ] **Step 3: Implement `src/agent/source_pages.py`**

Move the helpers out of `content.py` (delete them there; `content.py` imports `turn_pages`). Keep the selection rules of the old `extract_read_sources` exactly: read pages first (research pages with `content`, `delegate_task` sources, successful `fetch_url`, successful `browser`, escalated `web_search`), de-duplicated by URL, at most `_MAX_READ_SOURCES`; otherwise rank-interleaved search results, at most `_MAX_SEARCH_SOURCES`.

```python
"""The pages a turn read, numbered the way the user sees them.

One list feeds both the sources popup (title + URL) and the grounding
verifier (title + URL + text), so a claim's source number always points at
the same page in both places.
"""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.content_text import extract_text_content

WEB_TOOL_NAMES = frozenset({"research", "web_search", "fetch_url", "browser"})
_MAX_READ_SOURCES = 10
_MAX_SEARCH_SOURCES = 5


@dataclass(frozen=True)
class SourcePage:
    """One page the turn read (or one search result when nothing was read)."""

    title: str
    url: str
    text: str


def _json_object(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError, TypeError:
        return None
    return data if isinstance(data, dict) else None


def _title_from_url(url: str) -> str:
    """Readable stand-in title when the tool did not report one."""
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else url


def _search_results(data: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Result lists of a single ({results}) or batched ({searches}) web_search."""
    if isinstance(data.get("searches"), list):
        return [s.get("results") or [] for s in data["searches"] if isinstance(s, dict)]
    return [data.get("results") or []]


def _tool_calls(messages: list[BaseMessage]) -> dict[str, tuple[str, dict[str, Any]]]:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls:
                if tc.get("id"):
                    calls[tc["id"]] = (tc.get("name", ""), tc.get("args") or {})
    return calls


def _page(item: dict[str, Any], text: str) -> SourcePage | None:
    url = str(item.get("url") or item.get("href") or "")
    if not url:
        return None
    return SourcePage(str(item.get("title") or _title_from_url(url)), url, text)


def _read_and_searched(
    messages: list[BaseMessage],
) -> tuple[list[SourcePage], list[list[SourcePage]], list[str]]:
    """(read pages, search result lists, web tool text that parsed as neither)."""
    calls = _tool_calls(messages)
    read: list[SourcePage] = []
    searched: list[list[SourcePage]] = []
    loose: list[str] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage) or msg.status == "error":
            continue
        name = msg.name or calls.get(msg.tool_call_id, ("", {}))[0]
        args = calls.get(msg.tool_call_id, ("", {}))[1]
        data = _json_object(msg.content)
        escalated = name == "web_search" and data is not None and "_escalated" in data
        if (name in ("research", "delegate_task") or escalated) and data:
            for source in data.get("sources") or []:
                # research lists failed fetches too; only pages with content were read
                if isinstance(source, dict) and (name == "delegate_task" or "content" in source):
                    page = _page(source, str(source.get("content") or ""))
                    if page:
                        read.append(page)
        elif name == "fetch_url":
            url = args.get("url")
            failed = data is not None and bool(data.get("error"))
            if url and msg.content and not failed:
                read.append(SourcePage(_title_from_url(str(url)), str(url), extract_text_content(msg.content)))
        elif name == "browser" and data and data.get("success") and data.get("url"):
            page = _page(data, str(data.get("content") or ""))
            if page:
                read.append(page)
        elif name == "web_search" and data:
            searched.extend(
                [p for r in results if isinstance(r, dict) and (p := _page(r, str(r.get("snippet") or "")))]
                for results in _search_results(data)
            )
        elif name in WEB_TOOL_NAMES:
            text = extract_text_content(msg.content).strip()
            if text:
                loose.append(text)
    return read, searched, loose


def _unique(pages: list[SourcePage], limit: int) -> list[SourcePage]:
    out: list[SourcePage] = []
    seen: set[str] = set()
    for page in pages:
        if page.url in seen:
            continue
        seen.add(page.url)
        out.append(page)
        if len(out) >= limit:
            break
    return out


def _interleave(searched: list[list[SourcePage]]) -> list[SourcePage]:
    longest = max((len(r) for r in searched), default=0)
    return [results[rank] for rank in range(longest) for results in searched if rank < len(results)]


def turn_pages(messages: list[BaseMessage]) -> list[SourcePage]:
    """The turn's pages in source-popup order (read pages, else search results)."""
    read, searched, _ = _read_and_searched(messages)
    if read:
        return _unique(read, _MAX_READ_SOURCES)
    return _unique(_interleave(searched), _MAX_SEARCH_SOURCES)


def uncited_web_text(messages: list[BaseMessage]) -> str:
    """Web tool text the verifier may use but cannot cite by number."""
    read, searched, loose = _read_and_searched(messages)
    parts = list(loose)
    if read:
        parts += [f"{p.title}: {p.text}" for p in _interleave(searched) if p.text]
    return "\n".join(parts)
```

`extract_text_content` lives in `src/agent/content.py`; if importing it from there makes a cycle (`content.py` will import `source_pages`), move it into a new `src/agent/content_text.py` and import it from there in both modules (update every `from src.agent.content import extract_text_content` with `grep -rn "import.*extract_text_content" src evals tests`). In `content.py`:

```python
from src.agent.source_pages import turn_pages


def extract_read_sources(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Source chips for a turn: the pages it read, numbered as in turn_pages()."""
    return [{"title": p.title, "url": p.url} for p in turn_pages(messages)]
```

Keep the long rationale docstring (the cite_sources history) on `turn_pages`.

- [ ] **Step 4: Run the new tests and the old source tests**

Run: `.venv/bin/pytest tests/unit/test_source_pages.py $(grep -rl "extract_read_sources" tests) -q > $TMPDIR/t1.log 2>&1; echo $?; tail -3 $TMPDIR/t1.log`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/agent/source_pages.py src/agent/content.py src/agent/content_text.py tests/unit/test_source_pages.py
git commit -m "refactor(agent): one numbered page list for source chips and the verifier"
```

---

### Task 2: Claim validation and summary

**Files:**
- Create: `src/agent/grounding_annotations.py`
- Modify: `src/config.py:408-420`, `.env.example:371-381`
- Test: `tests/unit/test_grounding_annotations.py`

**Interfaces:**
- Consumes: `SourcePage` (Task 1).
- Produces:
  - `Verdict = Literal["supported", "partial", "not_found", "contradicted"]`
  - `class ClaimVerdict(BaseModel)`: `quote: str`, `verdict: Verdict`, `source: int | None = None`, `source_quote: str | None = None`, `reason: str | None = None`
  - `class GroundingVerdict(BaseModel)`: `claims: list[ClaimVerdict]`
  - `validate_claims(claims: list[ClaimVerdict], answer: str, pages: list[SourcePage]) -> list[dict[str, Any]]` (annotation dicts in answer order)
  - `summarize(source_count: int) -> dict[str, Any]` returning `{"checked": True, "source_count": source_count}`
  - `format_grounding_context(annotations: list[dict[str, Any]] | None) -> str | None`
- Config produces: `Config.GROUNDING_CHECK_MAX_CLAIMS`, `GROUNDING_CHECK_MAX_QUOTE_CHARS`, `GROUNDING_CHECK_MAX_REASON_CHARS`, `GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS`, `GROUNDING_CONTEXT_MAX_CHARS`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for verifier-claim validation (src/agent/grounding_annotations.py)."""

import pytest

from src.agent.grounding_annotations import (
    ClaimVerdict,
    format_grounding_context,
    validate_claims,
)
from src.agent.source_pages import SourcePage
from src.config import Config

_PAGES = [
    SourcePage("SPZ Služby", "https://spzsluzby.cz", "Doklady vyřídíme   do 24 hodin. Cena 1 590 Kč."),
    SourcePage("Pomocnice", "https://pomocnice.cz", "Správní poplatek 800 Kč."),
]
_ANSWER = (
    "**SPZ Služby**: vyřízení do 24 hodin, cena 1 590 Kč + 800 Kč.\n"
    "**PřepiServis**: rychlost 24–48 hodin, cena 1 200 Kč + 800 Kč."
)


def _claim(**kw: object) -> ClaimVerdict:
    return ClaimVerdict.model_validate({"verdict": "supported", **kw})


def test_supported_claim_keeps_source_and_literal_passage() -> None:
    [ann] = validate_claims(
        [_claim(quote="vyřízení do 24 hodin", source=1, source_quote="vyřídíme do 24 hodin")],
        _ANSWER,
        _PAGES,
    )

    assert ann == {
        "type": "claim",
        "verdict": "supported",
        "quote": "vyřízení do 24 hodin",
        "prefix": "**SPZ Služby**: ",
        "source": 1,
        "source_quote": "vyřídíme do 24 hodin",
    }


def test_downgrades_paraphrased_passage() -> None:
    [ann] = validate_claims(
        [_claim(quote="cena 1 590 Kč", source=1, source_quote="stojí to 1590 korun")],
        _ANSWER,
        _PAGES,
    )

    assert ann["verdict"] == "not_found"
    assert "source" not in ann and "source_quote" not in ann


@pytest.mark.parametrize("source", [0, 3, None])
def test_downgrades_out_of_range_source(source: int | None) -> None:
    [ann] = validate_claims(
        [_claim(quote="cena 1 590 Kč", verdict="contradicted", source=source, source_quote="Cena 1 590 Kč")],
        _ANSWER,
        _PAGES,
    )

    assert ann["verdict"] == "not_found"


def test_supported_without_a_source_number_stays_supported() -> None:
    # Backed only by uncited search text: counts as supported, shows no number
    [ann] = validate_claims([_claim(quote="cena 1 590 Kč")], _ANSWER, _PAGES)

    assert ann["verdict"] == "supported" and "source" not in ann


def test_drops_quotes_not_in_the_answer_and_orders_by_position() -> None:
    anns = validate_claims(
        [
            _claim(quote="rychlost 24–48 hodin", verdict="not_found", reason="Není ve zdrojích."),
            _claim(quote="PřepiServis s.r.o.", verdict="not_found"),
            _claim(quote="vyřízení do 24 hodin"),
        ],
        _ANSWER,
        _PAGES,
    )

    assert [a["quote"] for a in anns] == ["vyřízení do 24 hodin", "rychlost 24–48 hodin"]


def test_prefix_comes_from_the_first_occurrence_in_the_answer() -> None:
    [ann] = validate_claims([_claim(quote="800 Kč", source=2, source_quote="poplatek 800 Kč")], _ANSWER, _PAGES)

    assert ann["prefix"].endswith("1 590 Kč + ")


def test_caps_claims_reasons_and_passages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_CLAIMS", 1)
    monkeypatch.setattr(Config, "GROUNDING_CHECK_MAX_REASON_CHARS", 10)
    anns = validate_claims(
        [
            _claim(quote="rychlost 24–48 hodin", verdict="not_found", reason="x" * 50),
            _claim(quote="cena 1 200 Kč", verdict="not_found"),
        ],
        _ANSWER,
        _PAGES,
    )

    assert len(anns) == 1
    assert anns[0]["reason"] == "x" * 9 + "…"


def test_schedule_times_are_dropped_when_unsupported() -> None:
    answer = "Plán: 10:15 odjezd, 11:30 oběd, 13:00 hrad, 15:45 návrat."
    anns = validate_claims(
        [_claim(quote=t, verdict="not_found") for t in ("10:15", "11:30", "13:00")],
        answer,
        [],
    )

    assert anns == []


def test_grounding_context_lists_only_problems_and_never_closes_the_comment() -> None:
    text = format_grounding_context(
        [
            {"type": "claim", "verdict": "supported", "quote": "a"},
            {"type": "claim", "verdict": "not_found", "quote": "PřepiServis", "reason": "Není -->"},
            {"type": "claim", "verdict": "contradicted", "quote": "1 200 Kč", "reason": "Zdroj: 1 590 Kč"},
        ]
    )

    assert text == "unsourced: PřepiServis (Není ); contradicted: 1 200 Kč (Zdroj: 1 590 Kč)"
    assert format_grounding_context([{"type": "claim", "verdict": "supported", "quote": "a"}]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_grounding_annotations.py -q > $TMPDIR/t2.log 2>&1; echo $?; tail -3 $TMPDIR/t2.log`
Expected: exit 1, `No module named 'src.agent.grounding_annotations'`.

- [ ] **Step 3: Config**

In `src/config.py` replace `GROUNDING_CHECK_MAX_ITEMS`, `GROUNDING_CHECK_MAX_FALSE_CLAIMS` and `GROUNDING_CHECK_MAX_ITEM_CHARS` with:

```python
    # Claims the verifier may return per answer (supported ones included)
    GROUNDING_CHECK_MAX_CLAIMS: int = int(os.getenv("GROUNDING_CHECK_MAX_CLAIMS", "20"))
    # Longer "quotes" are sentences, not claims
    GROUNDING_CHECK_MAX_QUOTE_CHARS: int = int(os.getenv("GROUNDING_CHECK_MAX_QUOTE_CHARS", "120"))
    GROUNDING_CHECK_MAX_REASON_CHARS: int = int(os.getenv("GROUNDING_CHECK_MAX_REASON_CHARS", "160"))
    GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS: int = int(
        os.getenv("GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS", "240")
    )
    # The MSG_CONTEXT grounding entry later turns see
    GROUNDING_CONTEXT_MAX_CHARS: int = int(os.getenv("GROUNDING_CONTEXT_MAX_CHARS", "400"))
```

Mirror in `.env.example` (same comment style as the neighbouring lines), removing the three old keys.

- [ ] **Step 4: Implement `src/agent/grounding_annotations.py`**

```python
"""Validated grounding claims: what the verifier said, kept only where provable.

The verifier (src/agent/grounding_check.py) judges each specific claim in an
answer against the turn's numbered pages (src/agent/source_pages.py). Nothing
it returns is trusted: a quote must be in the answer, a source passage must be
in the cited page, or the claim loses its source. Spec:
docs/superpowers/specs/2026-10-03-grounding-annotations-design.md.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agent.source_pages import SourcePage
from src.config import Config

Verdict = Literal["supported", "partial", "not_found", "contradicted"]
_PREFIX_CHARS = 32
_WITH_SOURCE: frozenset[str] = frozenset({"supported", "partial", "contradicted"})
# A bare time or time range ("10:15", "12:00–14:15"). Three or more unsupported
# ones are the answer's own timeline, which the verifier flags despite the prompt
_BARE_TIME = re.compile(r"~?\d{1,2}[:.]\d{2}(?:\s*[–—-]\s*\d{1,2}[:.]\d{2})?")
_SCHEDULE_MIN_TIMES = 3
_SPACE = re.compile(r"\s+")


class ClaimVerdict(BaseModel):
    """One specific claim in the answer and how the sources bear on it."""

    quote: str = Field(..., description="The shortest phrase stating the claim, copied exactly from the ANSWER")
    verdict: Verdict
    source: int | None = Field(default=None, description="Number of the SOURCE page, e.g. 2 for [2]")
    source_quote: str | None = Field(default=None, description="Passage copied exactly from that page")
    reason: str | None = Field(default=None, description="One sentence, in the ANSWER's language")


class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    claims: list[ClaimVerdict] = Field(default_factory=list)


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _passage_in_page(claim: ClaimVerdict, pages: list[SourcePage]) -> bool:
    if claim.source is None or not claim.source_quote or not 1 <= claim.source <= len(pages):
        return False
    return _norm(claim.source_quote) in _norm(pages[claim.source - 1].text)


def _annotation(claim: ClaimVerdict, answer: str, start: int, pages: list[SourcePage]) -> dict[str, Any]:
    quote = claim.quote.strip()
    ann: dict[str, Any] = {
        "type": "claim",
        "verdict": claim.verdict,
        "quote": quote,
        "prefix": answer[max(0, start - _PREFIX_CHARS) : start],
    }
    cited = _passage_in_page(claim, pages)
    if claim.verdict in _WITH_SOURCE and cited:
        ann["source"] = claim.source
        ann["source_quote"] = _clip(claim.source_quote or "", Config.GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS)
    elif claim.verdict != "supported" or claim.source is not None:
        # Unprovable passage: a claim is never shown with a source it lacks.
        # A supported claim with no number at all is backed by uncited text.
        ann["verdict"] = "not_found"
    if ann["verdict"] != "supported" and claim.reason:
        ann["reason"] = _clip(claim.reason.strip(), Config.GROUNDING_CHECK_MAX_REASON_CHARS)
    return ann


def _drop_schedule_times(anns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    times = [a for a in anns if a["verdict"] != "supported" and _BARE_TIME.fullmatch(a["quote"])]
    if len(times) < _SCHEDULE_MIN_TIMES:
        return anns
    return [a for a in anns if a not in times]


def validate_claims(
    claims: list[ClaimVerdict], answer: str, pages: list[SourcePage]
) -> list[dict[str, Any]]:
    """Annotations for the claims that can be shown, in answer order."""
    haystack = answer.casefold()
    placed: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for claim in claims:
        quote = claim.quote.strip()
        start = haystack.find(quote.casefold()) if quote else -1
        if start < 0 or quote in seen or len(quote) > Config.GROUNDING_CHECK_MAX_QUOTE_CHARS:
            continue
        seen.add(quote)
        placed.append((start, _annotation(claim, answer, start, pages)))
        if len(placed) >= Config.GROUNDING_CHECK_MAX_CLAIMS:
            break
    placed.sort(key=lambda item: item[0])
    return _drop_schedule_times([ann for _, ann in placed])


def summarize(source_count: int) -> dict[str, Any]:
    """The footer's summary for a checked answer."""
    return {"checked": True, "source_count": source_count}


_CONTEXT_LABELS = {"not_found": "unsourced", "partial": "partly sourced", "contradicted": "contradicted"}


def format_grounding_context(annotations: list[dict[str, Any]] | None) -> str | None:
    """MSG_CONTEXT entry: the claims a later turn must not repeat as fact."""
    groups: dict[str, list[str]] = {}
    for ann in annotations or []:
        label = _CONTEXT_LABELS.get(ann.get("verdict", ""))
        if not label:
            continue
        reason = (ann.get("reason") or "").replace("-->", "").strip()
        groups.setdefault(label, []).append(f"{ann['quote']} ({reason})" if reason else ann["quote"])
    if not groups:
        return None
    text = "; ".join(f"{label}: {', '.join(items)}" for label, items in groups.items())
    return _clip(text.replace("-->", ""), Config.GROUNDING_CONTEXT_MAX_CHARS)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit/test_grounding_annotations.py -q > $TMPDIR/t2.log 2>&1; echo $?; tail -3 $TMPDIR/t2.log`
Expected: exit 0. (`test_grounding_check.py` still imports the old names; it is rewritten in Task 3.)

- [ ] **Step 6: Commit**

```bash
git add src/agent/grounding_annotations.py src/config.py .env.example tests/unit/test_grounding_annotations.py
git commit -m "feat(agent): validate grounding claims into annotations"
```

---

### Task 3: Verifier judges every claim; answer text stays untouched

**Files:**
- Modify: `src/agent/grounding_check.py` (whole module), `src/agent/prompt_texts/grounding.py`, `src/agent/agent.py:18,325,505-515`
- Delete: `src/agent/grounding_markers.py`, `tests/unit/test_grounding_markers.py`
- Rewrite: `tests/unit/test_grounding_check.py`, `tests/unit/test_grounding_hooks.py`

**Interfaces:**
- Consumes: `turn_pages`, `uncited_web_text`, `SourcePage` (Task 1); `ClaimVerdict`, `GroundingVerdict`, `validate_claims`, `summarize` (Task 2).
- Produces:
  - `@dataclass GroundingOutcome`: `annotations: list[dict[str, Any]]`, `summary: dict[str, Any] | None`, `usage: dict[str, Any] | None`
  - `should_check(answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None) -> bool`
  - `check_grounding(answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None) -> GroundingOutcome`
  - `apply_grounding(answer: str, result_messages: list[BaseMessage], usage_info: dict[str, Any], stop_reason: str | None = None) -> None` — sets `usage_info["grounding_usage"]` (as today) and, when there are annotations, `usage_info["grounding"] = {"annotations": [...], "summary": {...}}`.
  - Agent: `chat_batch` no longer reassigns `response_text`; `stream_chat` yields `{"type": "grounding_started"}` before the check when `grounding_check.should_check(...)` is true. `agent.py` calls both through the module (`from src.agent import grounding_check`), so the E2E server can patch them.

- [ ] **Step 1: Rewrite the failing tests**

`tests/unit/test_grounding_check.py` — keep `_tool`, `_USAGE`, `fake_verifier` (now returning `(GroundingVerdict(...), _USAGE)`), the skip parametrization (rename to `check_grounding`), the fail-open test, the delegate test and the `known_facts` tests unchanged. Replace `TestCollectWebSources` and `TestFindUnverified` with:

```python
import json

from src.agent.grounding_annotations import ClaimVerdict, GroundingVerdict
from src.agent.grounding_check import check_grounding, format_sources, should_check
from src.agent.source_pages import SourcePage


def _research_turn(text: str) -> list[Any]:
    payload = json.dumps({"sources": [{"title": "Bike Prague", "url": "https://bike.cz", "content": text}]})
    return [
        AIMessage(content="", tool_calls=[{"name": "research", "args": {}, "id": "r1"}]),
        ToolMessage(content=payload, tool_call_id="r1", name="research"),
    ]


_WEB_TURN = _research_turn("Kolo Brompton C Line stojí 32 990 Kč u Bike Prague.")
_ANSWER = "Brompton koupíte u Bike Prague (32 990 Kč) nebo ve VeloRama za 29 990 Kč."


class TestFormatSources:
    def test_numbers_pages_and_appends_uncited_text(self) -> None:
        text = format_sources(
            [SourcePage("A", "https://a.cz", "alpha"), SourcePage("B", "https://b.cz", "beta")],
            "snippet text",
            1000,
        )

        assert text.startswith("[1] A (https://a.cz)\nalpha\n\n[2] B (https://b.cz)\nbeta")
        assert text.endswith("UNNUMBERED (may support a claim, cannot be cited):\nsnippet text")

    def test_cap_is_shared_between_pages(self) -> None:
        text = format_sources([SourcePage("A", "u", "a" * 500), SourcePage("B", "v", "b" * 500)], "", 200)

        assert text.count("a") <= 100 and text.count("b") <= 100


class TestCheckGrounding:
    def test_returns_validated_annotations_and_summary(self, fake_verifier: MagicMock) -> None:
        fake_verifier.return_value = (
            GroundingVerdict(
                claims=[
                    ClaimVerdict(quote="Bike Prague", verdict="supported", source=1, source_quote="u Bike Prague"),
                    ClaimVerdict(quote="VeloRama", verdict="not_found", reason="Ve zdroji není."),
                ]
            ),
            _USAGE,
        )

        outcome = check_grounding(_ANSWER, _WEB_TURN)

        assert [a["verdict"] for a in outcome.annotations] == ["supported", "not_found"]
        assert outcome.summary == {"checked": True, "source_count": 1}
        assert outcome.usage == _USAGE

    def test_prompt_carries_numbered_pages(self, fake_verifier: MagicMock) -> None:
        check_grounding(_ANSWER, _WEB_TURN)

        sources_arg = fake_verifier.call_args.args[1]
        assert sources_arg.startswith("[1] Bike Prague (https://bike.cz)")

    def test_should_check_matches_check_grounding_skips(self, fake_verifier: MagicMock) -> None:
        assert should_check(_ANSWER, _WEB_TURN)
        assert not should_check(_ANSWER, _WEB_TURN, "user")
        assert not should_check("", _WEB_TURN)
        assert not should_check(_ANSWER, [_tool("execute_code", "42")])
```

`tests/unit/test_grounding_hooks.py` — replace the fixture and assertions:

```python
from src.agent.grounding_check import GroundingOutcome, apply_grounding

_ANNS = [{"type": "claim", "verdict": "not_found", "quote": "VeloRama", "prefix": "Buy it at "}]
_SUMMARY = {"checked": True, "source_count": 2}


@pytest.fixture
def flag(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(Config, "GROUNDING_CHECK_ENABLED", True)
    fake = MagicMock(return_value=GroundingOutcome(annotations=_ANNS, summary=_SUMMARY, usage=_USAGE))
    monkeypatch.setattr(grounding_check, "check_grounding", fake)
    monkeypatch.setattr(grounding_check, "should_check", MagicMock(return_value=True))
    return fake


class TestApplyGrounding:
    def test_records_annotations_and_usage_without_touching_text(self, flag: MagicMock) -> None:
        usage_info: dict[str, Any] = {"input_tokens": 1}

        assert apply_grounding(_ANSWER, [], usage_info) is None
        assert usage_info["grounding"] == {"annotations": _ANNS, "summary": _SUMMARY}
        assert usage_info["grounding_usage"] == _USAGE

    def test_no_claims_records_nothing(self, flag: MagicMock) -> None:
        flag.return_value = GroundingOutcome(annotations=[], summary=None, usage=None)
        usage_info: dict[str, Any] = {}

        apply_grounding("All supported.", [], usage_info)

        assert usage_info == {}
```

In `TestAgentHooks` assert the batch response text equals `_ANSWER` and `usage_info["grounding"]["annotations"] == _ANNS`; for the stream, assert the yielded event types contain `"grounding_started"` before `"final"`, and the final event's `content == _ANSWER` and `usage_info["grounding"]` is set.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_grounding_check.py tests/unit/test_grounding_hooks.py -q > $TMPDIR/t3.log 2>&1; echo $?; tail -5 $TMPDIR/t3.log`
Expected: exit 1/2, ImportError for `check_grounding` / `GroundingOutcome`.

- [ ] **Step 3: Rewrite the prompt** (`src/agent/prompt_texts/grounding.py`)

```python
"""Prompt for the post-answer grounding check (src/agent/grounding_check.py)."""

# Every claim gets a verdict; the server keeps a source number only when the
# copied passage is really in that page. Formatted with str.format - keep
# literal braces doubled.
GROUNDING_CHECK_PROMPT = """You check an assistant's ANSWER against the numbered web SOURCES it read this turn.

List every specific claim in the ANSWER about businesses, products, services, events, prices, opening hours, dates, times of events and contact details. Each claim is the SHORTEST phrase that states it, copied exactly from the ANSWER: a business name, or "Cena: kolem 1 200–1 600 Kč" - never a whole paragraph. Go through the answer line by line, tables included.

For each claim give a verdict:
- supported: a numbered SOURCE states it (in any wording or language). Give its number as source and copy the supporting passage exactly from that source as source_quote.
- partial: a SOURCE states part of it. Give source and source_quote for the part, and a reason naming the part that is missing.
- contradicted: a SOURCE says something different. Give source, the conflicting passage as source_quote, and a reason.
- not_found: no SOURCE supports it. Give a reason.

If only the UNNUMBERED text supports a claim, it is supported with no source.

A reason is one short sentence in the ANSWER's language, about the sources ("Stránky popisují jen SPZ Služby; PřepiServis v nich není.").

A sentence in which the ANSWER says it verified, checked or confirmed something is a claim too: contradicted or not_found when the SOURCES don't back it.

NEVER list:
- the answer's own plan, schedule, suggested times, durations or itinerary ("10:30 departure", "about 30 minutes") - these are proposals, not claims
- well-known places and geography: towns, villages, hills, rivers, regions, roads, countries
- general knowledge, advice, explanations, or the answer's own reasoning
- anything the ANSWER already marks as unverified, approximate or an estimate
- anything in KNOWN

KNOWN (always supported - never list these):
{known}

SOURCES:
{sources}

ANSWER:
{answer}
"""
```

- [ ] **Step 4: Rewrite `src/agent/grounding_check.py`**

Keep: module docstring (update the last paragraph to point at `grounding_annotations.py` and the Oct 3 spec), `_KNOWN_*` caps, `_now`, `_turn_tool_facts`, `known_facts`, the `_run_verifier` body (its structured output type is now `GroundingVerdict` from `grounding_annotations`). Delete: `UnverifiedItem`, the old `GroundingVerdict`, `GroundingResult`, `collect_web_sources`, `_drop_schedule_times`, `_literal`, `_keep`, `find_unverified`, `_SOURCE_SEPARATOR`, `WEB_TOOL_NAMES` (moved to `source_pages`). Add:

```python
@dataclass
class GroundingOutcome:
    """Annotations to store, the footer summary, and verifier usage."""

    annotations: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


_UNCITED_HEADER = "UNNUMBERED (may support a claim, cannot be cited):"


def format_sources(pages: list[SourcePage], uncited: str, max_chars: int) -> str:
    """Numbered pages, each capped to a fair share of max_chars, then uncited text."""
    parts = 1 + len(pages) if uncited else len(pages)
    share = max_chars // max(parts, 1)
    blocks = [f"[{i}] {p.title} ({p.url})\n{p.text[:share]}" for i, p in enumerate(pages, 1)]
    if uncited:
        blocks.append(f"{_UNCITED_HEADER}\n{uncited[:share]}")
    return "\n\n".join(blocks)


def should_check(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> bool:
    """Whether this answer gets a grounding check (and a grounding_started event)."""
    if not Config.GROUNDING_CHECK_ENABLED or stop_reason or not answer.strip():
        return False
    if in_delegate_run():
        # The parent turn's answer is the one users see; a check here would
        # cost an unrecorded call
        return False
    return bool(turn_pages(result_messages) or uncited_web_text(result_messages))


def check_grounding(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> GroundingOutcome:
    """Every specific claim in a web-tool answer, judged against its pages.

    Fails open: any verifier error returns an empty outcome.
    """
    if not should_check(answer, result_messages, stop_reason):
        return GroundingOutcome()
    pages = turn_pages(result_messages)
    sources = format_sources(
        pages, uncited_web_text(result_messages), Config.GROUNDING_CHECK_MAX_SOURCE_CHARS
    )
    started = time.monotonic()
    try:
        verdict, usage = _run_verifier(answer, sources, known_facts(result_messages))
    except Exception:
        logger.warning("Grounding check failed", exc_info=True, extra={"source_chars": len(sources)})
        return GroundingOutcome()
    annotations = validate_claims(verdict.claims if verdict else [], answer, pages)
    counts = Counter(a["verdict"] for a in annotations)
    logger.info(
        "Grounding check",
        extra={
            "verdict_counts": dict(counts),
            "source_count": len(pages),
            "source_chars": len(sources),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "parsed": verdict is not None,
        },
    )
    summary = summarize(len(pages)) if annotations else None
    return GroundingOutcome(annotations=annotations, summary=summary, usage=usage)


def apply_grounding(
    answer: str,
    result_messages: list[BaseMessage],
    usage_info: dict[str, Any],
    stop_reason: str | None = None,
) -> None:
    """Check the answer and record the outcome in usage_info for the save path.

    usage_info already carries the turn's usage to save_message_to_db in both
    the batch and the stream path, so the annotations ride along with it.
    `check_grounding` is looked up on the module at call time (patchable).
    """
    outcome = check_grounding(answer, result_messages, stop_reason)
    if outcome.usage:
        usage_info["grounding_usage"] = outcome.usage
    if outcome.annotations:
        usage_info["grounding"] = {"annotations": outcome.annotations, "summary": outcome.summary}
```

Imports: `from collections import Counter`, `from src.agent.grounding_annotations import GroundingVerdict, validate_claims, summarize`, `from src.agent.source_pages import SourcePage, turn_pages, uncited_web_text`. Grep for other users of the deleted names: `grep -rn "collect_web_sources\|find_unverified\|GroundingResult\|WEB_TOOL_NAMES\|grounding_markers" src evals tests` and update each (e.g. `evals/run.py` cost code only reads `grounding_usage`).

- [ ] **Step 5: Agent call sites** (`src/agent/agent.py`)

Replace `from src.agent.grounding_check import apply_grounding` with `from src.agent import grounding_check`. Batch (line ~325):

```python
        usage_info = batch_usage_info(result_messages, turn_duration_ms)
        grounding_check.apply_grounding(response_text, result_messages, usage_info)
```

Stream (line ~505):

```python
        for event in processor.finish(turn_started, stop_reason=stop_reason):
            if event.get("type") == "final":
                args = (event["content"], event["result_messages"])
                if grounding_check.should_check(*args, event.get("stop_reason")):
                    yield {"type": "grounding_started"}
                grounding_check.apply_grounding(*args, event["usage_info"], event.get("stop_reason"))
            yield event
```

- [ ] **Step 6: Delete the marker module and its test, run the grounding tests**

```bash
git rm src/agent/grounding_markers.py tests/unit/test_grounding_markers.py
.venv/bin/pytest tests/unit/test_grounding_check.py tests/unit/test_grounding_hooks.py tests/unit/test_grounding_cost.py tests/unit/test_grounding_directive.py -q > $TMPDIR/t3.log 2>&1; echo $?; tail -3 $TMPDIR/t3.log
```
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add -A src/agent tests/unit
git commit -m "feat(agent): grounding verifier judges every claim against numbered pages"
```

---

### Task 4: Store and serve annotations

**Files:**
- Create: `migrations/0057_add_message_annotations.py`
- Modify: `src/db/models/dataclasses.py:73-90`, `src/db/models/message_rows.py:13-27`, `src/db/models/message.py` (`add_message`, `update_message_content`, `_store_message_payload` callers), `src/api/helpers/chat_save.py` (`_persist_assistant_message`, `save_message_to_db`), `src/api/utils.py` (`build_chat_response`, `build_stream_done_event`, `serialize_messages_for_response`), `src/api/schemas/chat.py`
- Regenerate: `static/openapi.json`, `web/src/types/generated-api.ts` (`make openapi && make types`)
- Test: `tests/unit/test_message_annotations_storage.py`, `tests/integration/test_chat_annotations.py`

**Interfaces:**
- Consumes: `usage_info["grounding"]` (Task 3).
- Produces: `Message.annotations: list[dict[str, Any]] | None`, `Message.grounding: dict[str, Any] | None`; `db.add_message(..., annotations=None, grounding=None)`, `db.update_message_content(..., annotations=None, grounding=None)`; API fields `annotations` / `grounding` on `MessageResponse`, `ChatBatchResponse` and the stream `done` event (omitted when `None`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_message_annotations_storage.py` (use the repo's `db`/conversation fixtures from `tests/conftest.py`; check `grep -n "def test_db\|def conversation" tests/conftest.py` for names):

```python
"""Annotations and the grounding summary round-trip through the messages table."""

from typing import Any

from src.api.schemas.common import MessageRole
from src.api.utils import serialize_messages_for_response

_ANNS = [{"type": "claim", "verdict": "not_found", "quote": "PřepiServis", "prefix": "", "reason": "Není."}]
_SUMMARY = {"checked": True, "source_count": 3}


def test_add_and_read_back(test_db: Any, conversation: Any) -> None:
    msg = test_db.add_message(conversation.id, MessageRole.ASSISTANT, "text", annotations=_ANNS, grounding=_SUMMARY)

    [stored] = [m for m in test_db.get_messages(conversation.id) if m.id == msg.id]
    assert stored.annotations == _ANNS and stored.grounding == _SUMMARY
    assert stored.content == "text"


def test_update_message_content_sets_them(test_db: Any, conversation: Any) -> None:
    msg = test_db.add_message(conversation.id, MessageRole.ASSISTANT, "")

    updated = test_db.update_message_content(msg.id, "final", annotations=_ANNS, grounding=_SUMMARY)

    assert updated is not None and updated.annotations == _ANNS


def test_serializer_includes_them_only_when_present(test_db: Any, conversation: Any) -> None:
    with_anns = test_db.add_message(conversation.id, MessageRole.ASSISTANT, "a", annotations=_ANNS, grounding=_SUMMARY)
    plain = test_db.add_message(conversation.id, MessageRole.ASSISTANT, "b")

    out = {m["id"]: m for m in serialize_messages_for_response([with_anns, plain])}

    assert out[with_anns.id]["annotations"] == _ANNS and out[with_anns.id]["grounding"] == _SUMMARY
    assert "annotations" not in out[plain.id] and "grounding" not in out[plain.id]
```

`tests/integration/test_chat_annotations.py` — follow the batch/stream mocking pattern of an existing integration chat test (`grep -ln "chat/batch" tests/integration | head -1`): mock `chat_batch` to return `("Answer about PřepiServis.", [], {"grounding": {"annotations": _ANNS, "summary": _SUMMARY}}, [])`, POST `/api/conversations/<id>/chat/batch`, assert the response JSON has `annotations == _ANNS`, `grounding == _SUMMARY`, and `GET /api/conversations/<id>` returns them on the assistant message. For the stream: mock `stream_chat_events` with a final event `{"type": "final", "content": "...", "result_messages": [], "tool_results": [], "usage_info": {"grounding": {...}}}`, read the SSE body, assert the `done` event carries both fields.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/unit/test_message_annotations_storage.py tests/integration/test_chat_annotations.py -q > $TMPDIR/t4.log 2>&1; echo $?; tail -5 $TMPDIR/t4.log`
Expected: exit 1, `TypeError: add_message() got an unexpected keyword argument 'annotations'`.

- [ ] **Step 3: Migration `migrations/0057_add_message_annotations.py`**

```python
"""Add annotations and grounding to messages.

annotations: JSON list of claim annotations (verdict, quote, prefix, reason,
source, source_quote) from the post-answer grounding check; grounding: JSON
summary for the footer ({"checked": true, "source_count": N}). Both NULL for
messages that were never checked. Spec:
docs/superpowers/specs/2026-10-03-grounding-annotations-design.md.
"""

from yoyo import step

__depends__ = {"0056_add_conversation_trash"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN annotations TEXT",
        "ALTER TABLE messages DROP COLUMN annotations",
    ),
    step(
        "ALTER TABLE messages ADD COLUMN grounding TEXT",
        "ALTER TABLE messages DROP COLUMN grounding",
    ),
]
```

- [ ] **Step 4: Dataclass, row mapping, add/update**

`dataclasses.py` (after `stop_reason`):

```python
    # Grounding-check claims ({type, verdict, quote, prefix, reason?, source?,
    # source_quote?}) and the footer summary; None when never checked
    annotations: list[dict[str, Any]] | None = None
    grounding: dict[str, Any] | None = None
```

`message_rows.py`:

```python
        annotations=_json_column(row, "annotations"),
        grounding=_json_column(row, "grounding"),
```

with

```python
def _json_column(row: sqlite3.Row, name: str) -> Any:
    """Parsed JSON of an optional column (absent in pre-0057 test schemas)."""
    return json.loads(row[name]) if name in row.keys() and row[name] else None
```

`message.py`: add `annotations: list[dict[str, Any]] | None = None, grounding: dict[str, Any] | None = None` to both `add_message` and `update_message_content` (document them in the Args), serialize with `json.dumps(x, ensure_ascii=False) if x else None`, and add both columns to the INSERT column list/values and the UPDATE `SET` list. If any `SELECT` in `message.py`/`message_pagination.py` lists columns explicitly instead of `SELECT *`, add the two columns there (`grep -n "SELECT" src/db/models/message*.py`).

- [ ] **Step 5: Save path** (`chat_save.py`)

`_persist_assistant_message` gains `grounding: dict[str, Any] | None = None` and adds to `kwargs`:

```python
        "annotations": (grounding or {}).get("annotations"),
        "grounding": (grounding or {}).get("summary"),
```

`save_message_to_db` passes `usage.get("grounding")` as the new argument (after `stop_reason`). No change to `SaveResult`: the done event reads the saved message.

- [ ] **Step 6: Response builders and schemas**

`src/api/utils.py` — in `build_chat_response`, `build_stream_done_event` (both have `assistant_msg`) and `serialize_messages_for_response` (per message `m`), next to the existing `stop_reason` handling:

```python
    annotations = getattr(assistant_msg, "annotations", None)
    if annotations:
        response_data["annotations"] = annotations
        response_data["grounding"] = getattr(assistant_msg, "grounding", None)
```

(`done_data` / `msg_data` respectively.) Note the stream finalize path that re-reads the message (`stream_finalize.py:43-50`) already passes `assistant_msg`.

`src/api/schemas/chat.py`:

```python
class ClaimAnnotationResponse(BaseModel):
    """A grounding-check claim in an assistant message."""

    type: Literal["claim"]
    verdict: Literal["supported", "partial", "not_found", "contradicted"]
    quote: str = Field(description="Literal phrase from the message content")
    prefix: str = Field(default="", description="Text right before the quote (disambiguates repeats)")
    reason: str | None = None
    source: int | None = Field(default=None, description="1-based index into sources")
    source_quote: str | None = Field(default=None, description="Literal passage from that source")


class GroundingSummaryResponse(BaseModel):
    """Footer summary of a grounding-checked message."""

    checked: bool
    source_count: int | None = None
    legacy: bool | None = Field(default=None, description="Converted from pre-Oct-3-2026 inline markers")
```

Add to both `MessageResponse` and `ChatBatchResponse`:

```python
    annotations: list[ClaimAnnotationResponse] | None = None
    grounding: GroundingSummaryResponse | None = None
```

- [ ] **Step 7: Regenerate the API contract**

Run: `make openapi > $TMPDIR/oa.log 2>&1; echo $?; make types > $TMPDIR/ty.log 2>&1; echo $?`
Expected: `0` and `0`; `git diff --stat` shows `static/openapi.json` and `web/src/types/generated-api.ts`.

- [ ] **Step 8: Run tests**

Run: `.venv/bin/pytest tests/unit/test_message_annotations_storage.py tests/integration/test_chat_annotations.py tests/unit/test_chat_save*.py -q > $TMPDIR/t4.log 2>&1; echo $?; tail -3 $TMPDIR/t4.log`
Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add migrations/0057_add_message_annotations.py src/db src/api static/openapi.json web/src/types/generated-api.ts tests/unit/test_message_annotations_storage.py tests/integration/test_chat_annotations.py
git commit -m "feat(api): store grounding annotations beside the message and serve them"
```

---

### Task 5: `grounding_started` reaches the client and the journal

**Files:**
- Modify: `src/api/helpers/chat_streaming.py:393` (forwarded event types), `src/api/helpers/stream_resume.py:24-32`
- Test: `tests/integration/test_chat_annotations.py` (extend), `tests/unit/test_stream_resume.py` (extend)

**Interfaces:**
- Consumes: the `{"type": "grounding_started"}` event from `ChatAgent.stream_chat` (Task 3).
- Produces: SSE `data: {"type": "grounding_started"}` before `done`; replayed by `/chat/resume`.

- [ ] **Step 1: Failing tests**

Integration: with `stream_chat_events` mocked to yield `{"type": "token", "text": "Hi"}`, `{"type": "grounding_started"}`, then the final event, assert the SSE event types are `[..., "token", "grounding_started", "done"]`.

Unit (`tests/unit/test_stream_resume.py`, beside the existing journaling tests):

```python
def test_grounding_started_is_journaled() -> None:
    from src.api.helpers.stream_resume import _JOURNALED_EVENT_TYPES

    assert "grounding_started" in _JOURNALED_EVENT_TYPES
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/integration/test_chat_annotations.py tests/unit/test_stream_resume.py -q > $TMPDIR/t5.log 2>&1; echo $?` → exit 1.

- [ ] **Step 3: Implement**

`stream_resume.py`: add `"grounding_started",` to `_JOURNALED_EVENT_TYPES` with a comment `# the footer's "checking" state survives a reload mid-check`.
`chat_streaming.py`: extend the forwarded tuple to `("thinking", "tool_start", "tool_end", "token", "retry", "stopping", "grounding_started")`.

- [ ] **Step 4: Run tests** — same command → exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/api/helpers tests
git commit -m "feat(streaming): grounding_started event, journaled for resume"
```

---

### Task 6: Later turns see the grounding verdicts

**Files:**
- Modify: `src/agent/history.py:25-35,309-325`, `src/agent/message_content.py:135-150`
- Test: `tests/unit/test_history.py` (or the file covering `enrich_history`: `grep -ln "enrich_history" tests/unit`)

**Interfaces:**
- Consumes: `Message.annotations` (Task 4), `format_grounding_context` (Task 2).
- Produces: `MessageMetadata["grounding"]: str | None`; `MSG_CONTEXT` JSON key `"grounding"`.

- [ ] **Step 1: Failing test**

```python
def test_assistant_history_carries_the_grounding_entry() -> None:
    msg = _assistant_message(  # use the file's existing Message factory
        content="PřepiServis vyřídí přepis za 24–48 hodin.",
        annotations=[{"type": "claim", "verdict": "not_found", "quote": "PřepiServis", "reason": "Není ve zdrojích."}],
    )

    [enriched] = enrich_history([msg])

    assert enriched["metadata"]["grounding"] == "unsourced: PřepiServis (Není ve zdrojích.)"
    assert '"grounding":"unsourced: PřepiServis' in format_message_with_metadata(enriched)
    assert enriched["content"] == "PřepiServis vyřídí přepis za 24–48 hodin."
```

- [ ] **Step 2: Run to verify failure** → KeyError `grounding`.

- [ ] **Step 3: Implement**

`history.py`: add `grounding: str | None  # "unsourced: X (reason); contradicted: Y (...)" - claims not to repeat as fact` to `MessageMetadata`; in the assistant branch of `enrich_history`:

```python
            grounding = format_grounding_context(msg.annotations)
            if grounding:
                metadata["grounding"] = grounding
```

`message_content.py` after the `tool_outputs` block:

```python
    # Claims of that answer the grounding check found unsourced or
    # contradicted - a follow-up must not restate them as fact
    if metadata.get("grounding"):
        meta_dict["grounding"] = metadata["grounding"]
```

- [ ] **Step 4: Run** `.venv/bin/pytest $(grep -ln "enrich_history\|format_message_with_metadata" tests/unit) -q > $TMPDIR/t6.log 2>&1; echo $?` → 0.

- [ ] **Step 5: Commit** — `git commit -am "feat(agent): later turns see which claims had no source"`

---

### Task 7: Convert the markers written since Oct 2

**Files:**
- Create: `migrations/0058_convert_grounding_markers.py`
- Test: `tests/unit/test_migration_grounding_markers.py`

**Interfaces:**
- Produces: in the migration module, `convert_markers(content: str) -> tuple[str, list[dict[str, Any]]]` (clean content, legacy annotations) and the yoyo step `convert(conn)`.

- [ ] **Step 1: Failing tests** (fixtures shaped like the 7 prod messages; load the module with `importlib.util.spec_from_file_location("m0058", "migrations/0058_convert_grounding_markers.py")`)

```python
"""Migration 0058 turns inline grounding markers into legacy annotations."""

import importlib.util
import sqlite3
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def m() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0058", "migrations/0058_convert_grounding_markers.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("content", "clean", "quotes"),
    [
        (
            "pracoviště registru (Bohdalec, Jarov, Vyšehrad _(neověřeno)_).",
            "pracoviště registru (Bohdalec, Jarov, Vyšehrad).",
            ["Vyšehrad"],
        ),
        ("- **Rychlost:** 24–48 hodin _(neověřeno)_.", "- **Rychlost:** 24–48 hodin.", ["24–48 hodin"]),
        (
            "nesmí být starší než **1 rok** _(neověřeno)_ (od novely",
            "nesmí být starší než **1 rok** (od novely",
            ["1 rok"],
        ),
        ("Cena: Kolem 1 200–1 600 Kč _(neověřeno)_ za úkon", "Cena: Kolem 1 200–1 600 Kč za úkon", ["Kolem 1 200–1 600 Kč"]),
        ("Open daily 9-17 _(unverified)_\nBye", "Open daily 9-17\nBye", ["Open daily 9-17"]),
    ],
)
def test_convert_markers(m: ModuleType, content: str, clean: str, quotes: list[str]) -> None:
    new_content, anns = m.convert_markers(content)

    assert new_content == clean
    assert [a["quote"] for a in anns] == quotes
    assert all(a["verdict"] == "not_found" and a["type"] == "claim" for a in anns)
    for ann in anns:
        assert new_content.find(ann["prefix"] + ann["quote"]) >= 0


def test_step_updates_rows_and_search_index(m: ModuleType) -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE messages (id TEXT, role TEXT, content TEXT, annotations TEXT, grounding TEXT);
        CREATE VIRTUAL TABLE search_index USING fts5(user_id, conversation_id, message_id, type, title, content);
        INSERT INTO messages VALUES ('a', 'assistant', 'Cena 1 200 Kč _(neověřeno)_.', NULL, NULL);
        INSERT INTO messages VALUES ('b', 'assistant', 'Clean answer.', NULL, NULL);
        INSERT INTO search_index VALUES ('u', 'c', 'a', 'message', '', 'Cena 1 200 Kč _(neověřeno)_.');
        """
    )

    m.convert(conn)

    content, anns, grounding = conn.execute("SELECT content, annotations, grounding FROM messages WHERE id='a'").fetchone()
    assert content == "Cena 1 200 Kč." and '"legacy": true' in grounding and "1 200 Kč" in anns
    assert conn.execute("SELECT annotations FROM messages WHERE id='b'").fetchone() == (None,)
    assert conn.execute("SELECT content FROM search_index WHERE message_id='a'").fetchone() == ("Cena 1 200 Kč.",)
```

- [ ] **Step 2: Run to verify failure** → file not found.

- [ ] **Step 3: Implement the migration**

```python
"""Convert inline grounding markers (Oct 2-3 2026) to legacy annotations.

The grounding check used to write `_(neověřeno)_` / `_(unverified)_` into the
answer after each unsupported item. Annotations (0057) replace that: this
strips each marker and records the phrase right before it as a `not_found`
claim. The old markers carried no reason or source, so the converted
messages get `{"checked": true, "legacy": true}`. Self-contained on purpose:
later code changes must not change what this migration does.
"""

import json
import re
from typing import Any

from yoyo import step

__depends__ = {"0057_add_message_annotations"}

_MARKER = re.compile(r" ?_\((?:neověřeno|unverified)\)_")
# The quote runs back to the nearest of these (or the line start)
# A dash only as a spaced separator ("SPZ – text"), never inside "1 200–1 600"
_BOUNDARY = re.compile(r"(?:\*\*|[(:,;]|\s[–—]\s|^\s*(?:[-*+]|\d+\.)\s)", re.MULTILINE)
_TRAILING_EMPHASIS = re.compile(r"(\*\*|\*)$")
_MAX_QUOTE_CHARS = 60
_PREFIX_CHARS = 32


def _quote_before(text: str) -> tuple[str, int]:
    """(quote, start index in text) of the phrase that ends at the end of text."""
    end = len(text)
    emphasis = _TRAILING_EMPHASIS.search(text)
    if emphasis:
        end = emphasis.start()
    line_start = text.rfind("\n", 0, end) + 1
    start = line_start
    for match in _BOUNDARY.finditer(text, line_start, end):
        start = match.end()
    raw = text[start:end]
    quote = raw.strip()
    start += len(raw) - len(raw.lstrip())
    if len(quote) > _MAX_QUOTE_CHARS:  # no boundary nearby: keep the last words
        words = quote.split()[-3:]
        quote = " ".join(words)
        start = end - len(quote)
    return quote, start


def convert_markers(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Content without markers, and one legacy annotation per marker."""
    out = ""
    annotations: list[dict[str, Any]] = []
    pos = 0
    for match in _MARKER.finditer(content):
        out += content[pos : match.start()]
        pos = match.end()
        quote, start = _quote_before(out)
        if quote:
            annotations.append(
                {
                    "type": "claim",
                    "verdict": "not_found",
                    "quote": quote,
                    "prefix": out[max(0, start - _PREFIX_CHARS) : start],
                }
            )
    out += content[pos:]
    return out, annotations


def convert(conn: Any) -> None:
    rows = conn.execute(
        "SELECT id, content FROM messages WHERE role = 'assistant' "
        "AND (content LIKE '%(neověřeno)_%' OR content LIKE '%(unverified)_%')"
    ).fetchall()
    for msg_id, content in rows:
        clean, annotations = convert_markers(content)
        conn.execute(
            "UPDATE messages SET content = ?, annotations = ?, grounding = ? WHERE id = ?",
            (
                clean,
                json.dumps(annotations, ensure_ascii=False) if annotations else None,
                json.dumps({"checked": True, "legacy": True}),
                msg_id,
            ),
        )
        # search_index has insert/delete triggers only
        conn.execute(
            "UPDATE search_index SET content = ? WHERE message_id = ? AND type = 'message'",
            (clean, msg_id),
        )
    conn.commit()


steps = [step(convert)]  # no rollback: the old marker text is not worth restoring
```

- [ ] **Step 4: Run** `.venv/bin/pytest tests/unit/test_migration_grounding_markers.py -q > $TMPDIR/t7.log 2>&1; echo $?` → 0. If a parametrized case fails, fix `_quote_before`, not the expectation — the expectations are the 7 prod shapes.

- [ ] **Step 5: Rehearse on a copy of the prod database (read-only source)**

```bash
scp "$PROD_HOST:src/moneypenny/chatbot.db" "$TMPDIR/prod-copy.db"   # PROD_HOST from private memory, never written to the repo
.venv/bin/python - "$TMPDIR/prod-copy.db" <<'EOF'
import sqlite3, sys
from yoyo import get_backend, read_migrations
backend = get_backend(f"sqlite:///{sys.argv[1]}")
with backend.lock():
    backend.apply_migrations(backend.to_apply(read_migrations("migrations")))
conn = sqlite3.connect(sys.argv[1])
for row in conn.execute("SELECT id, annotations, substr(content,1,300) FROM messages WHERE grounding LIKE '%legacy%'"):
    print(row, "\n")
print("leftover markers:", conn.execute("SELECT COUNT(*) FROM messages WHERE content LIKE '%(neověřeno)_%' OR content LIKE '%(unverified)_%'").fetchone())
EOF
```

Expected: 7 rows listed, leftover markers `(0,)`. **Show the user every converted row's quotes before merging.** Delete `$TMPDIR/prod-copy.db` afterwards.

- [ ] **Step 6: Commit**

```bash
git add migrations/0058_convert_grounding_markers.py tests/unit/test_migration_grounding_markers.py
git commit -m "feat(db): convert inline grounding markers to legacy annotations"
```

---

### Task 8: Anchor claims in rendered markdown; drop the badge

**Files:**
- Create: `web/src/components/messages/annotations.ts`, `web/src/styles/components/grounding.css`
- Modify: `web/src/types/api.ts:86-101`, `web/src/utils/markdown.ts:145-152`, `web/src/constants.ts:38-46`, `web/src/core/file-actions.ts:85-86`, `web/src/styles/components/messages.css:1703-1716`, `web/src/styles/main.css:33`, `web/src/styles/variables.css`
- Test: `web/tests/unit/annotations.test.ts`; update `web/tests/unit/markdown.test.ts`, `web/tests/unit/copy-message.test.ts`

**Interfaces:**
- Produces:
  - `types/api.ts`: `export type ClaimVerdict = 'supported' | 'partial' | 'not_found' | 'contradicted';` `export interface ClaimAnnotation { type: 'claim'; verdict: ClaimVerdict; quote: string; prefix?: string; reason?: string; source?: number; source_quote?: string }` `export interface GroundingSummary { checked: boolean; source_count?: number; legacy?: boolean }`; `Message.annotations?: ClaimAnnotation[]; Message.grounding?: GroundingSummary;`
  - `applyAnnotations(contentEl: HTMLElement, annotations: ClaimAnnotation[]): Set<number>` (indexes that were anchored); `getMessageAnnotations(messageEl: Element): ClaimAnnotation[] | undefined`; `rememberAnnotations(messageEl: Element, annotations: ClaimAnnotation[], grounding?: GroundingSummary): void`; `getMessageGrounding(messageEl: Element): GroundingSummary | undefined`.
  - DOM: `<span class="claim claim--{verdict}" data-claim="{i}" tabindex="0" role="button">` for non-supported claims; `<sup class="claim-cite" data-claim="{i}" tabindex="0" role="button">{n}</sup>` after supported claims with a source.

- [ ] **Step 1: Failing tests** (`web/tests/unit/annotations.test.ts`, jsdom like the other unit tests)

```ts
import { describe, expect, it } from 'vitest';
import { applyAnnotations } from '@/components/messages/annotations';
import { renderMarkdown } from '@/utils/markdown';
import type { ClaimAnnotation } from '@/types/api';

function render(md: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message-content';
  el.innerHTML = renderMarkdown(md);
  return el;
}

const claim = (over: Partial<ClaimAnnotation>): ClaimAnnotation => ({
  type: 'claim',
  verdict: 'not_found',
  quote: '',
  ...over,
});

describe('applyAnnotations', () => {
  it('underlines a not_found claim', () => {
    const el = render('Rychlost: 24–48 hodin.');
    applyAnnotations(el, [claim({ quote: '24–48 hodin' })]);
    const span = el.querySelector('.claim')!;
    expect(span.textContent).toBe('24–48 hodin');
    expect(span.classList.contains('claim--not_found')).toBe(true);
  });

  it('anchors a quote written with markdown emphasis and links', () => {
    const el = render('**SPZ Služby** ([spzsluzby.cz](https://spzsluzby.cz)) a `registr-vozidel.cz`');
    const anchored = applyAnnotations(el, [
      claim({ quote: '**SPZ Služby**' }),
      claim({ quote: '[spzsluzby.cz](https://spzsluzby.cz)' }),
    ]);
    expect([...anchored]).toEqual([0, 1]);
    expect([...el.querySelectorAll('.claim')].map((s) => s.textContent)).toEqual(['SPZ Služby', 'spzsluzby.cz']);
  });

  it('spans a quote across bold boundaries', () => {
    const el = render('nesmí být starší než **1 rok** od novely');
    applyAnnotations(el, [claim({ quote: 'než **1 rok** od' })]);
    const text = [...el.querySelectorAll('.claim[data-claim="0"]')].map((s) => s.textContent).join('');
    expect(text).toBe('než 1 rok od');
  });

  it('picks the occurrence that matches the prefix', () => {
    const el = render('A: 1 590 Kč + 800 Kč. B: 1 200 Kč + 800 Kč.');
    applyAnnotations(el, [claim({ quote: '800 Kč', prefix: 'B: 1 200 Kč + ' })]);
    const span = el.querySelector('.claim')!;
    expect(span.previousSibling?.textContent?.endsWith('1 200 Kč + ')).toBe(true);
  });

  it('adds a source number after a supported claim instead of an underline', () => {
    const el = render('Kurýr vyzvedne doklady.');
    applyAnnotations(el, [claim({ quote: 'Kurýr vyzvedne doklady', verdict: 'supported', source: 2 })]);
    expect(el.querySelector('.claim')).toBeNull();
    expect(el.querySelector('sup.claim-cite')!.textContent).toBe('2');
  });

  it('never anchors inside code blocks and skips missing quotes', () => {
    const el = render('```\nVyšehrad\n```\nOther text');
    const anchored = applyAnnotations(el, [claim({ quote: 'Vyšehrad' }), claim({ quote: 'Nowhere' })]);
    expect(anchored.size).toBe(0);
    expect(el.querySelector('.claim')).toBeNull();
  });
});
```

In `markdown.test.ts` replace the badge tests with: `renderMarkdown('a _(neověřeno)_')` renders `<em>(neověřeno)</em>` (plain italics — markers are gone from the data). In `copy-message.test.ts` replace the badge copy test with: a message containing `.claim` spans and `sup.claim-cite` copies as plain text **without** the source numbers (`"Kurýr vyzvedne doklady."`).

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/unit/annotations.test.ts > $TMPDIR/t8.log 2>&1; echo $?; tail -5 $TMPDIR/t8.log`
Expected: exit 1, cannot resolve `@/components/messages/annotations`.

- [ ] **Step 3: Implement `annotations.ts`**

```ts
/**
 * Grounding claims anchored in rendered markdown.
 *
 * The server stores each claim as a literal quote of the markdown source plus
 * the text just before it. The rendered text differs (emphasis, link syntax),
 * so both sides are normalised - markdown punctuation dropped, whitespace
 * collapsed - and the match is mapped back onto the DOM text nodes.
 * Spec: docs/superpowers/specs/2026-10-03-grounding-annotations-design.md
 */
import type { ClaimAnnotation, GroundingSummary } from '../../types/api';

const SKIP_SELECTOR = 'pre, code, .katex';
const MARKDOWN_SYNTAX = /\*\*|__|[*_`]|\]\([^)]*\)|[[\]]/g;

interface MessageGrounding {
  annotations: ClaimAnnotation[];
  grounding?: GroundingSummary;
}
const byMessage = new WeakMap<Element, MessageGrounding>();

export function rememberAnnotations(messageEl: Element, annotations: ClaimAnnotation[], grounding?: GroundingSummary): void {
  byMessage.set(messageEl, { annotations, grounding });
}
export function getMessageAnnotations(messageEl: Element): ClaimAnnotation[] | undefined {
  return byMessage.get(messageEl)?.annotations;
}
export function getMessageGrounding(messageEl: Element): GroundingSummary | undefined {
  return byMessage.get(messageEl)?.grounding;
}

/** Markdown source text as it reads once rendered, normalised for matching. */
function normaliseSource(text: string): string {
  return text.replace(MARKDOWN_SYNTAX, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

interface TextIndex {
  /** Normalised rendered text */
  text: string;
  /** For each char of `text`: [text node, offset in that node] */
  map: Array<[Text, number]>;
}

function indexText(root: HTMLElement): TextIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest(SKIP_SELECTOR) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let text = '';
  const map: Array<[Text, number]> = [];
  let lastWasSpace = true;
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const value = node.data;
    for (let i = 0; i < value.length; i++) {
      const isSpace = /\s/.test(value[i]);
      if (isSpace && lastWasSpace) continue;
      text += isSpace ? ' ' : value[i].toLowerCase();
      map.push([node, i]);
      lastWasSpace = isSpace;
    }
  }
  return { text, map };
}

function findOccurrence(index: TextIndex, quote: string, prefix: string): number {
  const starts: number[] = [];
  for (let at = index.text.indexOf(quote); at >= 0; at = index.text.indexOf(quote, at + 1)) starts.push(at);
  if (starts.length <= 1 || !prefix) return starts[0] ?? -1;
  return starts.find((at) => index.text.slice(0, at).trimEnd().endsWith(prefix.trimEnd())) ?? starts[0];
}

/** Wrap [start, end) of the index in spans, one per text node it crosses. */
function wrapRange(index: TextIndex, start: number, end: number, make: () => HTMLElement): HTMLElement | null {
  const segments = new Map<Text, [number, number]>();
  for (let i = start; i < end; i++) {
    const [node, offset] = index.map[i];
    const seg = segments.get(node);
    segments.set(node, seg ? [seg[0], offset + 1] : [offset, offset + 1]);
  }
  let last: HTMLElement | null = null;
  for (const [node, [from, to]] of segments) {
    const middle = node.splitText(from);
    middle.splitText(to - from);
    const span = make();
    middle.replaceWith(span);
    span.appendChild(middle);
    last = span;
  }
  return last;
}

function claimSpan(i: number, verdict: string): () => HTMLElement {
  return () => {
    const span = document.createElement('span');
    span.className = `claim claim--${verdict}`;
    span.dataset.claim = String(i);
    span.tabIndex = 0;
    span.setAttribute('role', 'button');
    return span;
  };
}

function citeSup(i: number, source: number): HTMLElement {
  const sup = document.createElement('sup');
  sup.className = 'claim-cite';
  sup.dataset.claim = String(i);
  sup.tabIndex = 0;
  sup.setAttribute('role', 'button');
  sup.textContent = String(source);
  return sup;
}

/** Anchor every claim it can find; returns the indexes that were anchored. */
export function applyAnnotations(contentEl: HTMLElement, annotations: ClaimAnnotation[]): Set<number> {
  const anchored = new Set<number>();
  annotations.forEach((ann, i) => {
    // Re-index per claim: wrapping splits text nodes
    const index = indexText(contentEl);
    const quote = normaliseSource(ann.quote);
    const at = quote ? findOccurrence(index, quote, normaliseSource(ann.prefix ?? '')) : -1;
    if (at < 0) return;
    const end = at + quote.length;
    if (ann.verdict === 'supported') {
      if (ann.source) {
        const [node, offset] = index.map[end - 1];
        const after = node.splitText(offset + 1);
        after.before(citeSup(i, ann.source));
      }
    } else {
      wrapRange(index, at, end, claimSpan(i, ann.verdict));
    }
    anchored.add(i);
  });
  return anchored;
}
```

- [ ] **Step 4: Remove the badge path**

- `markdown.ts`: delete the `em(token)` renderer override and the `GROUNDING_MARKERS` import.
- `constants.ts`: delete `GROUNDING_MARKERS` and its comment.
- `file-actions.ts:85-86`: replace the badge line with `clone.querySelectorAll('sup.claim-cite').forEach((el) => el.remove());` and comment `// Source numbers are UI, not text`.
- `messages.css`: delete the `.grounding-unverified` block.

- [ ] **Step 5: Styles**

`variables.css` (dark block, then the light block with its own values):

```css
    --claim-unsourced: rgba(245, 181, 68, 0.45);
    --claim-contradicted: rgba(240, 138, 122, 0.55);
    --claim-highlight: rgba(245, 181, 68, 0.12);
    --claim-heading-unsourced: var(--color-warning-400);
    --claim-heading-contradicted: #f08a7a;
```

Light theme: `--claim-unsourced: rgba(180, 120, 10, 0.5); --claim-contradicted: rgba(200, 70, 50, 0.55); --claim-highlight: rgba(245, 181, 68, 0.18); --claim-heading-unsourced: var(--color-warning-700); --claim-heading-contradicted: #b4432f;`

`web/src/styles/components/grounding.css` (import it in `main.css` right after `messages.css`):

```css
/* Grounding claims (components/messages/annotations.ts) - look "A1" */
.claim {
    text-decoration: underline dotted var(--claim-unsourced);
    text-decoration-thickness: 1px;
    text-underline-offset: 4px;
    cursor: pointer;
    border-radius: 3px;
}

.claim--contradicted {
    text-decoration-color: var(--claim-contradicted);
}

.claim:focus-visible,
.claim.claim--open,
.claim.claim--flash {
    background: var(--claim-highlight);
    outline: none;
}

.claim-cite {
    color: var(--text-muted);
    font-size: 0.68em;
    font-weight: 500;
    padding: 0 1px;
    margin-left: 1px;
    cursor: pointer;
}
```

- [ ] **Step 6: Types** — add `ClaimVerdict`, `ClaimAnnotation`, `GroundingSummary` and the two `Message` fields to `web/src/types/api.ts` as listed under Interfaces.

- [ ] **Step 7: Run** `cd web && npx vitest run tests/unit/annotations.test.ts tests/unit/markdown.test.ts tests/unit/copy-message.test.ts > $TMPDIR/t8.log 2>&1; echo $?` → 0.

- [ ] **Step 8: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): anchor grounding claims in rendered markdown; drop the badge"
```

---

### Task 9: Footer, and decorating every rendered message

**Files:**
- Create: `web/src/components/messages/grounding.ts`, `web/src/components/messages/grounding-strings.ts`
- Modify: `web/src/components/messages/render.ts` (`addMessageToUI`, assistant branch after `highlightAllCodeBlocks(content)`), `web/src/core/stream-done.ts` (`StreamDoneEvent`, `finalizeDoneBubble`, `doneContentToRender` comment), `web/src/core/stream-events.ts` (switch), `web/src/styles/components/grounding.css`
- Test: `web/tests/unit/grounding-footer.test.ts`, `web/tests/unit/stream-done.test.ts` (update)

**Interfaces:**
- Consumes: `applyAnnotations`, `rememberAnnotations` (Task 8); `Message.annotations` / `.grounding`.
- Produces:
  - `decorateGrounding(messageEl: HTMLElement, message: Pick<Message, 'annotations' | 'grounding' | 'language'>): void` — anchors claims, remembers them, renders/replaces the footer.
  - `showGroundingChecking(messageEl: HTMLElement, language?: string): void`
  - `footerText(annotations: ClaimAnnotation[], grounding: GroundingSummary, language?: string): string`
  - `groundingStrings(language?: string): GroundingStrings` with keys `checking`, `ofSourced(n, total)`, `unsourced(n)`, `contradicted(n)`, `partial(n)`, `headings: Record<ClaimVerdict, string>`, `legacyReason`, `lookUp`, `lookUpMessage(quote)`, `sheetTitle`, `sheetMeta(pages, sourced, total)`, `verdictLabels: Record<ClaimVerdict, string>`.
  - DOM: `<div class="grounding-footer" role="button" tabindex="0">` inserted right after `.message-content`; class `grounding-footer--checking` while checking; it is a button only when a claim is not supported.

- [ ] **Step 1: Failing tests**

```ts
import { describe, expect, it } from 'vitest';
import { decorateGrounding, footerText, showGroundingChecking } from '@/components/messages/grounding';
import type { ClaimAnnotation } from '@/types/api';

const anns = (...verdicts: ClaimAnnotation['verdict'][]): ClaimAnnotation[] =>
  verdicts.map((verdict, i) => ({ type: 'claim', verdict, quote: `q${i}` }));

function bubble(text: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-content-wrapper"><div class="message-content"><p>${text}</p></div></div>`;
  return el;
}

describe('footerText', () => {
  it('counts sourced of total and each problem kind (Czech)', () => {
    const text = footerText(anns('supported', 'supported', 'not_found', 'contradicted'), { checked: true, source_count: 3 }, 'cs');
    expect(text).toBe('2 z 4 tvrzení ze zdrojů · 1 bez zdroje · 1 jinak než zdroj');
  });

  it('omits zero parts and uses English otherwise', () => {
    expect(footerText(anns('supported', 'not_found'), { checked: true, source_count: 1 }, 'en')).toBe(
      '1 of 2 claims from sources · 1 without a source'
    );
  });

  it('legacy footer counts claims that were not anchored', () => {
    expect(footerText(anns('not_found', 'not_found', 'not_found'), { checked: true, legacy: true }, 'cs')).toBe('3 bez zdroje');
  });
});

describe('decorateGrounding', () => {
  it('adds a footer after the content and is a button only with problems', () => {
    const el = bubble('q0 and q1');
    decorateGrounding(el, { annotations: anns('supported', 'not_found'), grounding: { checked: true, source_count: 1 }, language: 'en' });
    const footer = el.querySelector('.message-content + .grounding-footer')!;
    expect(footer.getAttribute('role')).toBe('button');

    const clean = bubble('q0');
    decorateGrounding(clean, { annotations: anns('supported'), grounding: { checked: true, source_count: 1 }, language: 'en' });
    expect(clean.querySelector('.grounding-footer')!.getAttribute('role')).toBeNull();
  });

  it('addMessageToUI decorates server messages', async () => {
    const { addMessageToUI } = await import('@/components/messages');
    const container = document.createElement('div');
    container.id = 'messages';
    document.body.appendChild(container);
    addMessageToUI(
      {
        id: 'm1',
        role: 'assistant',
        content: 'PřepiServis vyřídí přepis.',
        created_at: '2026-10-03T08:00:00',
        language: 'cs',
        annotations: [{ type: 'claim', verdict: 'not_found', quote: 'PřepiServis' }],
        grounding: { checked: true, legacy: true },
      },
      container
    );
    expect(container.querySelector('.claim')!.textContent).toBe('PřepiServis');
    expect(container.querySelector('.grounding-footer')!.textContent).toBe('1 bez zdroje');
  });

  it('replaces the checking state and does nothing without annotations', () => {
    const el = bubble('q0');
    showGroundingChecking(el, 'cs');
    expect(el.querySelector('.grounding-footer--checking')!.textContent).toBe('Ověřuji proti zdrojům…');
    decorateGrounding(el, { annotations: [], grounding: undefined, language: 'cs' });
    expect(el.querySelector('.grounding-footer')).toBeNull();
  });
});
```

Add to `stream-done.test.ts`: `handleStreamDone` with an event carrying `annotations` renders `.grounding-footer` on the bubble (mirror the file's existing done-event test setup); and update the `doneContentToRender` test description (no grounding case any more — only lost tokens).

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run tests/unit/grounding-footer.test.ts > $TMPDIR/t9.log 2>&1; echo $?` → 1.

- [ ] **Step 3: `grounding-strings.ts`**

```ts
/** UI text for grounding annotations, in the answer's language (cs, else en). */
import type { ClaimVerdict } from '../../types/api';

export interface GroundingStrings {
  checking: string;
  ofSourced: (n: number, total: number) => string;
  unsourced: (n: number) => string;
  partial: (n: number) => string;
  contradicted: (n: number) => string;
  headings: Record<Exclude<ClaimVerdict, 'supported'>, string>;
  verdictLabels: Record<ClaimVerdict, string>;
  legacyReason: string;
  lookUp: string;
  lookUpMessage: (quote: string) => string;
  sheetTitle: string;
  sheetMeta: (pages: number, sourced: number, total: number) => string;
}

const CS: GroundingStrings = {
  checking: 'Ověřuji proti zdrojům…',
  ofSourced: (n, total) => `${n} z ${total} tvrzení ze zdrojů`,
  unsourced: (n) => `${n} bez zdroje`,
  partial: (n) => `${n} částečně`,
  contradicted: (n) => `${n} jinak než zdroj`,
  headings: { not_found: 'Ve zdrojích není', partial: 'Částečně ve zdrojích', contradicted: 'Zdroj uvádí jinak' },
  verdictLabels: { supported: 'ZDROJ', partial: 'ČÁSTEČNĚ', not_found: 'BEZ ZDROJE', contradicted: 'JINAK' },
  legacyReason: 'Nenašel jsem to ve stránkách, které jsem při odpovědi četl.',
  lookUp: 'Dohledat',
  lookUpMessage: (quote) => `Dohledej a ověř: ${quote}`,
  sheetTitle: 'Kontrola zdrojů',
  sheetMeta: (pages, sourced, total) => `Porovnáno se ${pages} stránkami · ${sourced} z ${total} podloženo`,
};

const EN: GroundingStrings = {
  checking: 'Checking against sources…',
  ofSourced: (n, total) => `${n} of ${total} claims from sources`,
  unsourced: (n) => `${n} without a source`,
  partial: (n) => `${n} partly sourced`,
  contradicted: (n) => `${n} differ from the source`,
  headings: { not_found: 'Not in the sources', partial: 'Partly in the sources', contradicted: 'The source says otherwise' },
  verdictLabels: { supported: 'SOURCE', partial: 'PARTLY', not_found: 'NO SOURCE', contradicted: 'DIFFERS' },
  legacyReason: 'Not found in the pages I read for this answer.',
  lookUp: 'Look it up',
  lookUpMessage: (quote) => `Look up and verify: ${quote}`,
  sheetTitle: 'Source check',
  sheetMeta: (pages, sourced, total) => `Compared with ${pages} pages · ${sourced} of ${total} sourced`,
};

export function groundingStrings(language?: string): GroundingStrings {
  return language === 'cs' ? CS : EN;
}
```

(Before writing `sheetMeta`, check the Czech instrumental for 1 page: `1 stránkou` — use `pages === 1 ? '1 stránkou' : \`${pages} stránkami\``, and English `1 page` vs `N pages`.)

- [ ] **Step 4: `grounding.ts`**

```ts
/** Footer and decoration for grounding-checked assistant messages. */
import type { ClaimAnnotation, GroundingSummary, Message } from '../../types/api';
import { applyAnnotations, rememberAnnotations } from './annotations';
import { groundingStrings } from './grounding-strings';

const FOOTER_CLASS = 'grounding-footer';

export function footerText(annotations: ClaimAnnotation[], grounding: GroundingSummary, language?: string): string {
  const s = groundingStrings(language);
  const count = (v: ClaimAnnotation['verdict']) => annotations.filter((a) => a.verdict === v).length;
  const parts: string[] = [];
  if (!grounding.legacy) parts.push(s.ofSourced(count('supported'), annotations.length));
  if (count('not_found')) parts.push(s.unsourced(count('not_found')));
  if (count('partial')) parts.push(s.partial(count('partial')));
  if (count('contradicted')) parts.push(s.contradicted(count('contradicted')));
  return parts.join(' · ');
}

function placeFooter(messageEl: HTMLElement): HTMLElement | null {
  const content = messageEl.querySelector('.message-content');
  if (!content) return null;
  messageEl.querySelector(`.${FOOTER_CLASS}`)?.remove();
  const footer = document.createElement('div');
  footer.className = FOOTER_CLASS;
  content.after(footer);
  return footer;
}

export function showGroundingChecking(messageEl: HTMLElement, language?: string): void {
  const footer = placeFooter(messageEl);
  if (!footer) return;
  footer.classList.add(`${FOOTER_CLASS}--checking`);
  footer.textContent = groundingStrings(language).checking;
}

export function decorateGrounding(
  messageEl: HTMLElement,
  message: Pick<Message, 'annotations' | 'grounding' | 'language'>
): void {
  const annotations = message.annotations ?? [];
  if (!annotations.length || !message.grounding) {
    messageEl.querySelector(`.${FOOTER_CLASS}`)?.remove();
    return;
  }
  const content = messageEl.querySelector<HTMLElement>('.message-content');
  if (content) applyAnnotations(content, annotations);
  rememberAnnotations(messageEl, annotations, message.grounding);
  const footer = placeFooter(messageEl);
  if (!footer) return;
  footer.textContent = footerText(annotations, message.grounding, message.language);
  if (annotations.some((a) => a.verdict !== 'supported')) {
    footer.setAttribute('role', 'button');
    footer.tabIndex = 0;
  }
}
```

CSS (append to `grounding.css`):

```css
.grounding-footer {
    margin-top: var(--space-2, 8px);
    padding-top: var(--space-2, 8px);
    border-top: 1px solid var(--border-light);
    font-size: var(--font-size-sm, 13px);
    color: var(--text-muted);
}

.grounding-footer[role='button'] {
    cursor: pointer;
}

.grounding-footer[role='button']::before {
    content: '⚠ ';
    color: var(--claim-heading-unsourced);
}

.grounding-footer--checking::after {
    content: '';
    animation: grounding-pulse 1.2s ease-in-out infinite;
}

@keyframes grounding-pulse {
    50% { opacity: 0.4; }
}
```

(Check the actual spacing/font tokens in `variables.css` and use those names; the fallbacks above only document the intended values.)

- [ ] **Step 5: Wire it in**

`render.ts`, assistant branch right after `highlightAllCodeBlocks(content);` — the footer needs `content` inside `messageEl`, so call it after `contentWrapper`/`content` are appended (at the end of `addMessageToUI`, before it returns, for assistant messages):

```ts
  if (message.role === 'assistant') decorateGrounding(messageEl, message);
```

`stream-done.ts`: add `annotations?: ClaimAnnotation[]; grounding?: GroundingSummary;` to `StreamDoneEvent`; at the end of `finalizeDoneBubble` (after `finalizeStreamingMessage`): `decorateGrounding(messageEl, { annotations: event.annotations, grounding: event.grounding, language: event.language });` and pass `annotations`/`grounding` into the `Message` object the done handler appends to the store (find it with `grep -n "appendMessage\|stopped_early" web/src/core/stream-done.ts`). Rewrite the `doneContentToRender` docstring: only lost tokens trigger a re-render now.

`stream-events.ts` switch:

```ts
    case 'grounding_started':
      // The verifier runs between the last token and done (~1 s). The reply's
      // language is only known at done, so use the previous reply's.
      if (isCurrentConversation) showGroundingChecking(state.messageEl, previousReplyLanguage(convId));
      break;
```

with, in the same file:

```ts
/** Language of the conversation's last saved assistant reply (for UI text before done). */
function previousReplyLanguage(convId: string): string | undefined {
  const messages = useStore.getState().getMessages(convId);
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant' && messages[i].language) return messages[i].language;
  }
  return undefined;
}
```

`done` then re-renders the footer in the reply's own language.

Batch path: `addMessageToUI` already decorates the reply (`toAssistantMessage` in `core/batch-send.ts` must copy `annotations` and `grounding` from the `ChatResponse` — add both lines).

- [ ] **Step 6: Run** `cd web && npx vitest run tests/unit/grounding-footer.test.ts tests/unit/stream-done.test.ts tests/unit/annotations.test.ts > $TMPDIR/t9.log 2>&1; echo $?` → 0; `npm run typecheck > $TMPDIR/tc.log 2>&1; echo $?` → 0.

- [ ] **Step 7: Commit** — `git add web && git commit -m "feat(web): grounding footer on streamed, batch and loaded messages"`

---

### Task 10: Claim card and "Dohledat"

**Files:**
- Create: `web/src/components/ClaimCard.ts`
- Modify: `web/src/main.ts` (init), `web/src/config.ts` (`CLAIM_CARD_HOVER_DELAY_MS = 250`), `web/src/styles/components/grounding.css`
- Test: `web/tests/component/claim-card.test.ts`

**Interfaces:**
- Consumes: `getMessageAnnotations`, `getMessageGrounding` (Task 8), `groundingStrings` (Task 9), `sendQuickText` (below).
- Produces: `initClaimCard(): void`; `openClaimCard(target: HTMLElement): void`; `closeClaimCard(): void`. Card DOM: `<div class="claim-card" role="dialog" id="claim-card">` appended to `document.body`, positioned under the target (clamped to the viewport, 16px gutter). Also `sendComposedText(text: string): Promise<void>` exported from `web/src/core/quick-actions.ts` (the textarea-fill-and-send part of `sendQuickAction`, which then calls it).

- [ ] **Step 1: Failing tests** (component test style as in `web/tests/component/`; mock `@/core/quick-actions`)

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/core/quick-actions', () => ({ sendComposedText: vi.fn() }));
import { sendComposedText } from '@/core/quick-actions';
import { initClaimCard } from '@/components/ClaimCard';
import { decorateGrounding } from '@/components/messages/grounding';

function setup(): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const msg = document.createElement('div');
  msg.className = 'message assistant';
  msg.innerHTML = '<div class="message-content-wrapper"><div class="message-content"><p>PřepiServis: rychlost 24–48 hodin. Kurýr.</p></div></div>';
  document.getElementById('messages')!.appendChild(msg);
  decorateGrounding(msg, {
    language: 'cs',
    grounding: { checked: true, source_count: 1 },
    annotations: [
      { type: 'claim', verdict: 'not_found', quote: 'rychlost 24–48 hodin', reason: 'Stránky popisují jen SPZ Služby.' },
      { type: 'claim', verdict: 'supported', quote: 'Kurýr', source: 1, source_quote: 'Kurýr vyzvedne' },
    ],
  });
  initClaimCard();
  return msg;
}

describe('ClaimCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('opens on click with heading, reason and Dohledat', () => {
    setup();
    (document.querySelector('.claim') as HTMLElement).click();
    const card = document.getElementById('claim-card')!;
    expect(card.querySelector('.claim-card__heading')!.textContent).toBe('Ve zdrojích není');
    expect(card.textContent).toContain('Stránky popisují jen SPZ Služby.');
    (card.querySelector('.claim-card__lookup') as HTMLButtonElement).click();
    expect(sendComposedText).toHaveBeenCalledWith('Dohledej a ověř: rychlost 24–48 hodin');
  });

  it('a source number shows the passage and no Dohledat', () => {
    setup();
    (document.querySelector('sup.claim-cite') as HTMLElement).click();
    const card = document.getElementById('claim-card')!;
    expect(card.querySelector('blockquote')!.textContent).toBe('„Kurýr vyzvedne“');
    expect(card.querySelector('.claim-card__lookup')).toBeNull();
  });

  it('closes on Escape and on an outside click', () => {
    setup();
    (document.querySelector('.claim') as HTMLElement).click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('claim-card')).toBeNull();
    (document.querySelector('.claim') as HTMLElement).click();
    document.body.click();
    expect(document.getElementById('claim-card')).toBeNull();
  });
});
```

The source-number card also shows the domain and title from the message's `sources` — read them from the store: `useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId)?.sources`. In the test the store has no message, so the card falls back to "Zdroj 1" (assert nothing about it).

- [ ] **Step 2: Run to verify failure** → cannot resolve `@/components/ClaimCard`.

- [ ] **Step 3: `quick-actions.ts`** — extract:

```ts
/** Put text in the composer and send it through the normal path. */
export async function sendComposedText(text: string): Promise<void> {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!textarea) return;
  textarea.value = text;
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sendMessage();
}
```

and make `sendQuickAction` call `await sendComposedText(text)` after its log line.

- [ ] **Step 4: `ClaimCard.ts`**

```ts
/**
 * Card for a grounding claim or source number: verdict, reason, the source
 * passage, and "Dohledat" (sends a targeted follow-up). One delegated handler
 * on #messages; hover opens on devices that hover, tap/click everywhere.
 */
import { CLAIM_CARD_HOVER_DELAY_MS } from '../config';
import { sendComposedText } from '../core/quick-actions';
import { useStore } from '../state/store';
import type { ClaimAnnotation, Source } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { getMessageAnnotations, getMessageGrounding } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';

const CARD_ID = 'claim-card';
const TARGET_SELECTOR = '.claim, .claim-cite';
const GUTTER_PX = 16;
let hoverTimer: number | undefined;
let openTarget: HTMLElement | null = null;

interface CardContext {
  ann: ClaimAnnotation;
  language?: string;
  legacy: boolean;
  source?: Source;
}

function contextFor(target: HTMLElement): CardContext | null {
  const messageEl = target.closest<HTMLElement>('.message');
  const index = Number(target.dataset.claim);
  const ann = messageEl ? getMessageAnnotations(messageEl)?.[index] : undefined;
  if (!messageEl || !ann) return null;
  const convId = useStore.getState().currentConversation?.id;
  const stored = convId ? useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId) : undefined;
  return {
    ann,
    language: stored?.language,
    legacy: Boolean(getMessageGrounding(messageEl)?.legacy),
    source: ann.source ? stored?.sources?.[ann.source - 1] : undefined,
  };
}

function sourceLine(ctx: CardContext): string {
  if (!ctx.ann.source) return '';
  const host = ctx.source ? new URL(ctx.source.url).hostname.replace(/^www\./, '') : `${ctx.ann.source}`;
  return `<span class="claim-card__source"><sup>${ctx.ann.source}</sup> ${escapeHtml(host)}</span>`;
}

function cardHtml(ctx: CardContext): string {
  const s = groundingStrings(ctx.language);
  const { ann } = ctx;
  const passage = ann.source_quote ? `<blockquote>„${escapeHtml(ann.source_quote)}“</blockquote>` : '';
  if (ann.verdict === 'supported') {
    const title = ctx.source ? ` <small>· ${escapeHtml(ctx.source.title)}</small>` : '';
    return `<div class="claim-card__heading claim-card__heading--cite">${sourceLine(ctx)}${title}</div>${passage}`;
  }
  const reason = ann.reason ?? (ctx.legacy ? s.legacyReason : '');
  return `
    <div class="claim-card__heading claim-card__heading--${ann.verdict}">${escapeHtml(s.headings[ann.verdict])}</div>
    ${reason ? `<p class="claim-card__reason">${escapeHtml(reason)}</p>` : ''}
    ${passage}${ann.verdict === 'contradicted' ? sourceLine(ctx) : ''}
    <button type="button" class="claim-card__lookup">${escapeHtml(s.lookUp)}</button>`;
}

function position(card: HTMLElement, target: HTMLElement): void {
  const rect = target.getBoundingClientRect();
  const width = Math.min(card.offsetWidth || 320, window.innerWidth - 2 * GUTTER_PX);
  const left = Math.min(Math.max(GUTTER_PX, rect.left), window.innerWidth - GUTTER_PX - width);
  card.style.left = `${left + window.scrollX}px`;
  card.style.top = `${rect.bottom + window.scrollY + 6}px`;
}

export function closeClaimCard(): void {
  document.getElementById(CARD_ID)?.remove();
  openTarget?.classList.remove('claim--open');
  openTarget?.removeAttribute('aria-describedby');
  openTarget = null;
}

export function openClaimCard(target: HTMLElement): void {
  const ctx = contextFor(target);
  closeClaimCard();
  if (!ctx) return;
  const card = document.createElement('div');
  card.id = CARD_ID;
  card.className = 'claim-card';
  card.setAttribute('role', 'dialog');
  card.innerHTML = cardHtml(ctx);
  card.querySelector('.claim-card__lookup')?.addEventListener('click', (e) => {
    e.stopPropagation();
    closeClaimCard();
    void sendComposedText(groundingStrings(ctx.language).lookUpMessage(ctx.ann.quote));
  });
  card.addEventListener('click', (e) => e.stopPropagation());
  document.body.appendChild(card);
  position(card, target);
  target.classList.add('claim--open');
  target.setAttribute('aria-describedby', CARD_ID);
  openTarget = target;
}

export function initClaimCard(): void {
  const messages = document.getElementById('messages');
  if (!messages) return;
  messages.addEventListener('click', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (!target) return;
    e.stopPropagation();
    if (target === openTarget) closeClaimCard();
    else openClaimCard(target);
  });
  messages.addEventListener('keydown', (e) => {
    const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
    if (target && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      openClaimCard(target);
    }
  });
  if (window.matchMedia('(hover: hover)').matches) {
    messages.addEventListener('mouseover', (e) => {
      const target = (e.target as Element).closest<HTMLElement>(TARGET_SELECTOR);
      window.clearTimeout(hoverTimer);
      if (target && target !== openTarget) {
        hoverTimer = window.setTimeout(() => openClaimCard(target), CLAIM_CARD_HOVER_DELAY_MS);
      }
    });
  }
  document.addEventListener('click', closeClaimCard);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeClaimCard();
  });
}
```

(Check that `escapeHtml` is exported from `web/src/utils/dom.ts`; `SourcesPopup.ts` imports it — use the same import.)

`web/src/config.ts`: `/** Hover delay before a grounding claim's card opens (desktop) */ export const CLAIM_CARD_HOVER_DELAY_MS = 250;`. `main.ts`: call `initClaimCard()` next to the other component inits (`grep -n "init.*Popup()" web/src/main.ts`).

CSS (append to `grounding.css`):

```css
.claim-card {
    position: absolute;
    z-index: 1000;
    width: min(320px, calc(100vw - 32px));
    padding: 10px 12px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-light);
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    font-size: 13px;
    line-height: 1.45;
    color: var(--text-primary);
}

.claim-card__heading { font-weight: 600; }
.claim-card__heading--not_found,
.claim-card__heading--partial { color: var(--claim-heading-unsourced); }
.claim-card__heading--contradicted { color: var(--claim-heading-contradicted); }
.claim-card__heading small { font-weight: 400; color: var(--text-muted); }
.claim-card__reason { margin: 4px 0 0; color: var(--text-secondary); }
.claim-card blockquote { margin: 8px 0 0; padding: 2px 0 2px 10px; border-left: 2px solid var(--border-light); font-size: 12.5px; }
.claim-card__source { display: block; margin-top: 6px; font-size: 12px; color: var(--text-muted); }
.claim-card__source sup { color: var(--text-muted); }
.claim-card__lookup {
    margin-top: 9px;
    padding: 3px 10px;
    border: 0;
    border-radius: 8px;
    background: var(--accent-muted);
    color: var(--accent-hover);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}
```

- [ ] **Step 5: Run** `cd web && npx vitest run tests/component/claim-card.test.ts > $TMPDIR/t10.log 2>&1; echo $?` → 0; plus `npx vitest run tests/unit/quick-actions*.test.ts` if it exists → 0.

- [ ] **Step 6: Commit** — `git add web && git commit -m "feat(web): claim card with source passage and Dohledat"`

---

### Task 11: Claims list

**Files:**
- Create: `web/src/components/ClaimsSheet.ts`
- Modify: `web/src/main.ts`, `web/src/config.ts` (`CLAIM_FLASH_MS = 1600`), `web/src/styles/components/grounding.css`
- Test: `web/tests/component/claims-sheet.test.ts`

**Interfaces:**
- Consumes: `getMessageAnnotations`, `getMessageGrounding`, `groundingStrings`, `closeClaimCard`.
- Produces: `initClaimsSheet(): void`; `openClaimsSheet(messageEl: HTMLElement): void`; `closeClaimsSheet(): void`. DOM: `<div class="claims-sheet" id="claims-sheet" role="dialog" aria-modal="true">` with a `.claims-sheet__backdrop`; rows `<button class="claims-sheet__row" data-claim="i">`. Below 768px it is a bottom sheet (`.claims-sheet--sheet`), otherwise a popover anchored above the footer (`.claims-sheet--popover`).

- [ ] **Step 1: Failing tests**

```ts
import { describe, expect, it, vi } from 'vitest';
import { initClaimsSheet } from '@/components/ClaimsSheet';
import { decorateGrounding } from '@/components/messages/grounding';

function setup(): HTMLElement {
  document.body.innerHTML = '<div id="messages"></div>';
  const msg = document.createElement('div');
  msg.className = 'message assistant';
  msg.innerHTML = '<div class="message-content-wrapper"><div class="message-content"><p>A je dobré. B stojí 1 200 Kč. C zavírá v 18:00.</p></div></div>';
  document.getElementById('messages')!.appendChild(msg);
  decorateGrounding(msg, {
    language: 'cs',
    grounding: { checked: true, source_count: 3 },
    annotations: [
      { type: 'claim', verdict: 'supported', quote: 'A je dobré', source: 1, source_quote: 'A' },
      { type: 'claim', verdict: 'not_found', quote: 'C zavírá v 18:00', reason: 'Není.' },
      { type: 'claim', verdict: 'contradicted', quote: 'B stojí 1 200 Kč', reason: 'Zdroj: 1 590 Kč' },
    ],
  });
  initClaimsSheet();
  return msg;
}

describe('ClaimsSheet', () => {
  it('opens from the footer with rows ordered by severity', () => {
    setup();
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    const rows = [...document.querySelectorAll('.claims-sheet__row .claims-sheet__quote')].map((r) => r.textContent);
    expect(rows).toEqual(['B stojí 1 200 Kč', 'C zavírá v 18:00', 'A je dobré']);
    expect(document.querySelector('.claims-sheet__meta')!.textContent).toBe('Porovnáno se 3 stránkami · 1 z 3 podloženo');
  });

  it('a row closes the sheet, scrolls to the claim and flashes it', () => {
    vi.useFakeTimers();
    setup();
    const target = document.querySelector('.claim--contradicted') as HTMLElement;
    target.scrollIntoView = vi.fn();
    (document.querySelector('.grounding-footer') as HTMLElement).click();
    (document.querySelector('.claims-sheet__row') as HTMLElement).click();
    expect(document.getElementById('claims-sheet')).toBeNull();
    expect(target.scrollIntoView).toHaveBeenCalled();
    expect(target.classList.contains('claim--flash')).toBe(true);
    vi.runAllTimers();
    expect(target.classList.contains('claim--flash')).toBe(false);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run to verify failure** → cannot resolve `@/components/ClaimsSheet`.

- [ ] **Step 3: Implement `ClaimsSheet.ts`**

```ts
/**
 * Every claim of one answer, problems first. Bottom sheet on mobile, popover
 * on desktop; a row scrolls to the claim in the answer and flashes it.
 */
import { CLAIM_FLASH_MS } from '../config';
import { MOBILE_BREAKPOINT_PX } from '../constants';
import { useStore } from '../state/store';
import type { ClaimAnnotation, ClaimVerdict } from '../types/api';
import { escapeHtml } from '../utils/dom';
import { closeClaimCard } from './ClaimCard';
import { getMessageAnnotations, getMessageGrounding } from './messages/annotations';
import { groundingStrings } from './messages/grounding-strings';

const SHEET_ID = 'claims-sheet';
const ORDER: ClaimVerdict[] = ['contradicted', 'not_found', 'partial', 'supported'];

function languageOf(messageEl: HTMLElement): string | undefined {
  const convId = useStore.getState().currentConversation?.id;
  return convId
    ? useStore.getState().getMessages(convId).find((m) => m.id === messageEl.dataset.messageId)?.language
    : undefined;
}

function rowHtml(ann: ClaimAnnotation, index: number, language?: string): string {
  const s = groundingStrings(language);
  const detail = ann.verdict === 'supported' ? (ann.source ? `${ann.source}` : '') : (ann.reason ?? '');
  return `<button type="button" class="claims-sheet__row" data-claim="${index}">
      <span class="claims-sheet__verdict claims-sheet__verdict--${ann.verdict}">${escapeHtml(s.verdictLabels[ann.verdict])}</span>
      <span class="claims-sheet__quote">${escapeHtml(ann.quote)}</span>
      ${detail ? `<span class="claims-sheet__detail">${escapeHtml(detail)}</span>` : ''}
    </button>`;
}

export function closeClaimsSheet(): void {
  document.getElementById(SHEET_ID)?.remove();
}

function flash(target: HTMLElement): void {
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.add('claim--flash');
  window.setTimeout(() => target.classList.remove('claim--flash'), CLAIM_FLASH_MS);
}

export function openClaimsSheet(messageEl: HTMLElement): void {
  const annotations = getMessageAnnotations(messageEl);
  const grounding = getMessageGrounding(messageEl);
  if (!annotations?.length || !grounding) return;
  closeClaimCard();
  closeClaimsSheet();
  const language = languageOf(messageEl);
  const s = groundingStrings(language);
  const sourced = annotations.filter((a) => a.verdict === 'supported').length;
  const rows = annotations
    .map((ann, i) => ({ ann, i }))
    .sort((a, b) => ORDER.indexOf(a.ann.verdict) - ORDER.indexOf(b.ann.verdict) || a.i - b.i);
  const mobile = window.innerWidth < MOBILE_BREAKPOINT_PX;
  const sheet = document.createElement('div');
  sheet.id = SHEET_ID;
  sheet.className = `claims-sheet ${mobile ? 'claims-sheet--sheet' : 'claims-sheet--popover'}`;
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-modal', 'true');
  const meta = grounding.legacy ? '' : `<p class="claims-sheet__meta">${escapeHtml(s.sheetMeta(grounding.source_count ?? 0, sourced, annotations.length))}</p>`;
  sheet.innerHTML = `<div class="claims-sheet__backdrop"></div>
    <div class="claims-sheet__panel">
      ${mobile ? '<div class="claims-sheet__grab"></div>' : ''}
      <h4 class="claims-sheet__title">${escapeHtml(s.sheetTitle)}</h4>${meta}
      <div class="claims-sheet__rows">${rows.map(({ ann, i }) => rowHtml(ann, i, language)).join('')}</div>
    </div>`;
  sheet.querySelector('.claims-sheet__backdrop')!.addEventListener('click', closeClaimsSheet);
  sheet.addEventListener('click', (e) => {
    e.stopPropagation();
    const row = (e.target as Element).closest<HTMLElement>('.claims-sheet__row');
    if (!row) return;
    closeClaimsSheet();
    const target = messageEl.querySelector<HTMLElement>(`[data-claim="${row.dataset.claim}"]`);
    if (target) flash(target);
  });
  document.body.appendChild(sheet);
  if (!mobile) {
    const footer = messageEl.querySelector('.grounding-footer')!.getBoundingClientRect();
    const panel = sheet.querySelector<HTMLElement>('.claims-sheet__panel')!;
    panel.style.left = `${footer.left + window.scrollX}px`;
    panel.style.top = `${Math.max(16, footer.top + window.scrollY - panel.offsetHeight - 8)}px`;
  }
}

export function initClaimsSheet(): void {
  const messages = document.getElementById('messages');
  if (!messages) return;
  messages.addEventListener('click', (e) => {
    const footer = (e.target as Element).closest<HTMLElement>('.grounding-footer[role="button"]');
    if (!footer) return;
    e.stopPropagation();
    const messageEl = footer.closest<HTMLElement>('.message');
    if (messageEl) openClaimsSheet(messageEl);
  });
  messages.addEventListener('keydown', (e) => {
    const footer = (e.target as Element).closest<HTMLElement>('.grounding-footer[role="button"]');
    if (footer && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      footer.click();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeClaimsSheet();
  });
}
```

Check the breakpoint constant's real name: `grep -rn "768" web/src/constants.ts web/src/config.ts`; use it (add `MOBILE_BREAKPOINT_PX = 768` to `constants.ts` only if none exists). `config.ts`: `/** How long a claim stays highlighted after jumping to it from the claims list */ export const CLAIM_FLASH_MS = 1600;`. `main.ts`: `initClaimsSheet()` next to `initClaimCard()`.

CSS (append):

```css
.claims-sheet__backdrop { position: fixed; inset: 0; z-index: 999; background: rgba(0, 0, 0, 0.35); }
.claims-sheet--popover .claims-sheet__backdrop { background: transparent; }
.claims-sheet__panel {
    position: absolute;
    z-index: 1000;
    width: min(380px, calc(100vw - 32px));
    max-height: 60vh;
    overflow-y: auto;
    padding: 10px 14px 14px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-light);
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.claims-sheet--sheet .claims-sheet__panel {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    width: auto;
    max-height: 70vh;
    border-radius: 16px 16px 0 0;
    padding-bottom: calc(14px + env(safe-area-inset-bottom));
}
.claims-sheet__grab { width: 36px; height: 4px; margin: 0 auto 10px; border-radius: 4px; background: var(--border); }
.claims-sheet__title { margin: 0 0 2px; font-size: 14px; }
.claims-sheet__meta { margin: 0 0 8px; font-size: 12px; color: var(--text-muted); }
.claims-sheet__row {
    display: block;
    width: 100%;
    padding: 7px 0;
    border: 0;
    border-top: 1px solid var(--border-light);
    background: none;
    color: var(--text-primary);
    font: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
}
.claims-sheet__verdict { margin-right: 6px; font-size: 11px; font-weight: 600; }
.claims-sheet__verdict--not_found,
.claims-sheet__verdict--partial { color: var(--claim-heading-unsourced); }
.claims-sheet__verdict--contradicted { color: var(--claim-heading-contradicted); }
.claims-sheet__verdict--supported { color: var(--text-muted); }
.claims-sheet__quote { font-weight: 600; }
.claims-sheet__detail { display: block; font-size: 12px; color: var(--text-muted); }
```

- [ ] **Step 4: Run** `cd web && npx vitest run tests/component/claims-sheet.test.ts tests/component/claim-card.test.ts > $TMPDIR/t11.log 2>&1; echo $?` → 0.

- [ ] **Step 5: Commit** — `git add web && git commit -m "feat(web): claims list as a bottom sheet / popover"`

---

### Task 12: E2E hook, E2E tests, visual baselines

**Files:**
- Modify: `tests/e2e-server.py` (startup patch + `/test/set-grounding-result`)
- Create: `web/tests/e2e/grounding-annotations.spec.ts`, visual test in `web/tests/visual/` (follow an existing file there, e.g. `grep -ln "toHaveScreenshot" web/tests/visual | head -1`)

**Interfaces:**
- Consumes: `grounding_check.should_check` / `check_grounding` / `GroundingOutcome` (Task 3), all UI from Tasks 8-11.
- Produces: `POST /test/set-grounding-result {"annotations": [...], "summary": {...}}` (per test via `X-Test-Execution-Id`; `{}` resets).

- [ ] **Step 1: Server hook** (in `tests/e2e-server.py`, near `set_batch_delay`, and the patch near the other module patches at startup)

```python
        @test_bp.route("/test/set-grounding-result", methods=["POST"])
        def set_grounding_result() -> tuple[dict[str, Any], int]:
            """Make the (patched) grounding check return canned annotations."""
            MOCK_CONFIG["grounding_result"] = request.get_json(silent=True) or {}
            return {"status": "set"}, 200
```

```python
from src.agent import grounding_check as _grounding_check


def _mock_should_check(answer: str, result_messages: Any, stop_reason: str | None = None) -> bool:
    return bool(MOCK_CONFIG.get("grounding_result")) and not stop_reason


def _mock_check_grounding(
    answer: str, result_messages: Any, stop_reason: str | None = None
) -> "_grounding_check.GroundingOutcome":
    canned = MOCK_CONFIG.get("grounding_result") or {}
    if not canned or stop_reason:
        return _grounding_check.GroundingOutcome()
    return _grounding_check.GroundingOutcome(
        annotations=canned.get("annotations", []), summary=canned.get("summary"), usage=None
    )


_grounding_check.should_check = _mock_should_check  # type: ignore[assignment]
_grounding_check.check_grounding = _mock_check_grounding  # type: ignore[assignment]
```

Add `"grounding_result": {}` to the `MOCK_CONFIG` defaults dict (line ~116).

- [ ] **Step 2: E2E spec** (`web/tests/e2e/grounding-annotations.spec.ts`)

```ts
import { test, expect } from '../global-setup';

const ANNOTATIONS = {
  summary: { checked: true, source_count: 1 },
  annotations: [
    { type: 'claim', verdict: 'not_found', quote: 'mock response', prefix: 'This is a ', reason: 'Not in the pages I read.' },
    { type: 'claim', verdict: 'supported', quote: 'This is a', source: 1, source_quote: 'This is' },
  ],
};

for (const streaming of [true, false]) {
  test.describe(`Grounding annotations (${streaming ? 'stream' : 'batch'})`, () => {
    test.beforeEach(async ({ page, request }) => {
      await request.post('/test/set-grounding-result', { data: ANNOTATIONS });
      await page.goto('/');
      await page.waitForSelector('#new-chat-btn');
      const streamBtn = page.locator('#stream-btn');
      if ((await streamBtn.getAttribute('aria-pressed')) !== String(streaming)) await streamBtn.click();
      await page.click('#new-chat-btn');
      await page.fill('#message-input', 'Check my claims please');
      await page.click('#send-btn');
      await expect(page.locator('.grounding-footer')).toHaveText(/1 of 2 claims from sources · 1 without a source/, { timeout: 15000 });
    });

    test('underline opens a card; Dohledat sends a follow-up', async ({ page }) => {
      const claim = page.locator('.message.assistant .claim').first();
      await expect(claim).toHaveText('mock response');
      await claim.click();
      await expect(page.locator('#claim-card .claim-card__reason')).toHaveText('Not in the pages I read.');
      await page.locator('#claim-card .claim-card__lookup').click();
      await expect(page.locator('.message.user').last()).toContainText('Look up and verify: mock response');
    });

    test('footer opens the claims list; a row jumps to the claim', async ({ page }) => {
      await page.locator('.grounding-footer').click();
      await expect(page.locator('.claims-sheet__row')).toHaveCount(2);
      await page.locator('.claims-sheet__row').first().click();
      await expect(page.locator('#claims-sheet')).toHaveCount(0);
      await expect(page.locator('.claim.claim--flash')).toHaveCount(1);
    });

    test('annotations survive a reload', async ({ page }) => {
      await page.reload();
      await expect(page.locator('.message.assistant .claim')).toHaveText('mock response', { timeout: 15000 });
      await expect(page.locator('sup.claim-cite')).toHaveText('1');
    });
  });
}

test('claims list is a bottom sheet on mobile', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await request.post('/test/set-grounding-result', { data: ANNOTATIONS });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Mobile claims please');
  await page.click('#send-btn');
  await page.locator('.grounding-footer').click({ timeout: 15000 });
  await expect(page.locator('.claims-sheet--sheet .claims-sheet__panel')).toBeVisible();
  const box = await page.locator('.claims-sheet__panel').boundingBox();
  expect(box && box.y + box.height).toBeGreaterThan(800);
});
```

(Check the mock response wording in `tests/e2e-server.py` — tests elsewhere expect `This is a mock response to: <text>`; on mobile the new-chat button may sit in the sidebar — copy the mobile setup from `web/tests/e2e/mobile.spec.ts`.)

- [ ] **Step 3: Visual test** — one screenshot of an annotated assistant message with the card open, one of the mobile sheet, following the existing visual spec's setup and masking. Generate darwin baselines locally (`cd web && npx playwright test tests/visual/<file> --update-snapshots`), then Linux baselines via `/regen-baselines` after pushing the branch.

- [ ] **Step 4: Build and run**

```bash
make build > $TMPDIR/b.log 2>&1; echo "build $?"
cd web && caffeinate -i npx playwright test tests/e2e/grounding-annotations.spec.ts --reporter=line > $TMPDIR/e2e.log 2>&1; echo "e2e $?"; grep -E "passed|failed|flaky" $TMPDIR/e2e.log
```
Expected: `build 0`, `e2e 0`, all passed on chromium and webkit.

- [ ] **Step 5: Commit** — `git add tests/e2e-server.py web/tests && git commit -m "test(e2e): grounding annotations - card, Dohledat, claims list, reload, mobile"`

---

### Task 13: Evals judge the annotations

**Files:**
- Modify: `evals/run.py:540-565`, `evals/cases/cz_grounded_no_note.yaml`, `evals/cases/cz_trip_plan_precision.yaml`, `evals/cases/skill_product_where_to_buy.yaml`, `evals/cases/skill_trip_roadstop.yaml`
- Test: `tests/unit/test_eval_runner.py` (or the file testing `evals/run.py`: `grep -ln "parse_judge_response" tests`)

**Interfaces:**
- Consumes: `usage["grounding"]` from `chat_batch` (Task 3).
- Produces: `format_annotations_for_judge(grounding: dict[str, Any] | None) -> str` in `evals/run.py`.

- [ ] **Step 1: Failing test**

```python
from evals.run import format_annotations_for_judge


def test_judge_sees_the_annotations() -> None:
    text = format_annotations_for_judge(
        {
            "annotations": [
                {"verdict": "not_found", "quote": "VeloRama", "reason": "Not in sources."},
                {"verdict": "supported", "quote": "Bike Prague", "source": 1},
            ]
        }
    )

    assert text == (
        "\n\nGROUNDING ANNOTATIONS (shown to the user next to the answer):\n"
        '- "VeloRama": not_found - Not in sources.\n'
        '- "Bike Prague": supported (source 1)'
    )
    assert format_annotations_for_judge(None) == ""
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Implement** in `evals/run.py`:

```python
def format_annotations_for_judge(grounding: dict[str, Any] | None) -> str:
    """The grounding annotations as text: users see them beside the answer."""
    lines = []
    for ann in (grounding or {}).get("annotations") or []:
        detail = f" (source {ann['source']})" if ann.get("source") else ""
        reason = f" - {ann['reason']}" if ann.get("reason") else ""
        lines.append(f'- "{ann["quote"]}": {ann["verdict"]}{detail}{reason}')
    if not lines:
        return ""
    return "\n\nGROUNDING ANNOTATIONS (shown to the user next to the answer):\n" + "\n".join(lines)
```

and in the judge call: `response=(response + format_annotations_for_judge(usage.get("grounding")))[:8000]`.

- [ ] **Step 4: Rubrics** — replace marker wording. `cz_grounded_no_note`: "It FAILS if the grounding annotations mark the CNB rate (or any claim) as not_found, partial or contradicted: a single rate read from the CNB page is fully supported." `cz_trip_plan_precision`: "not_found annotations may appear only on specific businesses, prices, opening hours or event times — never on the plan's own times or on towns." `skill_product_where_to_buy` / `skill_trip_roadstop`: "...anything it could not confirm is annotated as not_found (or stated as unconfirmed in the text)." Read each file and keep the rest of the rubric intact.

- [ ] **Step 5: Run unit tests, then the grounding eval cases (costs money)**

```bash
.venv/bin/pytest $(grep -ln "parse_judge_response\|format_annotations_for_judge" tests) -q > $TMPDIR/t13.log 2>&1; echo $?
make eval CASES="cz_grounded_no_note cz_trip_plan_precision skill_product_where_to_buy skill_trip_roadstop" RUNS=3 > $TMPDIR/eval.log 2>&1; echo $?
```

(Check `make eval`'s real case/run selectors with `grep -n "^eval" -A8 Makefile`.) Expected: unit exit 0; eval pass rates `skill_product_where_to_buy` ≥ 4/5-equivalent (≥ 3/3 or report), `cz_grounded_no_note` passes. **Report the total USD cost** printed by the runner.

- [ ] **Step 6: Commit** — `git add evals tests && git commit -m "test(evals): judge reads grounding annotations"`

---

### Task 14: Docs, verification, merge

**Files:**
- Modify: `docs/features/` grounding page (find with `grep -rln "grounding" docs/features`), `docs/features/chat-and-streaming.md` (SSE events list, new message fields), `TODO.md` (the "Stale or invented facts" bullet: remove the parts this ships — the in-place marker trade-off review — keep the open items), `.env.example` (already done in Task 2)

- [ ] **Step 1: Docs** — run the `docs-updater` agent with: "Grounding annotations shipped (spec docs/superpowers/specs/2026-10-03-grounding-annotations-design.md, plan docs/superpowers/plans/2026-10-03-grounding-annotations.md). Update the grounding feature page (verdicts, numbered pages, validation rules, config keys, UI), the SSE event list (`grounding_started`), message fields (`annotations`, `grounding`), MSG_CONTEXT `grounding` key, and TODO.md. No infrastructure hostnames."

- [ ] **Step 2: Full verification**

```bash
make lint > $TMPDIR/lint.log 2>&1; echo "lint $?"
caffeinate -i make test-all > $TMPDIR/all.log 2>&1; echo "test-all $?"
```
Expected: `lint 0`, `test-all 0`. On failure read the log, fix, rerun — never judge through a pipe.

- [ ] **Step 3: Review** — invoke `superpowers:requesting-code-review` for the branch; address findings with `superpowers:receiving-code-review`.

- [ ] **Step 4: Merge and deploy (with the user)**

Show the user: the 7 converted messages from Task 7 Step 5, the eval results and cost, and a screenshot of the UI on desktop and mobile. After their go-ahead: merge `feat/grounding-annotations` into main (`git switch main && git merge --ff-only feat/grounding-annotations`), update the production `.env` keys renamed in Task 2 (per private memory: `.env` mirrors `.env.example`; restart, not reload, for env changes), push, deploy once (health-gated), and confirm the migration ran (`grounding LIKE '%legacy%'` count = 7, no leftover markers) on the production host.
