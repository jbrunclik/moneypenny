#!/usr/bin/env python3
"""Capture a case's canned web once, from the live (unmetered) search.

Canned web (evals/fake_web.py) needs pages that look like the real web -
for cases about real products, places and routes, the real pages. This
runs the case's queries once through the ddgs-only search, reads the top
results the way the research tool does (trimmed text, not HTML), and
writes them into the case as its ``web:`` block - replacing ``web: live``.
From then on every run of the case sees the same results, whatever the
model's own query wording (a recording replayed by query would not).

Review what it wrote: drop a page that is a cookie wall or off-topic, and
keep cases about TODAY's facts (who holds an office, today's rate) live.
Pages are trimmed (default 4 000 characters) and keep their source URLs.
Then run Prettier on the case (`make lint` checks evals/cases/*.yaml); it
only re-indents a few lines inside page text.

Usage:
    PYTHONPATH=. python evals/capture_web.py <case-id> "query one" ["query two" ...]

When ddgs returns ads or nothing (it throttles a laptop after many evals),
run ``capture()`` on the production host instead, against a copy of the
case file: the search router there uses the metered providers and counts
every search in production's own usage counters (a laptop run would bill
the family's quota where no counter sees it).
"""

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from src.utils.clock import local_today

CASES_DIR = Path(__file__).parent / "cases"
_LIVE_LINE = re.compile(r"^(# Interim[^\n]*\n)?web: live\n", re.MULTILINE)

Search = Callable[[str, int], list[dict[str, str]]]
Fetch = Callable[..., tuple[str | None, str | None]]


def _collect(
    queries: list[str], search: Search, fetch: Fetch, per_query: int, page_chars: int
) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    for query in queries:
        try:
            hits = search(query, per_query)
        except Exception as e:  # noqa: BLE001 - one empty query must not lose the rest
            print(f"  no results for {query!r}: {e}")
            continue
        for hit in hits:
            if hit["url"] not in {r["url"] for r in results}:
                results.append({k: str(hit.get(k, "")) for k in ("url", "title", "snippet")})
    pages: dict[str, str] = {}
    for hit in results:
        text, _error = fetch(hit["url"], max_chars=page_chars)
        if text and text.strip():
            pages[hit["url"]] = text.strip()[:page_chars]
    return {"results": results, "pages": pages}


def capture(
    path: Path,
    queries: list[str],
    *,
    search: Search | None = None,
    fetch: Fetch | None = None,
    per_query: int = 4,
    page_chars: int = 4000,
) -> dict[str, Any]:
    """Run the queries, read the hits and write the case's ``web:`` block."""
    if search is None or fetch is None:
        from src.agent.tools.web import fetch_page_text
        from src.services.search_provider import search_web

        search, fetch = search or search_web, fetch or fetch_page_text
    web = _collect(queries, search, fetch, per_query, page_chars)
    if not web["results"] or not web["pages"]:
        raise RuntimeError(f"{path.name}: nothing captured - the case is left as it was")
    block = yaml.safe_dump({"web": web}, allow_unicode=True, sort_keys=False, width=100)
    header = f"# Canned web captured {local_today().isoformat()} (evals/capture_web.py): {'; '.join(queries)}\n"
    text = path.read_text()
    text = _LIVE_LINE.sub("", text)
    path.write_text(text.rstrip("\n") + "\n" + header + block)
    return web


def main() -> int:
    from evals.run import isolate_environment

    isolate_environment()
    case_id, *queries = sys.argv[1:]
    web = capture(CASES_DIR / f"{case_id}.yaml", queries)
    print(f"{case_id}: {len(web['results'])} results, {len(web['pages'])} pages")
    for url, page in web["pages"].items():
        print(f"  {len(page):5d}  {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
