"""Approval requests filed by job runs (job_approvals)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import ApprovalRequest
from src.db.models.job_rows import row_to_approval_request
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class JobApprovalMixin:
    """Mixin providing job approval requests."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def create_approval_request(
        self,
        item_id: str,
        user_id: str,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        description: str,
    ) -> ApprovalRequest:
        """Create a new approval request for a dangerous operation.

        The request will expire after AGENT_APPROVAL_TTL_HOURS (default: 24 hours).
        """
        request_id = str(uuid.uuid4())
        now = utc_now()
        expires_at = now + timedelta(hours=Config.AGENT_APPROVAL_TTL_HOURS)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO job_approvals
                   (id, item_id, user_id, tool_name, tool_args, description, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    request_id,
                    item_id,
                    user_id,
                    tool_name,
                    json.dumps(tool_args) if tool_args else None,
                    description,
                    to_db(now),
                    to_db(expires_at),
                ),
            )
            conn.commit()

        logger.info(
            "Approval request created",
            extra={
                "request_id": request_id,
                "item_id": item_id,
                "tool": tool_name,
                "expires_at": expires_at.isoformat(),
            },
        )

        return ApprovalRequest(
            id=request_id,
            item_id=item_id,
            user_id=user_id,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
            status="pending",
            created_at=now,
            resolved_at=None,
            expires_at=expires_at,
        )

    def get_approval_request(self, request_id: str, user_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM job_approvals WHERE id = ? AND user_id = ?",
                (request_id, user_id),
            ).fetchone()

            if not row:
                return None

            return row_to_approval_request(row)

    def get_pending_approvals(self, user_id: str) -> list[ApprovalRequest]:
        """Get all pending (non-expired) approval requests for a user."""
        now = utc_now()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM job_approvals
                   WHERE user_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY created_at DESC""",
                (user_id, to_db(now)),
            ).fetchall()

            return [row_to_approval_request(row) for row in rows]

    def has_pending_approval(self, item_id: str) -> bool:
        """Check if a job has a pending (non-expired) approval request."""
        now = utc_now()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM job_approvals
                   WHERE item_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (item_id, to_db(now)),
            ).fetchone()

            return row is not None

    def consume_approved_request(
        self,
        item_id: str,
        tool_name: str,
        target_id: str | None = None,
        operation: str | None = None,
    ) -> bool:
        """Atomically consume one approved, unexpired approval for a tool.

        Used by the destructive-action gate (permission_check.py): each
        approved request authorizes exactly ONE destructive tool call,
        after which its status flips to 'consumed'. Returns True when an
        approval was consumed, False when none was available - the tool
        must then refuse and tell the model to call request_approval.

        Argument-level matching: an approval whose tool_args carry a
        `target_id` only authorizes the call acting on that exact entity
        (a hijacked agent cannot spend an approval for item X on item Y).
        Operation matching: an approval records the operation it was asked
        for; it never authorizes a different one (an approved "add task"
        cannot spend itself on "delete project"). An approval with neither a
        target nor that operation authorizes nothing.
        """
        with self._pool.get_connection() as conn:
            now = to_db(utc_now())
            rows = self._execute_with_timing(
                conn,
                """SELECT id, tool_args FROM job_approvals
                   WHERE item_id = ? AND tool_name = ?
                     AND status = 'approved' AND expires_at > ?
                   ORDER BY created_at DESC""",
                (item_id, tool_name, now),
            ).fetchall()

            chosen_id: str | None = None
            generic_id: str | None = None
            for row in rows:
                args = _approval_args(row["tool_args"])
                approved_op, approved_target = args.get("operation"), args.get("target_id")
                if approved_op and approved_op != operation:
                    continue  # approved for another operation
                if approved_target:
                    if target_id and approved_target == target_id:
                        chosen_id = row["id"]
                        break
                elif approved_op and generic_id is None:
                    generic_id = row["id"]

            chosen_id = chosen_id or generic_id
            consumed = False
            if chosen_id:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE job_approvals SET status = 'consumed'
                       WHERE id = ? AND status = 'approved'""",
                    (chosen_id,),
                )
                conn.commit()
                consumed = cursor.rowcount > 0

        logger.info(
            "Approval consumption attempt",
            extra={
                "item_id": item_id,
                "tool_name": tool_name,
                "target_id": target_id,
                "consumed": consumed,
            },
        )
        return consumed

    def resolve_approval(
        self, request_id: str, user_id: str, approved: bool
    ) -> ApprovalRequest | None:
        """Resolve an approval request (approve or reject).

        Args:
            request_id: The request ID
            user_id: The user ID (for authorization)
            approved: True to approve, False to reject

        Returns:
            Updated ApprovalRequest or None if not found
        """
        now = utc_now()
        status = "approved" if approved else "rejected"

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE job_approvals
                   SET status = ?, resolved_at = ?
                   WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (status, to_db(now), request_id, user_id),
            )

            if cursor.rowcount == 0:
                # The UPDATE matched nothing but still opened a transaction
                conn.rollback()
                return None

            conn.commit()

        logger.info(
            "Approval request resolved",
            extra={"request_id": request_id, "status": status},
        )

        return self.get_approval_request(request_id, user_id)


def _approval_args(raw: str | None) -> dict[str, str]:
    """An approval's stored args (operation, target_id), {} when unreadable."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return (
        {k: str(v) for k, v in parsed.items() if isinstance(v, str)}
        if isinstance(parsed, dict)
        else {}
    )
