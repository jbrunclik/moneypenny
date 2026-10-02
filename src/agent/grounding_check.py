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
