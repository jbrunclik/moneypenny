"""User database operations mixin.

User creation and retrieval plus per-user preferences (custom instructions,
planner reset, WhatsApp phone, language, daily briefing agent). Integration
credentials live in user_integrations.py.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import User
from src.utils.logging import get_logger
from src.utils.token_crypto import decrypt_token

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
            # Tokens decrypt here so every reader of the User object gets
            # plaintext; legacy plaintext rows pass through unchanged
            todoist_access_token=decrypt_token(row["todoist_access_token"]),
            todoist_connected_at=todoist_connected_at,
            google_calendar_access_token=decrypt_token(row["google_calendar_access_token"]),
            google_calendar_refresh_token=decrypt_token(row["google_calendar_refresh_token"]),
            google_calendar_token_expires_at=calendar_expires_at,
            google_calendar_connected_at=calendar_connected_at,
            google_calendar_email=row["google_calendar_email"],
            google_calendar_selected_ids=calendar_selected_ids,
            planner_last_reset_at=planner_last_reset,
            whatsapp_phone=row["whatsapp_phone"] if "whatsapp_phone" in row.keys() else None,
            garmin_token=(
                decrypt_token(row["garmin_token"]) if "garmin_token" in row.keys() else None
            ),
            garmin_connected_at=(
                datetime.fromisoformat(row["garmin_connected_at"])
                if "garmin_connected_at" in row.keys() and row["garmin_connected_at"]
                else None
            ),
            rouvy_email=(
                decrypt_token(row["rouvy_email"]) if "rouvy_email" in row.keys() else None
            ),
            rouvy_password=(
                decrypt_token(row["rouvy_password"]) if "rouvy_password" in row.keys() else None
            ),
            rouvy_session=(
                decrypt_token(row["rouvy_session"]) if "rouvy_session" in row.keys() else None
            ),
            rouvy_connected_at=(
                datetime.fromisoformat(row["rouvy_connected_at"])
                if "rouvy_connected_at" in row.keys() and row["rouvy_connected_at"]
                else None
            ),
            daily_briefing_agent_id=(
                row["daily_briefing_agent_id"] if "daily_briefing_agent_id" in row.keys() else None
            ),
            preferred_language=(
                row["preferred_language"] if "preferred_language" in row.keys() else None
            ),
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

    def refresh_google_profile(self, user: User, name: str, picture: str | None) -> User:
        """Store the name and avatar from a fresh Google login if they changed.

        Both were written once at first login and never refreshed. Values
        Google did not send are kept: a missing picture, or the email the
        login route substitutes for a missing name.
        """
        new_name = name if name and name != user.email else user.name
        new_picture = picture or user.picture
        if (new_name, new_picture) == (user.name, user.picture):
            return user
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE users SET name = ?, picture = ? WHERE id = ?",
                (new_name, new_picture, user.id),
            )
            conn.commit()
        logger.info("Google profile refreshed", extra={"user_id": user.id})
        return replace(user, name=new_name, picture=new_picture)

    def get_user_by_id(self, user_id: str) -> User | None:
        """Get a user by their ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> User | None:
        """Get a user by email address (None when they never logged in)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT * FROM users WHERE email = ?", (email,)
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

    def update_user_whatsapp_phone(self, user_id: str, phone: str | None) -> bool:
        """Update a user's WhatsApp phone number.

        Args:
            user_id: The user ID
            phone: The WhatsApp phone number in E.164 format (e.g., +1234567890),
                   or None to remove

        Returns:
            True if user was updated, False if not found
        """
        logger.debug(
            "Updating user WhatsApp phone",
            extra={"user_id": user_id, "has_phone": bool(phone)},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET whatsapp_phone = ? WHERE id = ?",
                (phone, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            action = "set" if phone else "removed"
            logger.info(
                f"User WhatsApp phone {action}",
                extra={"user_id": user_id},
            )
        else:
            logger.warning(
                "User not found for WhatsApp phone update",
                extra={"user_id": user_id},
            )
        return updated

    def update_user_preferred_language(self, user_id: str, language: str | None) -> bool:
        """Set or clear the user's primary response language (None = auto)."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET preferred_language = ? WHERE id = ?",
                (language, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(
                "User preferred language updated",
                extra={"user_id": user_id, "language": language or "auto"},
            )
        return updated

    def update_user_daily_briefing_agent(self, user_id: str, agent_id: str | None) -> bool:
        """Set or clear the user's Daily Briefing agent pointer.

        Args:
            user_id: The user ID
            agent_id: The briefing agent's id, or None to clear

        Returns:
            True if user was updated, False if not found
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET daily_briefing_agent_id = ? WHERE id = ?",
                (agent_id, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(
                "User daily briefing agent pointer updated",
                extra={"user_id": user_id, "has_agent": bool(agent_id)},
            )
        return updated
