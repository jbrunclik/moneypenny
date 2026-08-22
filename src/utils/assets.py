"""Vite manifest helpers for production asset injection."""

from typing import Any


def collect_entry_css(manifest: dict[str, Any], entry: str) -> list[str]:
    """Collect every stylesheet reachable from an entry's static import graph.

    Vendor chunks (katex, hljs) carry their own CSS since the bundle split,
    so the entry's own ``css`` list alone is not enough. Imported chunks'
    CSS comes first so the app stylesheet keeps the last word in the
    cascade. Dynamic imports are excluded - Vite loads their CSS at import
    time.
    """
    if entry not in manifest:
        return []

    ordered: list[str] = []
    seen_css: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        visited.add(key)
        chunk = manifest.get(key, {})
        for imported in chunk.get("imports", []):
            visit(imported)
        for css in chunk.get("css", []):
            if css not in seen_css:
                seen_css.add(css)
                ordered.append(css)

    chunk = manifest[entry]
    for imported in chunk.get("imports", []):
        visit(imported)
    for css in chunk.get("css", []):
        if css not in seen_css:
            seen_css.add(css)
            ordered.append(css)

    return ordered
