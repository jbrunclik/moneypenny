"""Relative links in the docs and AI-assistant config must resolve.

Sep 2026: 48 links were broken - root-level pages using ../../, links to
pages that were never written, and specs split into directories.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_FENCED = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def _markdown_files() -> list[Path]:
    files = [*_ROOT.glob("*.md"), *_ROOT.glob("docs/**/*.md"), *_ROOT.glob(".claude/**/*.md")]
    return sorted(p for p in files if p.is_file())


def _broken_links(path: Path) -> list[str]:
    text = _INLINE_CODE.sub("", _FENCED.sub("", path.read_text()))
    broken = []
    for link in _LINK.findall(text):
        target = link.split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", link):
            continue
        if not (path.parent / target).exists():
            broken.append(link)
    return broken


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: str(p.relative_to(_ROOT)))
def test_relative_links_resolve(path: Path) -> None:
    assert _broken_links(path) == []
