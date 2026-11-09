"""Migration 0089: deep-research offers (messages.research.offer and a
report's run.followup) become deep_research proposals on their message."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base
from src.enums import MessageRole

if TYPE_CHECKING:
    from pathlib import Path

_ID = "0089_research_offers_to_proposals"


def _migrate(path: Path, rollback: bool = False) -> None:
    backend = get_backend(f"sqlite:///{path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        if rollback:
            backend.rollback_migrations(
                backend.to_rollback(migrations).filter(lambda m: m.id == _ID)
            )
        else:
            backend.apply_migrations(backend.to_apply(migrations))


def _offer(status: str, kind: str = "initial") -> dict[str, Any]:
    return {
        "question": "Which e-bike?",
        "context": "",
        "sub_questions": ["a", "b"],
        "estimate": {"minutes": 5, "cost_czk": 10},
        "rates": {},
        "status": status,
        "autostart": False,
        "kind": kind,
        "round": 2 if kind == "followup" else 1,
        "created_at": "2026-11-01T10:00:00.000000+00:00",
    }


def _research(path: Path, message_id: str) -> Any:
    conn = sqlite3.connect(path)
    [row] = conn.execute("SELECT research FROM messages WHERE id = ?", (message_id,)).fetchall()
    conn.close()
    return json.loads(row[0]) if row[0] else None


def _seed(path: Path) -> tuple[Any, dict[str, str]]:
    db = Database(db_path=path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    conv = db.create_conversation(user.id, "Bikes")
    ids = {
        name: db.add_message(conv.id, MessageRole.ASSISTANT, name).id
        for name in ("open", "started", "declined", "report")
    }
    db.close()
    _migrate(path, rollback=True)
    conn = sqlite3.connect(path)
    for name, research in (
        ("open", {"offer": _offer("offered")}),
        ("started", {"offer": _offer("started")}),
        ("declined", {"offer": _offer("declined")}),
        ("report", {"run": {"round": 1, "followup": _offer("offered", "followup")}}),
    ):
        conn.execute(
            "UPDATE messages SET research = ? WHERE id = ?", (json.dumps(research), ids[name])
        )
    conn.commit()
    conn.close()
    return user, ids


def test_offers_become_cards_with_their_outcome(test_db_path: Path) -> None:
    user, ids = _seed(test_db_path)

    _migrate(test_db_path)

    db = Database(db_path=test_db_path, apply_migrations=False)
    cards = db.proposals_for_messages(list(ids.values()))
    db.close()
    states = {name: [(c.kind, c.state) for c in cards.get(ids[name], [])] for name in ids}
    assert states == {
        "open": [("deep_research", "pending")],
        "started": [("deep_research", "approved")],
        "declined": [("deep_research", "declined")],
        "report": [("deep_research", "pending")],
    }
    [followup] = cards[ids["report"]]
    assert followup.options[0]["payload"]["kind"] == "followup"
    assert followup.summary == "Which e-bike?" and followup.user_id == user.id
    assert _research(test_db_path, ids["open"]) is None
    assert _research(test_db_path, ids["report"]) == {"run": {"round": 1}}


def test_rollback_writes_the_offers_back(test_db_path: Path) -> None:
    _user, ids = _seed(test_db_path)
    _migrate(test_db_path)

    _migrate(test_db_path, rollback=True)

    assert _research(test_db_path, ids["started"])["offer"]["status"] == "started"
    assert _research(test_db_path, ids["open"])["offer"]["status"] == "offered"
    assert _research(test_db_path, ids["report"])["run"]["followup"]["status"] == "offered"
    conn = sqlite3.connect(test_db_path)
    [(left,)] = conn.execute("SELECT count(*) FROM proposals WHERE kind = 'deep_research'")
    conn.close()
    assert left == 0
