"""Migration 0058 turns inline grounding markers into legacy annotations."""

import importlib.util
import sqlite3
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def m() -> ModuleType:
    """The migration module, loaded outside yoyo (step() needs its collector)."""
    import yoyo

    spec = importlib.util.spec_from_file_location(
        "m0058", "migrations/0058_convert_grounding_markers.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original = yoyo.step
    yoyo.step = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        spec.loader.exec_module(module)
    finally:
        yoyo.step = original
    return module


@pytest.mark.parametrize(
    ("content", "clean", "quotes"),
    [
        (
            "pracoviště registru (Bohdalec, Jarov, Vyšehrad _(neověřeno)_).",
            "pracoviště registru (Bohdalec, Jarov, Vyšehrad).",
            ["Vyšehrad"],
        ),
        (
            "- **Rychlost:** 24–48 hodin _(neověřeno)_.",
            "- **Rychlost:** 24–48 hodin.",
            ["24–48 hodin"],
        ),
        (
            "nesmí být starší než **1 rok** _(neověřeno)_ (od novely",
            "nesmí být starší než **1 rok** (od novely",
            ["1 rok"],
        ),
        (
            "Cena: Kolem 1 200–1 600 Kč _(neověřeno)_ za úkon",
            "Cena: Kolem 1 200–1 600 Kč za úkon",
            ["Kolem 1 200–1 600 Kč"],
        ),
        ("Open daily 9-17 _(unverified)_\nBye", "Open daily 9-17\nBye", ["Open daily 9-17"]),
        # Plan times: a colon inside a time is not a boundary
        ("* **10:30** _(neověřeno)_ odjezd", "* **10:30** odjezd", ["10:30"]),
        ("* **11:30–13:15** _(neověřeno)_ oběd", "* **11:30–13:15** oběd", ["11:30–13:15"]),
        # Consecutive markers: the earlier marker bounds the next quote
        (
            "drony Magura V5 _(neověřeno)_ a raketový program Hrim/Sapsan _(neověřeno)_.",
            "drony Magura V5 a raketový program Hrim/Sapsan.",
            ["drony Magura V5", "a raketový program Hrim/Sapsan"],
        ),
        # Markdown headings drop their markup and numbering
        (
            "### 2. Pakt z roku 1968 _(neověřeno)_\nText",
            "### 2. Pakt z roku 1968\nText",
            ["Pakt z roku 1968"],
        ),
    ],
)
def test_convert_markers(m: ModuleType, content: str, clean: str, quotes: list[str]) -> None:
    new_content, anns = m.convert_markers(content)

    assert new_content == clean
    assert [a["quote"] for a in anns] == quotes
    assert all(a["verdict"] == "not_found" and a["type"] == "claim" for a in anns)
    for ann in anns:
        assert new_content.find(ann["prefix"] + ann["quote"]) >= 0


def test_step_updates_rows_and_search_index(m: ModuleType) -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE messages (id TEXT, role TEXT, content TEXT, annotations TEXT, grounding TEXT);
        CREATE VIRTUAL TABLE search_index USING fts5(user_id, conversation_id, message_id, type, title, content);
        INSERT INTO messages VALUES ('a', 'assistant', 'Cena 1 200 Kč _(neověřeno)_.', NULL, NULL);
        INSERT INTO messages VALUES ('b', 'assistant', 'Clean answer.', NULL, NULL);
        INSERT INTO search_index VALUES ('u', 'c', 'a', 'message', '', 'Cena 1 200 Kč _(neověřeno)_.');
        """
    )

    m.convert(conn)

    content, anns, grounding = conn.execute(
        "SELECT content, annotations, grounding FROM messages WHERE id='a'"
    ).fetchone()
    assert content == "Cena 1 200 Kč." and '"legacy": true' in grounding and "1 200 Kč" in anns
    assert conn.execute("SELECT annotations FROM messages WHERE id='b'").fetchone() == (None,)
    assert conn.execute("SELECT content FROM search_index WHERE message_id='a'").fetchone() == (
        "Cena 1 200 Kč.",
    )
