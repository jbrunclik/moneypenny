"""Agent approval request database operations mixin."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.agent_rows import row_to_approval_request
from src.db.models.dataclasses import ApprovalRequest
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class AgentApprovalMixin:
    """Mixin providing agent approval request operations."""

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
        agent_id: str,
        user_id: str,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        description: str,
    ) -> ApprovalRequest:
        """Create a new approval request for a dangerous operation.

        The request will expire after AGENT_APPROVAL_TTL_HOURS (default: 24 hours).
        """
        request_id = str(uuid.uuid4())
        now = utcnow_naive()
        expires_at = now + timedelta(hours=Config.AGENT_APPROVAL_TTL_HOURS)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO agent_approval_requests
                   (id, agent_id, user_id, tool_name, tool_args, description, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    request_id,
                    agent_id,
                    user_id,
                    tool_name,
                    json.dumps(tool_args) if tool_args else None,
                    description,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()

        logger.info(
            "Approval request created",
            extra={
                "request_id": request_id,
                "agent_id": agent_id,
                "tool": tool_name,
                "expires_at": expires_at.isoformat(),
            },
        )

        return ApprovalRequest(
            id=request_id,
            agent_id=agent_id,
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
                "SELECT * FROM agent_approval_requests WHERE id = ? AND user_id = ?",
                (request_id, user_id),
            ).fetchone()

            if not row:
                return None

            return row_to_approval_request(row)

    def get_pending_approvals(self, user_id: str) -> list[ApprovalRequest]:
        """Get all pending (non-expired) approval requests for a user."""
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_approval_requests
                   WHERE user_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY created_at DESC""",
                (user_id, now.isoformat()),
            ).fetchall()

            return [row_to_approval_request(row) for row in rows]

    def get_pending_approval_for_agent(self, agent_id: str) -> ApprovalRequest | None:
        """Get the pending (non-expired) approval request for an agent (if any)."""
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT * FROM agent_approval_requests
                   WHERE agent_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (agent_id, now.isoformat()),
            ).fetchone()

            if not row:
                return None

            return row_to_approval_request(row)

    def has_pending_approval(self, agent_id: str) -> bool:
        """Check if an agent has a pending (non-expired) approval request."""
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM agent_approval_requests
                   WHERE agent_id = ? AND status = 'pending'
                   AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (agent_id, now.isoformat()),
            ).fetchone()

            return row is not None

    def consume_approved_request(
        self, agent_id: str, tool_name: str, target_id: str | None = None
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
        Approvals without a target_id authorize any one call (matching
        approvals are preferred over generic ones).
        """
        now = utcnow_naive().isoformat()
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT id, tool_args FROM agent_approval_requests
                   WHERE agent_id = ? AND tool_name = ?
                     AND status = 'approved' AND expires_at > ?
                   ORDER BY created_at DESC""",
                (agent_id, tool_name, now),
            ).fetchall()

            chosen_id: str | None = None
            generic_id: str | None = None
            for row in rows:
                approval_target = None
                if row["tool_args"]:
                    try:
                        approval_target = json.loads(row["tool_args"]).get("target_id")
                    except json.JSONDecodeError:
                        approval_target = None
                if approval_target:
                    if target_id and approval_target == target_id:
                        chosen_id = row["id"]
                        break
                elif generic_id is None:
                    generic_id = row["id"]

            chosen_id = chosen_id or generic_id
            consumed = False
            if chosen_id:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE agent_approval_requests SET status = 'consumed'
                       WHERE id = ? AND status = 'approved'""",
                    (chosen_id,),
                )
                conn.commit()
                consumed = cursor.rowcount > 0

        logger.info(
            "Approval consumption attempt",
            extra={
                "agent_id": agent_id,
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
        now = utcnow_naive()
        status = "approved" if approved else "rejected"

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE agent_approval_requests
                   SET status = ?, resolved_at = ?
                   WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (status, now.isoformat(), request_id, user_id),
            )

            if cursor.rowcount == 0:
                return None

            conn.commit()

        logger.info(
            "Approval request resolved",
            extra={"request_id": request_id, "status": status},
        )

        return self.get_approval_request(request_id, user_id)
