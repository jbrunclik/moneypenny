"""Proposals: anything awaiting the user's yes (docs/features/proposals.md).

A tool files one during a turn; the saved reply links it (link_proposals);
the user answers it on its card or with a typed yes; claim_proposal lets
exactly one answer win, and finish_proposal records what applying did.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, cast

from src.db.models.dataclasses import Proposal, ProposalOption, ProposalState
from src.db.models.timestamps import from_db, from_db_or_none, to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from src.utils.connection_pool import ConnectionPool

_RESOLVED = ("approved", "declined", "expired", "failed")
INTERRUPTED = "Interrupted before it finished - check whether it was set up, and ask again if not."


def _row_to_proposal(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
        request_id=row["request_id"],
        kind=row["kind"],
        summary=row["summary"],
        details=json.loads(row["details"]),
        options=cast("list[ProposalOption]", json.loads(row["options"])),
        state=cast("ProposalState", row["state"]),
        chosen=row["chosen"],
        result=row["result"],
        resolved_by=row["resolved_by"],
        reported=bool(row["reported"]),
        created_at=from_db(row["created_at"]),
        resolved_at=from_db_or_none(row["resolved_at"]),
    )


class ProposalsMixin:
    """Mixin providing proposal storage."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _write(self, query: str, params: tuple[object, ...]) -> int:
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(conn, query, params)
            conn.commit()
        return cursor.rowcount

    def _select(self, query: str, params: tuple[object, ...]) -> list[Proposal]:
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(conn, query, params).fetchall()
        return [_row_to_proposal(row) for row in rows]

    def create_proposal(self, proposal: Proposal) -> Proposal:
        """Store a new (pending) proposal."""
        self._write(
            """INSERT INTO proposals (id, user_id, conversation_id, message_id, request_id,
                   kind, summary, details, options, state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id,
                proposal.user_id,
                proposal.conversation_id,
                proposal.message_id,
                proposal.request_id,
                proposal.kind,
                proposal.summary,
                json.dumps(proposal.details, ensure_ascii=False),
                json.dumps(proposal.options, ensure_ascii=False),
                proposal.state,
                to_db(proposal.created_at),
            ),
        )
        return proposal

    def get_proposal(self, proposal_id: str, user_id: str) -> Proposal | None:
        """The user's proposal, or None (unknown, or another user's)."""
        found = self._select(
            "SELECT * FROM proposals WHERE id = ? AND user_id = ?", (proposal_id, user_id)
        )
        return found[0] if found else None

    def proposals_for_messages(self, message_ids: list[str]) -> dict[str, list[Proposal]]:
        """Each reply's proposals (oldest first); replies without any are absent."""
        if not message_ids:
            return {}
        marks = ",".join("?" * len(message_ids))
        grouped: dict[str, list[Proposal]] = {}
        for proposal in self._select(
            f"SELECT * FROM proposals WHERE message_id IN ({marks}) ORDER BY created_at, rowid",
            tuple(message_ids),
        ):
            grouped.setdefault(proposal.message_id or "", []).append(proposal)
        return grouped

    def pending_proposals(self, conversation_id: str) -> list[Proposal]:
        """The conversation's proposals still awaiting an answer (oldest first)."""
        return self._select(
            """SELECT * FROM proposals WHERE conversation_id = ? AND state = 'pending'
               ORDER BY created_at, rowid""",
            (conversation_id,),
        )

    def claim_proposal(
        self, proposal_id: str, state: ProposalState, chosen: int | None, resolved_by: str
    ) -> bool:
        """Resolve a pending proposal - True for the one answer that wins."""
        return (
            self._write(
                """UPDATE proposals SET state = ?, chosen = ?, resolved_by = ?, resolved_at = ?
                   WHERE id = ? AND state = 'pending'""",
                (state, chosen, resolved_by, to_db(utc_now()), proposal_id),
            )
            == 1
        )

    def finish_proposal(self, proposal_id: str, state: ProposalState, result: str) -> None:
        """Record what applying the claimed option did (or why it failed)."""
        self._write(
            "UPDATE proposals SET state = ?, result = ? WHERE id = ?", (state, result, proposal_id)
        )

    def link_proposals(self, request_id: str, message_id: str) -> None:
        """Attach the proposals a turn filed to the reply that shows them."""
        if request_id:
            self._write(
                "UPDATE proposals SET message_id = ? WHERE request_id = ? AND message_id IS NULL",
                (message_id, request_id),
            )

    def expire_proposals(
        self, conversation_id: str, message_id: str | None = None, *, keep_unlinked: bool = False
    ) -> int:
        """Expire pending proposals - the conversation's, or one reply's; how
        many. keep_unlinked spares the ones no saved reply shows yet (a turn
        still running filed them)."""
        query = """UPDATE proposals SET state = 'expired', resolved_by = 'system', resolved_at = ?
                   WHERE conversation_id = ? AND state = 'pending'"""
        params: tuple[object, ...] = (to_db(utc_now()), conversation_id)
        if message_id is not None:
            query += " AND message_id = ?"
            params = (*params, message_id)
        if keep_unlinked:
            query += " AND message_id IS NOT NULL"
        return self._write(query, params)

    def fail_stale_applying(self, before: datetime) -> int:
        """Proposals claimed before a moment but never finished (the worker
        died mid-apply) become failed - never a card stuck "setting up" or a
        false "done"; how many."""
        return self._write(
            """UPDATE proposals SET state = 'failed', result = ?
               WHERE state = 'applying' AND resolved_at < ?""",
            (INTERRUPTED, to_db(before)),
        )

    def supersede_proposals(self, request_id: str, kind: str, keep_id: str) -> int:
        """A turn's newer proposal of a kind replaces its older pending ones."""
        return self._write(
            """UPDATE proposals SET state = 'superseded', resolved_by = 'system', resolved_at = ?
               WHERE request_id = ? AND kind = ? AND id != ? AND state = 'pending'""",
            (to_db(utc_now()), request_id, kind, keep_id),
        )

    def unreported_proposals(self, conversation_id: str) -> list[Proposal]:
        """Resolved proposals the agent has not been told about yet."""
        marks = ",".join("?" * len(_RESOLVED))
        return self._select(
            f"""SELECT * FROM proposals WHERE conversation_id = ? AND reported = 0
                AND state IN ({marks}) ORDER BY resolved_at, rowid""",
            (conversation_id, *_RESOLVED),
        )

    def resolved_proposals_since(self, conversation_id: str, since: datetime) -> list[Proposal]:
        """Proposals resolved at or after a moment (a rerun's outcomes, told again)."""
        marks = ",".join("?" * len(_RESOLVED))
        return self._select(
            f"""SELECT * FROM proposals WHERE conversation_id = ? AND resolved_at >= ?
                AND state IN ({marks}) ORDER BY resolved_at, rowid""",
            (conversation_id, to_db(since), *_RESOLVED),
        )

    def mark_reported(self, ids: list[str]) -> None:
        """The agent has been told these outcomes."""
        if ids:
            marks = ",".join("?" * len(ids))
            self._write(
                f"UPDATE proposals SET reported = 1 WHERE id IN ({marks})",
                tuple(ids),
            )
