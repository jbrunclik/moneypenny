"""Capturing a case's canned web once from the live search (evals/capture_web.py).

The capture runs at authoring time; these tests inject the search and fetch
so nothing touches the network.
"""

from pathlib import Path

import yaml

from evals.capture_web import capture

_CASE = """id: c
description: d
# Interim (Nov 18 2026): live until it gets canned pages
web: live
user: "kde koupit brompton"
expect:
  rubric: r
"""


def _search(query: str, n: int) -> list[dict[str, str]]:
    return [
        {"url": f"https://shop{i}.example.cz/{query[:5]}", "title": f"Shop {i}", "snippet": "s"}
        for i in range(n)
    ]


def test_capture_writes_results_and_trimmed_pages(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASE)
    pages = {"https://shop0.example.cz/bromp": "x" * 9000}

    def fetch(url: str, max_chars: int | None = None) -> tuple[str | None, str | None]:
        return (pages[url][:max_chars], None) if url in pages else (None, "HTTP 403")

    capture(
        path,
        ["brompton cena", "brompton prodejna"],
        search=_search,
        fetch=fetch,
        per_query=2,
        page_chars=5000,
    )

    data = yaml.safe_load(path.read_text())
    urls = [r["url"] for r in data["web"]["results"]]
    assert urls == [
        "https://shop0.example.cz/bromp",
        "https://shop1.example.cz/bromp",
    ]  # de-duplicated across the two queries
    assert list(data["web"]["pages"]) == ["https://shop0.example.cz/bromp"]  # 403 skipped
    assert len(data["web"]["pages"]["https://shop0.example.cz/bromp"]) == 5000
    text = path.read_text()
    assert "web: live" not in text and "Interim" not in text
    assert text.startswith("id: c\n") and "expect:\n  rubric: r" in text
    assert "# Canned web captured" in text


def test_capture_appends_when_the_case_had_no_web_line(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("id: c\nuser: u\nexpect:\n  rubric: r\n")
    capture(
        path, ["q"], search=_search, fetch=lambda u, max_chars=None: ("page", None), per_query=1
    )
    assert yaml.safe_load(path.read_text())["web"]["pages"]


def test_a_query_with_no_results_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASE)

    def search(query: str, n: int) -> list[dict[str, str]]:
        if query == "nothing":
            raise RuntimeError("No results found.")
        return _search(query, n)

    web = capture(
        path,
        ["nothing", "brompton"],
        search=search,
        fetch=lambda u, max_chars=None: ("page", None),
        per_query=1,
    )
    assert [r["url"] for r in web["results"]] == ["https://shop0.example.cz/bromp"]


def test_nothing_found_leaves_the_case_unchanged(tmp_path: Path) -> None:
    import pytest

    path = tmp_path / "c.yaml"
    path.write_text(_CASE)
    with pytest.raises(RuntimeError, match="nothing captured"):
        capture(path, ["q"], search=lambda q, n: [], fetch=lambda u, max_chars=None: (None, "x"))
    assert path.read_text() == _CASE
