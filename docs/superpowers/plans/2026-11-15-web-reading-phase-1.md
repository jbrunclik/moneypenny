# Web Reading Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pages that answer 403/429 (and PDFs refused today) are read through Exa; research is faster; `fetch_url` can read past its cut, lists links, and reads JSON and feeds.

**Architecture:** A small Exa extract service (`src/services/page_extract.py`) with its own gate and fractional billing into Exa's usage counter; the fetch path in `src/agent/tools/web.py` calls it on 403/429 and for PDFs; research parallelises its searches and fetches with a short timeout.

**Tech Stack:** Python, httpx, lxml (already installed), trafilatura.

**Spec:** docs/superpowers/specs/2026-11-15-web-reading-design.md (phase 1 only; phase 2, Reddit, waits on Reddit's approval)

## Global Constraints

- New tunables are plain `Config` constants with units (no env vars, no `.env` changes): `WEB_EXTRACT_TIMEOUT_SECONDS = 15`, `WEB_EXTRACT_QUOTA_SHARE = 0.9`, `RESEARCH_FETCH_TIMEOUT_SECONDS = 15`, `FETCH_URL_MAX_LINKS = 40`.
- Exa usage unit: $0.007 (`EXA_SEARCH_UNIT_USD`); extract spend is billed by the response's `costDollars`, never a whole unit per page.
- Every fetched text stays wrapped by `wrap_untrusted_content`; `GROUNDING_DIRECTIVE` stays on results.
- Reddit URLs never go to Exa (it is refused there too).
- The public repo rule: no host names or infrastructure in tracked files.
- Gate per task: `make lint` + `make test`; TDD; commit by explicit paths. Tool descriptions change: `make prompt-snapshots` and commit the snapshots with the change.

## Review Focus

- A 403 page when Exa is over 90% of its quota, has no key, or its breaker is tripped: today's error, no Exa call (Task 1 test).
- Exa answering 402: the exhausted flag is set and search stops using Exa too; any other Exa failure leaves the search breaker untouched (Task 1 test).
- A redirect chain ending in 403: the fallback reads the original URL, still SSRF-validated (Task 2 test).
- `start` past the end of the text: a clear "nothing after character N" note, not an empty wrapper (Task 4 test).
- A research call where every search fails in parallel: the existing "All searches failed" error (Task 3 test).

---

### Task 1: Exa extract service

**Files:**
- Create: `src/services/page_extract.py`
- Modify: `src/config.py`, `src/services/search_provider.py` (expose what the gate needs, no behaviour change)
- Test: `tests/unit/test_page_extract.py`

**Interfaces:**
- Produces: `extract_available() -> bool`; `extract_page(url: str, max_chars: int) -> tuple[str | None, str | None]` (text, error) - text is Exa's plain page text cut at `max_chars`; `record_extract_cost(cost_usd: float) -> None`.

- [ ] Step 1: tests (patch `httpx.post` and the kv store via the test database) -
  - `extract_page` posts to `https://api.exa.ai/contents` with `{"urls": [url], "text": {"maxCharacters": max_chars}}`, timeout `WEB_EXTRACT_TIMEOUT_SECONDS`, and returns the text;
  - Exa's per-URL status not `success` (e.g. 403 `SOURCE_NOT_AVAILABLE`) -> `(None, error)`; timeout -> `(None, error)`;
  - 402 -> `(None, error)` and the exa exhausted flag is set (`_breaker_tripped("exa")` true); a 500 or timeout leaves `_breaker_tripped("exa")` false;
  - `extract_available()` false without a key, with the breaker tripped, or at usage >= 90% of `SEARCH_QUOTA_EXA_MONTHLY`;
  - billing: costs 0.001 x 7 -> exa usage +1 (not +7); 0.003 + 0.005 -> +1 once the sum passes 0.007.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; the fraction is a kv counter of micro-dollars per Exa billing period (`usage_key`-style key); whole units added with `_record_use("exa")` when `before // 7000 < after // 7000`.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `feat(web): an Exa page-extract service, billed into Exa's usage`.

### Task 2: The fetch fallback and PDFs through Exa

**Files:**
- Modify: `src/agent/tools/web.py` (`_fetch_response`, `fetch_page_text`, `fetch_url`), `src/agent/tools/research.py` (`_fetch_source`)
- Test: `tests/unit/test_web_fallback.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `_fetch_response(url: str, timeout: float | None = None) -> tuple[httpx.Response | None, str | None, int | None]` (the third value: the HTTP status of a failed fetch); `fetch_page_text(url, max_chars=None, timeout=None)`.

- [ ] Step 1: tests -
  - a direct 403 or 429 then Exa text -> `fetch_page_text` returns Exa's text; `fetch_url` returns it wrapped like an HTML page (untrusted markers, grounding directive);
  - a direct 404 or timeout -> no Exa call, today's error;
  - Exa fails -> "HTTP 403 when fetching X (also unavailable through the reading service)";
  - a `reddit.com` / `old.reddit.com` URL answering 403 -> no Exa call;
  - research: a URL whose path ends in `.pdf` goes to Exa without a direct fetch; a direct response of `application/pdf` switches to Exa;
  - `fetch_url`: a PDF with `Content-Length` over `FETCH_URL_MAX_FILE_SIZE_BYTES` is not downloaded (stream, check the header, close) and goes to Exa as text; a small PDF stays multimodal;
  - one "Page read via fallback" info line per fallback with `host`, `via="exa"`, `status` (`ok`/`failed`), `elapsed_ms`, `direct_status`, `cost_usd`.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; the body is read only after the size check (`client.send(request, stream=True)`); the fallback reads the URL the caller gave.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs - `docs/features/agent-tools.md` (fetch_url / research: the fallback, PDFs), `docs/regular-review.md` (fetch failure rate against 27%, fallbacks per week by outcome, Exa extract spend); commit `feat(web): read blocked pages and large PDFs through Exa`.

### Task 3: Faster research

**Files:**
- Modify: `src/agent/tools/research.py` (`_ranked_unique_urls`, `_fetch_source`, `run_research`), `src/config.py`
- Test: `tests/unit/test_research.py` (or the existing research tests)

- [ ] Step 1: tests - the searches run concurrently (two searches that each wait on a shared barrier both complete); rank interleaving and the failed-search count unchanged; every search failing -> "All searches failed"; each fetch is called with `timeout=RESEARCH_FETCH_TIMEOUT_SECONDS` (15); "research completed" carries integer `search_ms` and `fetch_ms`.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement with the same `contextvars.copy_context` pool pattern as `web_search`'s batch.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `perf(web): research searches in parallel; a page gets 15 s`.

### Task 4: Reading past the cut, and links

**Files:**
- Modify: `src/agent/tools/web.py` (`fetch_url`, `_html_result`, `_text_result`), `src/agent/tools/web_content.py` (a link extractor)
- Test: `tests/unit/test_fetch_url_continuation.py`

**Interfaces:**
- Produces: `fetch_url(url: str, start: int = 0)`; `extract_links(html: str, base_url: str, limit: int) -> list[tuple[str, str]]` (text, absolute URL).

- [ ] Step 1: tests -
  - a page longer than `HTML_TEXT_MAX_LENGTH` ends with "[Truncated at N of M characters - call fetch_url with start=N for more]";
  - `start=N` returns the text from N (and the same note when more is left);
  - `start` past the end -> "[Nothing after character N - the page has M characters]";
  - links: absolute, deduplicated, `javascript:`/`mailto:`/fragment-only dropped, at most 40, listed after the text as "Links:" lines `- text: url`; none -> no section.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; the text is extracted whole (up to the extractor's own cap), then sliced; the tool description gains one line about `start`.
- [ ] Step 4: tests pass; `make prompt-snapshots`; lint, test.
- [ ] Step 5: commit `feat(web): fetch_url reads past its cut and lists the page's links`.

### Task 5: JSON and feeds

**Files:**
- Modify: `src/agent/tools/web_content.py` (`content_type_category`), `src/agent/tools/web.py`
- Test: `tests/unit/test_web_content_types.py`

- [ ] Step 1: tests - `application/json`, `application/ld+json`, `application/xml`, `text/xml`, `application/rss+xml`, `application/atom+xml` are readable by `fetch_url` and `fetch_page_text`; JSON comes back pretty-printed (`indent=2`, non-ASCII kept), invalid JSON as-is; both within the text limits and the `start` slicing.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement as a new `"data"` category handled like text.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs - `docs/features/agent-tools.md`; TODO: the Web reading item keeps only what is left (search adapters' country/language/results) plus "Re-measure fetch failures ~Dec 1 2026" against the 27% baseline; commit `feat(web): read JSON and RSS/Atom feeds as text`.
