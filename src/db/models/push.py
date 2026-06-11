"""Push subscription database operations mixin.

One row per device/browser subscription. endpoint is unique - the same
browser re-subscribing upserts its keys. Dead subscriptions (push service
returns 404/410) are deleted by the send pipeline in src/utils/push.py.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import PushSubscription
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


def _row_to_subscription(row: sqlite3.Row) -> PushSubscription:
    return PushSubscription(
        id=row["id"],
        user_id=row["user_id"],
        endpoint=row["endpoint"],
        p256dh=row["p256dh"],
        auth=row["auth"],
        user_agent=row["user_agent"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_used_at=(datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None),
    )


class PushSubscriptionMixin:
    """Mixin providing push subscription operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def save_push_subscription(
        self,
        user_id: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> PushSubscription:
        """Create or update a subscription (upsert by endpoint)."""
        sub_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO push_subscriptions
                   (id, user_id, endpoint, p256dh, auth, user_agent, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(endpoint) DO UPDATE SET
                       user_id = excluded.user_id,
                       p256dh = excluded.p256dh,
                       auth = excluded.auth,
                       user_agent = excluded.user_agent""",
                (sub_id, user_id, endpoint, p256dh, auth, user_agent, now),
            )
            conn.commit()
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM push_subscriptions WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
        logger.info(
            "Push subscription saved",
            extra={"user_id": user_id, "subscription_id": row["id"]},
        )
        return _row_to_subscription(row)

    def get_push_subscriptions(self, user_id: str) -> list[PushSubscription]:
        """All subscriptions for a user (one per device/browser)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [_row_to_subscription(row) for row in rows]

    def delete_push_subscription(self, endpoint: str, user_id: str | None = None) -> bool:
        """Delete a subscription by endpoint.

        Args:
            endpoint: The push service endpoint URL
            user_id: When set, only delete if owned by this user (API path);
                the send pipeline prunes expired endpoints without it.
        """
        with self._pool.get_connection() as conn:
            if user_id is not None:
                cursor = self._execute_with_timing(
                    conn,
                    "DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?",
                    (endpoint, user_id),
                )
            else:
                cursor = self._execute_with_timing(
                    conn,
                    "DELETE FROM push_subscriptions WHERE endpoint = ?",
                    (endpoint,),
                )
            conn.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Push subscription deleted", extra={"user_id": user_id})
        return deleted

    def touch_push_subscription(self, subscription_id: str) -> None:
        """Record a successful send on the subscription."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE push_subscriptions SET last_used_at = ? WHERE id = ?",
                (datetime.now().isoformat(), subscription_id),
            )
            conn.commit()
