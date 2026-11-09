"""Deep-research offers become deep_research proposals (one approval mechanism, step 3).

An offer lived on its reply as messages.research.offer, a report's follow-up
offer as messages.research.run.followup, each with its own status. Each
becomes a proposal on that message - its one option (Start) carries the
offer as payload, its state the offer's status (offered -> pending, started
-> approved, declined -> declined, superseded -> superseded) - and the key
leaves the JSON (research.run, the report's run data, stays). The rollback
writes the offers back from the cards and deletes them.
"""

import json
import sqlite3
import uuid

from yoyo import step

__depends__ = {"0088_run_proposals"}

_KIND = "deep_research"
_STATE = {"offered": "pending", "started": "approved", "declined": "declined"}
_STATUS = {"pending": "offered", "approved": "started", "declined": "declined"}
_DROPPED = ("status", "decided_at")


def _offers(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, dict]]:
    """(message_id, user_id, conversation_id, created_at, research) with an offer."""
    rows = conn.execute(
        """SELECT m.id, c.user_id, m.conversation_id, m.created_at, m.research
           FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE m.research IS NOT NULL
             AND (json_extract(m.research, '$.offer') IS NOT NULL
                  OR json_extract(m.research, '$.run.followup') IS NOT NULL)"""
    ).fetchall()
    return [(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rows]


def _insert_card(conn: sqlite3.Connection, row: tuple, offer: dict) -> None:
    message_id, user_id, conversation_id, created_at, _ = row
    state = _STATE.get(str(offer.get("status")), "superseded")
    payload = {k: v for k, v in offer.items() if k not in _DROPPED}
    conn.execute(
        """INSERT INTO proposals (id, user_id, conversation_id, message_id, request_id, kind,
               summary, details, options, state, chosen, result, resolved_by, reported,
               created_at, resolved_at)
           VALUES (?, ?, ?, ?, '', ?, ?, '{}', ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            str(uuid.uuid4()),
            user_id,
            conversation_id,
            message_id,
            _KIND,
            str(offer.get("question") or "Deep research"),
            json.dumps([{"label": "Start", "description": "", "payload": payload}]),
            state,
            0 if state == "approved" else None,
            "Started" if state == "approved" else None,
            None if state == "pending" else ("system" if state == "superseded" else "button"),
            created_at,
            None if state == "pending" else created_at,
        ),
    )


def _set_research(conn: sqlite3.Connection, message_id: str, research: dict) -> None:
    conn.execute(
        "UPDATE messages SET research = ? WHERE id = ?",
        (json.dumps(research) if research else None, message_id),
    )


def apply(conn: sqlite3.Connection) -> None:
    for row in _offers(conn):
        research = row[4]
        offer = research.pop("offer", None)
        followup = (research.get("run") or {}).pop("followup", None)
        for found in (offer, followup):
            if found:
                _insert_card(conn, row, found)
        _set_research(conn, row[0], research)


def rollback(conn: sqlite3.Connection) -> None:
    cards = conn.execute(
        """SELECT p.message_id, p.state, p.options, m.research FROM proposals p
           JOIN messages m ON m.id = p.message_id WHERE p.kind = ?
           ORDER BY p.created_at""",
        (_KIND,),
    ).fetchall()
    for message_id, state, options, research_json in cards:
        offer = {**json.loads(options)[0]["payload"], "status": _STATUS.get(state, "superseded")}
        research = json.loads(research_json) if research_json else {}
        if offer.get("kind") == "followup":
            research.setdefault("run", {})["followup"] = offer
        else:
            research["offer"] = offer
        _set_research(conn, message_id, research)
    conn.execute("DELETE FROM proposals WHERE kind = ?", (_KIND,))


steps = [step(apply, rollback)]
