"""Migration 0060 adds messages.action and turns old look-up messages into actions."""

import importlib.util
import json
import sqlite3
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def m() -> ModuleType:
    """The migration module, loaded outside yoyo (step() needs its collector)."""
    import yoyo

    spec = importlib.util.spec_from_file_location("m0060", "migrations/0060_add_message_action.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original = yoyo.step
    yoyo.step = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        spec.loader.exec_module(module)
    finally:
        yoyo.step = original
    return module


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE messages (id TEXT, conversation_id TEXT, role TEXT, content TEXT, "
        "created_at TEXT, annotations TEXT, action TEXT)"
    )
    return conn


def _add(conn: sqlite3.Connection, *row: object) -> None:
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, NULL)", row)


def _action(conn: sqlite3.Connection, msg_id: str) -> object:
    raw = conn.execute("SELECT action FROM messages WHERE id = ?", (msg_id,)).fetchone()[0]
    return json.loads(raw) if raw else None


def test_look_ups_become_verify_claim_actions(m: ModuleType) -> None:
    conn = _db()
    claims = [
        {"type": "claim", "verdict": "supported", "quote": "Kurýr"},
        {"type": "claim", "verdict": "not_found", "quote": "**Castelli** Flanders Warm"},
    ]
    _add(conn, "a1", "c", "assistant", "odpověď", "2026-10-03T08:00:00", json.dumps(claims))
    _add(
        conn,
        "u1",
        "c",
        "user",
        "Dohledej a ověř: Castelli Flanders Warm",
        "2026-10-03T08:01:00",
        None,
    )
    _add(conn, "u2", "c", "user", "Look up and verify: Kurýr", "2026-10-03T08:02:00", None)
    _add(conn, "u3", "c", "user", "Dohledej a ověř: nic takového", "2026-10-03T08:03:00", None)
    _add(conn, "u4", "c", "user", "Dohledej mi prosím cenu", "2026-10-03T08:04:00", None)

    m.convert(conn)

    assert _action(conn, "u1") == {
        "type": "verify_claim",
        "source_message_id": "a1",
        "claim_index": 1,
        "quote": "Castelli Flanders Warm",
    }
    assert _action(conn, "u2")["claim_index"] == 0  # type: ignore[index]
    # No matching claim: still an action, without the link back
    assert _action(conn, "u3") == {
        "type": "verify_claim",
        "source_message_id": None,
        "claim_index": None,
        "quote": "nic takového",
    }
    assert _action(conn, "u4") is None
    # The text the model saw stays as it was
    assert conn.execute("SELECT content FROM messages WHERE id='u1'").fetchone() == (
        "Dohledej a ověř: Castelli Flanders Warm",
    )


def test_the_nearest_earlier_answer_wins(m: ModuleType) -> None:
    conn = _db()
    claim = json.dumps([{"type": "claim", "verdict": "not_found", "quote": "X"}])
    _add(conn, "old", "c", "assistant", "a", "2026-10-03T08:00:00", claim)
    _add(conn, "new", "c", "assistant", "b", "2026-10-03T08:05:00", claim)
    _add(conn, "u", "c", "user", "Look up and verify: X", "2026-10-03T08:06:00", None)
    _add(conn, "later", "c", "assistant", "c", "2026-10-03T08:07:00", claim)
    _add(conn, "other", "d", "assistant", "d", "2026-10-03T08:05:30", claim)

    m.convert(conn)

    assert _action(conn, "u")["source_message_id"] == "new"  # type: ignore[index]


def test_malformed_annotations_never_stop_the_migration(m: ModuleType) -> None:
    """A deploy must not crash-loop on one odd row: it just finds no link there."""
    conn = _db()
    _add(conn, "bad", "c", "assistant", "a", "2026-10-03T08:00:00", "not json")
    _add(
        conn, "odd", "c", "assistant", "b", "2026-10-03T08:00:30", json.dumps(["x", {"quote": "X"}])
    )
    _add(conn, "u", "c", "user", "Look up and verify: X", "2026-10-03T08:01:00", None)

    m.convert(conn)

    assert _action(conn, "u") == {
        "type": "verify_claim",
        "source_message_id": "odd",
        "claim_index": 1,
        "quote": "X",
    }
