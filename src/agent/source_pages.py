"""The pages a turn read, numbered the way the user sees them.

One list feeds both the sources popup (title + URL) and the grounding
verifier (title + URL + text), so a claim's source number always points at
the same page in both places.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.content import extract_text_content

WEB_TOOL_NAMES = frozenset({"research", "web_search", "fetch_url", "browser"})
_MAX_READ_SOURCES = 10
_MAX_SEARCH_SOURCES = 5
# The date line fetched articles start with (src/agent/tools/page_date.py),
# after the untrusted-content header
_PUBLISHED = re.compile(r"^Published: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
_PUBLISHED_SEARCH_CHARS = 400


@dataclass(frozen=True)
class SourcePage:
    """One page the turn read (or one search result when nothing was read)."""

    title: str
    url: str
    text: str

    @property
    def published(self) -> str | None:
        """The article's publish date (YYYY-MM-DD), when its text states one."""
        match = _PUBLISHED.search(self.text[:_PUBLISHED_SEARCH_CHARS])
        return match.group(1) if match else None


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
                call_id = tc.get("id")
                if call_id:
                    calls[call_id] = (tc.get("name", ""), tc.get("args") or {})
    return calls


def _page(item: dict[str, Any], text: str) -> SourcePage | None:
    url = str(item.get("url") or item.get("href") or "")
    if not url:
        return None
    return SourcePage(str(item.get("title") or _title_from_url(url)), url, text)


def _research_snippets(data: dict[str, Any]) -> list[SourcePage]:
    """research's snippet-only results: failed fetches, then unfetched candidates.

    The model reads these too. Oct 2026: 3 of 5 fetches failed (403/429),
    among them a "complete Gyeon product guide", and the verifier - seeing
    only the 2 read pages, both about one rim coating - flagged every other
    Gyeon product in the answer as unsourced.
    """
    items = [s for s in data.get("sources") or [] if isinstance(s, dict) and "content" not in s]
    items += [u for u in data.get("unfetched") or [] if isinstance(u, dict)]
    return [p for item in items if (p := _page(item, str(item.get("snippet") or "")))]


def _read_and_searched(  # noqa: C901, PLR0912
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
            if name == "delegate_task":
                # The subagent's answer is evidence to check against, not KNOWN
                if data.get("result"):
                    loose.append(str(data["result"]))
            else:
                searched.append(_research_snippets(data))
        elif name == "fetch_url":
            url = args.get("url")
            failed = data is not None and bool(data.get("error"))
            if url and msg.content and not failed:
                read.append(
                    SourcePage(
                        _title_from_url(str(url)), str(url), extract_text_content(msg.content)
                    )
                )
        elif name == "browser" and data and data.get("success") and data.get("url"):
            page = _page(data, str(data.get("content") or ""))
            if page:
                read.append(page)
        elif name == "web_search" and data:
            searched.extend(
                [
                    p
                    for r in results
                    if isinstance(r, dict) and (p := _page(r, str(r.get("snippet") or "")))
                ]
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


def _newest_longest(pages: list[SourcePage], limit: int) -> list[SourcePage]:
    """One page per URL with its longest text (the model re-fetches a research
    page to read past its first 6000 chars), the newest `limit` of them
    (prefetched and broad pages come first, the targeted fetch last)."""
    by_url: dict[str, SourcePage] = {}
    for page in pages:
        kept = by_url.get(page.url)
        if kept is None or len(page.text) > len(kept.text):
            by_url[page.url] = page if kept is None else SourcePage(kept.title, page.url, page.text)
    return list(by_url.values())[-limit:]


def _interleave(searched: list[list[SourcePage]]) -> list[SourcePage]:
    longest = max((len(r) for r in searched), default=0)
    return [results[rank] for rank in range(longest) for results in searched if rank < len(results)]


def turn_pages(messages: list[BaseMessage]) -> list[SourcePage]:
    """The turn's pages in source-popup order (read pages, else search results).

    Replaces the cite_sources tool: the model sent it WITHOUT answer text in
    79% of tool-using turns (Sep 2026: 687 of 869), which cost a full extra
    model round each time (~49M input tokens/month) - and it forgot it in
    others. Sources are now the pages the turn READ: research pages that
    were fetched, successful fetch_url calls, browser pages, and sources a
    delegate_task subagent returned. A turn that answered from search
    snippets alone gets the top search results (rank-interleaved) instead.

    Returns:
        SourcePage list, de-duplicated by URL, at most 10 read pages or
        5 search results.
    """
    read, searched, _ = _read_and_searched(messages)
    if read:
        return _newest_longest(read, _MAX_READ_SOURCES)
    return _unique(_interleave(searched), _MAX_SEARCH_SOURCES)


def uncited_web_text(messages: list[BaseMessage]) -> str:
    """Web tool text the verifier may use but cannot cite by number."""
    read, searched, loose = _read_and_searched(messages)
    parts = list(loose)
    if read:
        parts += [f"{p.title}: {p.text}" for p in _interleave(searched) if p.text]
    return "\n".join(parts)
