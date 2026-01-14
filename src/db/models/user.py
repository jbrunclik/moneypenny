"""User database operations mixin.

Contains all methods for User entity management including:
- User creation and retrieval
- Custom instructions
- Todoist integration
- Google Calendar integration
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import User
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class UserMixin:
    """Mixin providing User-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _row_to_user(self, row: sqlite3.Row) -> User:
        """Convert a database row to a User object."""
        todoist_connected_at = None
        if row["todoist_connected_at"]:
            todoist_connected_at = datetime.fromisoformat(row["todoist_connected_at"])

        calendar_connected_at = None
        if row["google_calendar_connected_at"]:
            calendar_connected_at = datetime.fromisoformat(row["google_calendar_connected_at"])

        calendar_expires_at = None
        if row["google_calendar_token_expires_at"]:
            calendar_expires_at = datetime.fromisoformat(row["google_calendar_token_expires_at"])

        planner_last_reset = None
        if row["planner_last_reset_at"]:
            planner_last_reset = datetime.fromisoformat(row["planner_last_reset_at"])

        # Parse selected calendar IDs (JSON array)
        calendar_selected_ids = None
        if "google_calendar_selected_ids" in row.keys() and row["google_calendar_selected_ids"]:
            try:
                calendar_selected_ids = json.loads(row["google_calendar_selected_ids"])
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid calendar selection JSON, defaulting to primary",
                    extra={"user_id": row["id"]},
                )
                calendar_selected_ids = ["primary"]
        else:
            # Default to primary calendar for backward compatibility
            calendar_selected_ids = ["primary"]

        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            picture=row["picture"],
            created_at=datetime.fromisoformat(row["created_at"]),
            custom_instructions=row["custom_instructions"],
            todoist_access_token=row["todoist_access_token"],
            todoist_connected_at=todoist_connected_at,
            google_calendar_access_token=row["google_calendar_access_token"],
            google_calendar_refresh_token=row["google_calendar_refresh_token"],
            google_calendar_token_expires_at=calendar_expires_at,
            google_calendar_connected_at=calendar_connected_at,
            google_calendar_email=row["google_calendar_email"],
            google_calendar_selected_ids=calendar_selected_ids,
            planner_last_reset_at=planner_last_reset,
        )

    def get_or_create_user(self, email: str, name: str, picture: str | None = None) -> User:
        """Get an existing user by email or create a new one."""
        logger.debug("Getting or creating user", extra={"email": email})
        with self._pool.get_connection() as conn:
            # Use INSERT OR IGNORE to handle race conditions when multiple
            # concurrent requests try to create the same user
            user_id = str(uuid.uuid4())
            now = datetime.now()
            cursor = self._execute_with_timing(
                conn,
                "INSERT OR IGNORE INTO users (id, email, name, picture, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, name, picture, now.isoformat()),
            )
            conn.commit()

            # Check if we created a new user or if one already existed
            if cursor.rowcount > 0:
                logger.info("User created", extra={"user_id": user_id, "email": email})
                return User(
                    id=user_id,
                    email=email,
                    name=name,
                    picture=picture,
                    created_at=now,
                    custom_instructions=None,
                    todoist_access_token=None,
                    todoist_connected_at=None,
                )

            # User already existed, fetch it
            row = self._execute_with_timing(
                conn, "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            if not row:
                # This should never happen - if INSERT OR IGNORE didn't insert,
                # the user must exist. But handle it defensively.
                raise RuntimeError(f"User with email {email} should exist but was not found")
            logger.debug("User found", extra={"user_id": row["id"], "email": email})
            return self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get a user by their ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_user(row)

    def update_user_custom_instructions(self, user_id: str, instructions: str | None) -> bool:
        """Update a user's custom instructions.

        Args:
            user_id: The user ID
            instructions: The custom instructions text (or None to clear)

        Returns:
            True if user was updated, False if not found
        """
        logger.debug(
            "Updating user custom instructions",
            extra={"user_id": user_id, "has_instructions": bool(instructions)},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET custom_instructions = ? WHERE id = ?",
                (instructions, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(
                "User custom instructions updated",
                extra={"user_id": user_id},
            )
        else:
            logger.warning(
                "User not found for custom instructions update",
                extra={"user_id": user_id},
            )
        return updated

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
                (access_token, connected_at, user_id),
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
                    access_token,
                    refresh_token,
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

    def update_planner_last_reset_at(self, user_id: str) -> bool:
        """Update the planner_last_reset_at timestamp for a user.

        Called after auto-reset or manual reset to track when the planner
        was last cleared.

        Args:
            user_id: The user ID

        Returns:
            True if user was updated, False if not found
        """
        now = datetime.now()
        logger.debug(
            "Updating planner last reset timestamp",
            extra={"user_id": user_id, "timestamp": now.isoformat()},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET planner_last_reset_at = ? WHERE id = ?",
                (now.isoformat(), user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
