"""An artifact page's checklist items and which of them are ticked.

The artifact frame saves every .mp-checklist tick itself (web/src/artifact/
bridge-client.ts) in the artifact's state envelope - {"app": ..., "checklist":
{label key: true}} - keyed exactly like checklist_items keys them here, so the
agent can answer "what's left on my list?" from read_artifact.
"""

import re
from html.parser import HTMLParser

_WHITESPACE = re.compile(r"\s+")
# Elements with no end tag: never on the open-element stack
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)


class _ChecklistLabels(HTMLParser):
    """The text of every <label> inside an element with class mp-checklist."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = []
        self._open: list[bool] = []  # per open element: does it start a checklist
        self._label: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag not in _VOID_TAGS:
            self._open.append("mp-checklist" in classes)
        if tag == "label" and any(self._open):
            self._label = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label is not None:
            self.labels.append(_WHITESPACE.sub(" ", "".join(self._label)).strip())
            self._label = None
        if tag not in _VOID_TAGS and self._open:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        if self._label is not None:
            self._label.append(data)


def checklist_items(html: str) -> list[str]:
    """The page's checklist item keys in order: label text, " #n" on the n-th repeat."""
    parser = _ChecklistLabels()
    parser.feed(html)
    seen: dict[str, int] = {}
    keys: list[str] = []
    for label in parser.labels:
        seen[label] = seen.get(label, 0) + 1
        keys.append(label if seen[label] == 1 else f"{label} #{seen[label]}")
    return keys


def checklist_status(html: str, state: object) -> dict[str, list[str]] | None:
    """Done and open items in page order, or None when the page has no checklist."""
    items = checklist_items(html)
    if not items:
        return None
    ticks = state.get("checklist") if isinstance(state, dict) else None
    ticked = ticks if isinstance(ticks, dict) else {}
    return {
        "done": [key for key in items if ticked.get(key) is True],
        "open": [key for key in items if ticked.get(key) is not True],
    }
