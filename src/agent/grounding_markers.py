"""In-place markers for unverified specifics.

The grounding check (src/agent/grounding_check.py) returns items and false
"verified" claims that are literal substrings of the answer. They are marked
right where they appear: an end-of-answer note was measured not to work (the
reader, and the eval judge, still took the main text as fact). Deterministic
and model-free; text is never deleted or reworded. Spec:
docs/superpowers/specs/2026-10-02-grounding-check-design.md.
"""

import re

_MARKERS = {"cs": "_(neověřeno)_", "en": "_(unverified)_"}

# Never edited: fenced code, inline code, markdown link targets
_PROTECTED = re.compile(r"```.*?```|`[^`\n]*`|\]\([^)\s]*\)", re.DOTALL)

# Item boundaries: not inside a word, and not followed by ".cz"-style suffixes
_BEFORE = r"(?<!\w)"
_AFTER = r"(?![\w-]|\.\w)"
_CLOSING_EMPHASIS = r"(\*\*|\*)?"


def _marker(language: str | None) -> str:
    return _MARKERS.get(language or "", _MARKERS["en"])


def _item_pattern(items: list[str]) -> re.Pattern[str] | None:
    """One alternation, longest first, so overlapping items mark once."""
    unique = sorted({item for item in items if item}, key=len, reverse=True)
    if not unique:
        return None
    alternation = "|".join(re.escape(item) for item in unique)
    return re.compile(f"{_BEFORE}(?:{alternation}){_AFTER}{_CLOSING_EMPHASIS}", re.IGNORECASE)


def _mark_items(text: str, pattern: re.Pattern[str], marker: str) -> str:
    """Mark items outside protected spans."""

    def mark(segment: str) -> str:
        return pattern.sub(lambda m: f"{m.group(0)} {marker}", segment)

    out: list[str] = []
    pos = 0
    for span in _PROTECTED.finditer(text):
        out.append(mark(text[pos : span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(mark(text[pos:]))
    return "".join(out)


def _mark_claims(text: str, claims: list[str], marker: str) -> str:
    """Append the marker after each false claim's first occurrence."""
    for claim in claims:
        match = re.search(re.escape(claim), text, re.IGNORECASE) if claim else None
        if match:
            text = f"{text[: match.end()]} {marker}{text[match.end() :]}"
    return text


def mark_unverified(
    answer: str, items: list[str], false_claims: list[str], language: str | None
) -> str:
    """The answer with a marker after each unverified item and false claim.

    Claims are marked first: item markers change the text inside a claim,
    after which the claim would no longer match.
    """
    if not items and not false_claims:
        return answer
    marker = _marker(language)
    text = _mark_claims(answer, false_claims, marker)
    pattern = _item_pattern(items)
    return _mark_items(text, pattern, marker) if pattern else text
