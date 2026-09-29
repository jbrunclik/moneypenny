"""User integration credentials database operations mixin.

Todoist, Google Calendar, Garmin and Rouvy tokens/credentials (encrypted at
rest) and the selected-calendars list.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger
from src.utils.token_crypto import decrypt_token, encrypt_token

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class UserIntegrationsMixin:
    """Mixin providing per-user integration credential operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def update_user_todoist_token(self, user_id: str, access_token: str | None) -> bool:
        """Update a user's Todoist access token.

        Args:
            user_id: The user ID
            access_token: The Todoist access token (or None to disconnect)

        Returns:
            True if user was updated, False if not found
        """
        logger.debug(
            "Updating user Todoist token",
            extra={"user_id": user_id, "connecting": bool(access_token)},
        )

        connected_at = datetime.now().isoformat() if access_token else None

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET todoist_access_token = ?, todoist_connected_at = ? WHERE id = ?",
                (encrypt_token(access_token), connected_at, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            action = "connected" if access_token else "disconnected"
            logger.info(
                f"User Todoist {action}",
                extra={"user_id": user_id},
            )
        else:
            logger.warning(
                "User not found for Todoist token update",
                extra={"user_id": user_id},
            )
        return updated

    def update_user_google_calendar_tokens(
        self,
        user_id: str,
        access_token: str | None,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        email: str | None = None,
        connected_at: datetime | None = None,
    ) -> bool:
        """Update a user's Google Calendar OAuth tokens."""
        logger.debug(
            "Updating user Google Calendar tokens",
            extra={
                "user_id": user_id,
                "connecting": bool(access_token),
                "has_refresh_token": bool(refresh_token),
            },
        )

        connected_at_iso = None
        if access_token:
            connected_at_iso = (connected_at or datetime.now()).isoformat()
        expires_at_str = expires_at.isoformat() if expires_at else None

        if not access_token:
            refresh_token = None
            email = None
            expires_at_str = None
            connected_at_iso = None

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """
                UPDATE users
                SET
                    google_calendar_access_token = ?,
                    google_calendar_refresh_token = ?,
                    google_calendar_token_expires_at = ?,
                    google_calendar_connected_at = ?,
                    google_calendar_email = ?
                WHERE id = ?
                """,
                (
                    encrypt_token(access_token),
                    encrypt_token(refresh_token),
                    expires_at_str,
                    connected_at_iso,
                    email,
                    user_id,
                ),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            action = "connected" if access_token else "disconnected"
            logger.info(
                f"User Google Calendar {action}",
                extra={"user_id": user_id},
            )
        else:
            logger.warning(
                "User not found for Google Calendar token update",
                extra={"user_id": user_id},
            )

        return updated

    def refresh_user_google_calendar_tokens(
        self,
        user_id: str,
        used_refresh_token: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> bool:
        """Store refreshed calendar tokens with a compare-and-swap guard.

        Only writes when the stored refresh token still equals the one this
        refresh actually used. With multiple gunicorn workers two requests
        can refresh concurrently; an unconditional write would let the loser
        overwrite the winner's (possibly rotated) refresh token with a stale
        one, permanently breaking future refreshes (R2).

        Returns:
            True if this writer won (tokens stored), False if another worker
            refreshed first (caller's access token is still valid to USE,
            just must not be stored).
        """
        with self._pool.get_connection() as conn:
            # Encryption is non-deterministic, so the guard cannot compare
            # the plaintext refresh token in SQL. Instead: read the stored
            # (possibly encrypted) value, compare plaintexts in Python, and
            # CAS on the exact stored string - unique per encryption, so it
            # is a perfect swap token. Works for legacy plaintext rows too.
            row = self._execute_with_timing(
                conn,
                "SELECT google_calendar_refresh_token FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return False
            stored_value = row["google_calendar_refresh_token"]
            if decrypt_token(stored_value) != used_refresh_token:
                return False

            cursor = self._execute_with_timing(
                conn,
                """
                UPDATE users
                SET
                    google_calendar_access_token = ?,
                    google_calendar_refresh_token = ?,
                    google_calendar_token_expires_at = ?
                WHERE id = ? AND google_calendar_refresh_token = ?
                """,
                (
                    encrypt_token(access_token),
                    encrypt_token(refresh_token),
                    expires_at.isoformat(),
                    user_id,
                    stored_value,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_user_calendar_selected_ids(self, user_id: str, calendar_ids: list[str]) -> bool:
        """Update selected calendar IDs for a user.

        Args:
            user_id: User ID
            calendar_ids: List of calendar IDs to select (defaults to ["primary"] if empty)

        Returns:
            True if update succeeded, False otherwise
        """
        # Validate and default to primary if empty
        if not calendar_ids:
            calendar_ids = ["primary"]

        # Always ensure primary calendar is included
        if "primary" not in calendar_ids:
            calendar_ids = ["primary"] + calendar_ids

        calendar_ids_json = json.dumps(calendar_ids)

        logger.debug(
            "Updating user calendar selection",
            extra={"user_id": user_id, "count": len(calendar_ids)},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET google_calendar_selected_ids = ? WHERE id = ?",
                (calendar_ids_json, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(
                "Updated calendar selection",
                extra={"user_id": user_id, "count": len(calendar_ids)},
            )
        else:
            logger.warning(
                "User not found for calendar selection update",
                extra={"user_id": user_id},
            )

        return updated

    def update_user_garmin_token(self, user_id: str, token: str | None) -> bool:
        """Update a user's Garmin Connect session token.

        Args:
            user_id: The user ID
            token: Serialized garth session tokens (JSON), or None to disconnect

        Returns:
            True if user was updated, False if not found
        """
        logger.debug(
            "Updating user Garmin token",
            extra={"user_id": user_id, "connecting": bool(token)},
        )

        connected_at = datetime.now().isoformat() if token else None

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET garmin_token = ?, garmin_connected_at = ? WHERE id = ?",
                (encrypt_token(token), connected_at, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            action = "connected" if token else "disconnected"
            logger.info(
                f"User Garmin {action}",
                extra={"user_id": user_id},
            )
        else:
            logger.warning(
                "User not found for Garmin token update",
                extra={"user_id": user_id},
            )
        return updated

    def update_user_rouvy_credentials(
        self,
        user_id: str,
        email: str | None,
        password: str | None,
        session: str | None,
    ) -> bool:
        """Store (or clear) a user's Rouvy credentials + session cookie blob.

        email/password/session are encrypted at rest. Passing all-None clears
        the credentials and disconnects the integration. ``rouvy_connected_at``
        is set when a session is stored, cleared otherwise.

        Unlike Garmin, the password IS persisted (encrypted): Rouvy sessions are
        short-lived and re-login (headless) needs the credentials to refresh.
        """
        connected_at = datetime.now().isoformat() if session else None
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET rouvy_email = ?, rouvy_password = ?, "
                "rouvy_session = ?, rouvy_connected_at = ? WHERE id = ?",
                (
                    encrypt_token(email),
                    encrypt_token(password),
                    encrypt_token(session),
                    connected_at,
                    user_id,
                ),
            )
            conn.commit()
            updated = cursor.rowcount > 0
        if updated:
            logger.info(
                "User Rouvy %s",
                "connected" if session else "disconnected",
                extra={"user_id": user_id},
            )
        return updated

    def update_user_rouvy_session(self, user_id: str, session: str | None) -> bool:
        """Update only the stored Rouvy session cookie blob (used on refresh)."""
        connected_at = datetime.now().isoformat() if session else None
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET rouvy_session = ?, rouvy_connected_at = ? WHERE id = ?",
                (encrypt_token(session), connected_at, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
