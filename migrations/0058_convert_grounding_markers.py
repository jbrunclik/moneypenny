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
# The quote runs back to the nearest of these (or the line start, or the
# previous marker). A dash only as a spaced separator ("SPZ – text"), never
# inside "1 200–1 600"; a colon only before a space, never inside "10:30".
_BOUNDARY = re.compile(
    r"(?:\*\*|[(,;]|:(?=\s)|\s[–—]\s|^\s*(?:[-*+]|\d+\.)\s|^#{1,6}\s+(?:\d+\.\s+)?)",
    re.MULTILINE,
)
_TRAILING_EMPHASIS = re.compile(r"(\*\*|\*)$")
_MAX_QUOTE_CHARS = 60
_PREFIX_CHARS = 32


def _quote_before(text: str, floor: int) -> tuple[str, int]:
    """(quote, start index in text) of the phrase that ends at the end of text.

    `floor` is where the previous marker stood: a quote never reaches past it.
    """
    end = len(text)
    emphasis = _TRAILING_EMPHASIS.search(text)
    if emphasis:
        end = emphasis.start()
    line_start = max(text.rfind("\n", 0, end) + 1, floor)
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
    floor = 0
    for match in _MARKER.finditer(content):
        out += content[pos : match.start()]
        pos = match.end()
        quote, start = _quote_before(out, floor)
        floor = len(out)
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


def forget_legacy(conn: Any) -> None:
    """Rollback: drop the converted annotations (the marker text stays gone)."""
    conn.execute(
        "UPDATE messages SET annotations = NULL, grounding = NULL WHERE grounding LIKE '%\"legacy\"%'"
    )
    conn.commit()


steps = [step(convert, forget_legacy)]
