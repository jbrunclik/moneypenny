import base64
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from yoyo import get_backend, read_migrations

from src.api.schemas import MessageRole, PaginationDirection, ThumbnailStatus
from src.config import Config
from src.db.blob_store import get_blob_store
from src.utils.connection_pool import ConnectionPool
from src.utils.db_helpers import execute_with_timing, init_query_logging
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Blob Storage Helpers
# ============================================================================


def make_blob_key(message_id: str, file_index: int) -> str:
    """Create blob key for a file."""
    return f"{message_id}/{file_index}"


def make_thumbnail_key(message_id: str, file_index: int) -> str:
    """Create blob key for a thumbnail."""
    return f"{message_id}/{file_index}.thumb"


def save_file_to_blob_store(message_id: str, file_index: int, file_data: dict[str, Any]) -> None:
    """Save file data and thumbnail to blob store.

    Args:
        message_id: Message ID
        file_index: Index of file in message's files array
        file_data: File dict containing 'data', 'type', and optionally 'thumbnail'
    """
    blob_store = get_blob_store()
    mime_type = file_data.get("type", "application/octet-stream")

    # Save main file data
    if "data" in file_data:
        try:
            data_bytes = base64.b64decode(file_data["data"])
            blob_store.save(make_blob_key(message_id, file_index), data_bytes, mime_type)
        except Exception:
            logger.exception(
                "Failed to save file to blob store",
                extra={"message_id": message_id, "file_index": file_index},
            )

    # Save thumbnail if present
    if "thumbnail" in file_data and file_data["thumbnail"]:
        try:
            thumb_bytes = base64.b64decode(file_data["thumbnail"])
            # Thumbnails are always JPEG
            blob_store.save(make_thumbnail_key(message_id, file_index), thumb_bytes, "image/jpeg")
        except Exception:
            logger.exception(
                "Failed to save thumbnail to blob store",
                extra={"message_id": message_id, "file_index": file_index},
            )


def extract_file_metadata(file_data: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata from file dict, removing binary data.

    Returns a new dict with 'data' and 'thumbnail' removed, plus 'size' added.
    """
    metadata = {}

    # Copy over non-data fields
    for key, value in file_data.items():
        if key not in ("data", "thumbnail"):
            metadata[key] = value

    # Calculate and store size from data
    if "data" in file_data:
        try:
            data_bytes = base64.b64decode(file_data["data"])
            metadata["size"] = len(data_bytes)
        except Exception:
            metadata["size"] = 0

    # Track whether thumbnail exists
    metadata["has_thumbnail"] = bool(file_data.get("thumbnail"))

    return metadata


def delete_message_blobs(message_id: str) -> int:
    """Delete all blobs for a message."""
    blob_store = get_blob_store()
    return blob_store.delete_by_prefix(f"{message_id}/")


def delete_messages_blobs(message_ids: list[str]) -> int:
    """Delete all blobs for multiple messages in a single query.

    More efficient than calling delete_message_blobs() in a loop.
    """
    if not message_ids:
        return 0
    blob_store = get_blob_store()
    prefixes = [f"{msg_id}/" for msg_id in message_ids]
    return blob_store.delete_by_prefixes(prefixes)


# ============================================================================
# Cursor-Based Pagination Helpers
# ============================================================================


def build_cursor(timestamp: str, id: str) -> str:
    """Build a cursor string from timestamp and id.

    Format: '{timestamp}:{id}'
    The id serves as a tie-breaker for items with the same timestamp.
    """
    return f"{timestamp}:{id}"


def parse_cursor(cursor: str) -> tuple[str, str]:
    """Parse a cursor string into (timestamp, id).

    Args:
        cursor: Cursor string in format '{timestamp}:{id}'

    Returns:
        Tuple of (timestamp, id)

    Raises:
        ValueError: If cursor format is invalid
    """
    # Use rsplit with maxsplit=1 to handle timestamps that contain colons
    parts = cursor.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid cursor format: {cursor}")
    return parts[0], parts[1]


# ============================================================================
# Planner Helpers
# ============================================================================


def should_reset_planner(user: "User") -> bool:  # noqa: UP037
    """Check if the planner should be automatically reset.

    The planner resets daily at 4am. This function checks if the last reset
    was before today's 4am cutoff.

    Args:
        user: The User object with planner_last_reset_at field

    Returns:
        True if the planner should be reset, False otherwise
    """
    # If never reset before, this is first use - don't auto-reset
    if not user.planner_last_reset_at:
        return False

    now = datetime.now()

    # Calculate today's 4am cutoff
    today_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)

    # If it's before 4am today, the cutoff is yesterday's 4am
    if now.hour < 4:
        today_4am -= timedelta(days=1)

    # Reset if last reset was before the 4am cutoff
    return user.planner_last_reset_at < today_4am


def check_database_connectivity(db_path: Path | None = None) -> tuple[bool, str | None]:
    """Check if the database is accessible.

    This function performs a series of checks to verify database connectivity
    before starting the application. It checks directory existence, permissions,
    and performs a simple query test.

    Args:
        db_path: Optional path to database file. Uses Config.DATABASE_PATH if not provided.

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    db_path = db_path or Config.DATABASE_PATH
    logger.debug("Checking database connectivity", extra={"db_path": str(db_path)})

    # Check if parent directory exists and is writable
    parent_dir = db_path.parent
    if not parent_dir.exists():
        error = f"Database directory does not exist: {parent_dir}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error

    if not os.access(parent_dir, os.W_OK):
        error = f"Database directory is not writable: {parent_dir}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error

    # Check if database file exists and is accessible
    if db_path.exists():
        if not os.access(db_path, os.R_OK | os.W_OK):
            error = f"Database file is not readable/writable: {db_path}"
            logger.error("Database connectivity check failed", extra={"error": error})
            return False, error

    # Try to connect and run a simple query
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        logger.debug("Database connectivity check passed", extra={"db_path": str(db_path)})
        return True, None
    except sqlite3.OperationalError as e:
        error_msg = str(e)
        if "unable to open database file" in error_msg:
            error = f"Cannot open database file: {db_path}. Check file permissions."
        elif "database is locked" in error_msg:
            error = f"Database is locked: {db_path}. Another process may be using it."
        elif "disk I/O error" in error_msg:
            error = f"Disk I/O error accessing database: {db_path}. Check disk health."
        else:
            error = f"Database error: {error_msg}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error
    except Exception as e:
        error = f"Unexpected database error: {e}"
        logger.error("Database connectivity check failed", extra={"error": error}, exc_info=True)
        return False, error


# Path to migrations directory
MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


@dataclass
class User:
    id: str
    email: str
    name: str
    picture: str | None
    created_at: datetime
    custom_instructions: str | None = None
    todoist_access_token: str | None = None
    todoist_connected_at: datetime | None = None
    google_calendar_access_token: str | None = None
    google_calendar_refresh_token: str | None = None
    google_calendar_token_expires_at: datetime | None = None
    google_calendar_connected_at: datetime | None = None
    google_calendar_email: str | None = None
    google_calendar_selected_ids: list[str] | None = None
    planner_last_reset_at: datetime | None = None


@dataclass
class Conversation:
    id: str
    user_id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    is_planning: bool = False
    last_reset: datetime | None = None  # For planner conversations


@dataclass
class Message:
    id: str
    conversation_id: str
    role: MessageRole
    content: str  # Plain text message
    created_at: datetime
    files: list[dict[str, Any]] = field(default_factory=list)  # File attachments
    sources: list[dict[str, str]] | None = None  # Web sources for assistant messages
    generated_images: list[dict[str, str]] | None = None  # Generated image metadata
    has_cost: bool = False  # Whether cost tracking data exists for this message
    language: str | None = None  # ISO 639-1 language code (e.g., "en", "cs") for TTS


@dataclass
class Memory:
    id: str
    user_id: str
    content: str
    category: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class MessagePagination:
    """Pagination info for messages.

    Contains cursors for navigating in both directions (older and newer messages).
    """

    older_cursor: str | None  # Cursor to fetch older messages
    newer_cursor: str | None  # Cursor to fetch newer messages
    has_older: bool  # True if there are older messages
    has_newer: bool  # True if there are newer messages
    total_count: int  # Total message count in conversation


@dataclass
class SearchResult:
    """A single search result from full-text search.

    Can be either a conversation title match or a message content match.
    """

    conversation_id: str
    conversation_title: str
    message_id: str | None  # None if match is on conversation title
    message_content: str | None  # Snippet with highlight markers
    match_type: str  # "conversation" or "message"
    rank: float  # BM25 relevance score (lower is better)
    created_at: datetime | None  # Message timestamp (None for title matches)


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Config.DATABASE_PATH
        # Query logging is only active in development/debug mode
        self._should_log_queries, self._slow_query_threshold_ms = init_query_logging()
        # Use connection pool for efficient connection reuse
        self._pool = ConnectionPool(self.db_path)
        self._init_db()

    def close(self) -> None:
        """Close all connections in the pool.

        Call this on application shutdown.
        """
        self._pool.close_all()

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute a query with optional timing and logging.

        Delegates to shared execute_with_timing() helper.
        """
        return execute_with_timing(
            conn,
            query,
            params,
            should_log=self._should_log_queries,
            slow_query_threshold_ms=self._slow_query_threshold_ms,
        )

    def _init_db(self) -> None:
        """Run yoyo migrations to initialize/update the database schema."""
        logger.debug("Initializing database", extra={"db_path": str(self.db_path)})
        backend = get_backend(f"sqlite:///{self.db_path}")
        migrations = read_migrations(str(MIGRATIONS_DIR))
        try:
            with backend.lock():
                migrations_to_apply = backend.to_apply(migrations)
                if migrations_to_apply:
                    logger.info(
                        "Applying database migrations", extra={"count": len(migrations_to_apply)}
                    )
                backend.apply_migrations(migrations_to_apply)
        finally:
            backend.connection.close()

    # User operations
    def get_or_create_user(self, email: str, name: str, picture: str | None = None) -> User:
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

    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        """Convert a database row to a Conversation object."""
        # Check if last_reset column exists (added in migration 0021)
        last_reset = None
        if "last_reset" in row.keys():
            last_reset = datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None

        return Conversation(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            model=row["model"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            is_planning=bool(row["is_planning"]) if row["is_planning"] else False,
            last_reset=last_reset,
        )

    def get_user_by_id(self, user_id: str) -> User | None:
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

    # Conversation operations
    def create_conversation(
        self, user_id: str, title: str = "New Conversation", model: str | None = None
    ) -> Conversation:
        conv_id = str(uuid.uuid4())
        model = model or Config.DEFAULT_MODEL
        now = datetime.now()
        logger.debug(
            "Creating conversation",
            extra={"user_id": user_id, "conversation_id": conv_id, "model": model},
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conv_id, user_id, title, model, now.isoformat(), now.isoformat()),
            )
            conn.commit()

        logger.info("Conversation created", extra={"conversation_id": conv_id, "user_id": user_id})
        return Conversation(
            id=conv_id,
            user_id=user_id,
            title=title,
            model=model,
            created_at=now,
            updated_at=now,
        )

    def get_conversation(self, conv_id: str, user_id: str) -> Conversation | None:
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()

            if not row:
                return None

            return self._row_to_conversation(row)

    def list_conversations(
        self, user_id: str, include_planning: bool = False
    ) -> list[Conversation]:
        """List conversations for a user.

        Args:
            user_id: The user ID
            include_planning: If True, includes planning conversations.
                             Default False since planner is fetched separately.

        Returns:
            List of Conversation objects ordered by updated_at DESC
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations WHERE user_id = ?
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations WHERE user_id = ?
                       AND (is_planning = 0 OR is_planning IS NULL)
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [self._row_to_conversation(row) for row in rows]

    def list_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[Conversation], str | None, bool, int]:
        """List conversations for a user with cursor-based pagination.

        Returns conversations ordered by updated_at DESC (most recent first).
        Uses cursor-based pagination with (updated_at, id) as the cursor key.
        Excludes planning conversations (they are fetched separately).

        Args:
            user_id: The user ID
            limit: Maximum number of conversations to return
            cursor: Optional cursor from previous page (format: '{updated_at}:{id}')

        Returns:
            Tuple of:
            - List of Conversation objects
            - Next cursor (None if no more pages)
            - has_more: True if there are more pages
            - total_count: Total number of conversations for this user (excluding planner)
        """
        with self._pool.get_connection() as conn:
            # Get total count for this user (excluding planning conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND (is_planning = 0 OR is_planning IS NULL)""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query based on cursor (excluding planning conversations)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                # Use tuple comparison for stable pagination:
                # (updated_at, id) < (cursor_updated_at, cursor_id)
                # This handles tie-breaking when multiple conversations have the same updated_at
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations
                       WHERE user_id = ?
                         AND (is_planning = 0 OR is_planning IS NULL)
                         AND (updated_at < ? OR (updated_at = ? AND id < ?))
                       ORDER BY updated_at DESC, id DESC
                       LIMIT ?""",
                    (user_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM conversations
                       WHERE user_id = ?
                         AND (is_planning = 0 OR is_planning IS NULL)
                       ORDER BY updated_at DESC, id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            # Check if there are more pages
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            # Build cursor for next page from last item
            next_cursor = None
            if has_more and rows:
                last_row = rows[-1]
                next_cursor = build_cursor(last_row["updated_at"], last_row["id"])

            conversations = [self._row_to_conversation(row) for row in rows]

            return conversations, next_cursor, has_more, total_count

    def list_conversations_paginated_with_counts(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int]], str | None, bool, int]:
        """List conversations for a user with cursor-based pagination and message counts.

        Combines pagination with message counting in a single query for efficiency.
        Returns conversations ordered by updated_at DESC (most recent first).
        Excludes planning conversations (they are fetched separately).

        Args:
            user_id: The user ID
            limit: Maximum number of conversations to return
            cursor: Optional cursor from previous page (format: '{updated_at}:{id}')

        Returns:
            Tuple of:
            - List of (Conversation, message_count) tuples
            - Next cursor (None if no more pages)
            - has_more: True if there are more pages
            - total_count: Total number of conversations for this user (excluding planner)
        """
        with self._pool.get_connection() as conn:
            # Get total count for this user (excluding planning conversations)
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND (is_planning = 0 OR is_planning IS NULL)""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Build the query with JOIN for message counts (excluding planning conversations)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                         AND (c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC, c.id DESC
                       LIMIT ?""",
                    (user_id, limit + 1),
                ).fetchall()

            # Check if there are more pages
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]

            # Build cursor for next page from last item
            next_cursor = None
            if has_more and rows:
                last_row = rows[-1]
                next_cursor = build_cursor(last_row["updated_at"], last_row["id"])

            conversations_with_counts = [
                (self._row_to_conversation(row), int(row["message_count"])) for row in rows
            ]

            return conversations_with_counts, next_cursor, has_more, total_count

    def list_conversations_with_message_count(
        self, user_id: str, include_planning: bool = False
    ) -> list[tuple[Conversation, int]]:
        """List all conversations for a user with message counts.

        This method is used for sync operations to detect unread messages.
        Returns conversations with their message counts for comparison.
        Excludes planning conversations by default (they are fetched separately).

        Args:
            user_id: The user ID
            include_planning: If True, includes planning conversations.
                             Default False since planner is handled separately.

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id,),
                ).fetchall()

            return [(self._row_to_conversation(row), int(row["message_count"])) for row in rows]

    def get_conversations_updated_since(
        self, user_id: str, since: datetime, include_planning: bool = False
    ) -> list[tuple[Conversation, int]]:
        """Get conversations updated since a given timestamp with message counts.

        This method is used for incremental sync operations to fetch only
        conversations that have changed since the last sync.
        Excludes planning conversations by default (they are handled separately).

        Args:
            user_id: The user ID
            since: The timestamp to check against (conversations updated after this)
            include_planning: If True, includes planning conversations.
                             Default False since planner is handled separately.

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._pool.get_connection() as conn:
            if include_planning:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.updated_at > ?
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id, since.isoformat()),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                              c.is_planning, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ? AND c.updated_at > ?
                         AND (c.is_planning = 0 OR c.is_planning IS NULL)
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC""",
                    (user_id, since.isoformat()),
                ).fetchall()

            return [(self._row_to_conversation(row), int(row["message_count"])) for row in rows]

    # Whitelist of allowed columns for update_conversation to prevent SQL injection
    _CONVERSATION_UPDATE_COLUMNS = frozenset({"title", "model"})

    def update_conversation(
        self, conv_id: str, user_id: str, title: str | None = None, model: str | None = None
    ) -> bool:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [datetime.now().isoformat()]

        # Map parameter names to their values (only include non-None values)
        column_values = {"title": title, "model": model}

        for column, value in column_values.items():
            if value is not None:
                if column not in self._CONVERSATION_UPDATE_COLUMNS:
                    raise ValueError(f"Invalid column for update: {column}")
                updates.append(f"{column} = ?")
                params.append(value)

        params.extend([conv_id, user_id])

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        with self._pool.get_connection() as conn:
            # Note: We intentionally keep message_costs even after conversation deletion
            # to preserve accurate cost reporting (the money was already spent)

            # Get message IDs to delete associated blobs
            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()

            # Delete all blobs for these messages in a single query
            message_ids = [row["id"] for row in message_rows]
            delete_messages_blobs(message_ids)

            # Delete messages
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            # Delete conversation
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ============================================================================
    # Planner Operations
    # ============================================================================

    def get_planner_conversation(self, user_id: str) -> Conversation | None:
        """Get the planner conversation for a user without creating it.

        Args:
            user_id: The user ID

        Returns:
            The planner Conversation or None if it doesn't exist
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            return self._row_to_conversation(row) if row else None

    def count_messages(self, conversation_id: str) -> int:
        """Count messages in a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of messages in the conversation
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            return row[0] if row else 0

    def get_or_create_planner_conversation(
        self, user_id: str, model: str | None = None
    ) -> Conversation:
        """Get the planner conversation for a user, creating it if it doesn't exist.

        Each user has exactly one planner conversation (is_planning=1).
        The planner conversation is excluded from search and appears at the top
        of the conversation list.

        Args:
            user_id: The user ID
            model: Optional model to use when creating (defaults to Config.DEFAULT_MODEL)

        Returns:
            The planner Conversation
        """
        logger.debug("Getting or creating planner conversation", extra={"user_id": user_id})

        with self._pool.get_connection() as conn:
            # Try to find existing planner conversation
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            if row:
                logger.debug(
                    "Found existing planner conversation",
                    extra={"user_id": user_id, "conversation_id": row["id"]},
                )
                return self._row_to_conversation(row)

            # Create new planner conversation
            conv_id = str(uuid.uuid4())
            model = model or Config.DEFAULT_MODEL
            now = datetime.now()

            self._execute_with_timing(
                conn,
                """INSERT INTO conversations (id, user_id, title, model, is_planning, created_at, updated_at, last_reset)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    conv_id,
                    user_id,
                    "Planner",
                    model,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()

            # Initialize planner_last_reset_at so auto-reset can work
            self.update_planner_last_reset_at(user_id)

            logger.info(
                "Planner conversation created",
                extra={"conversation_id": conv_id, "user_id": user_id},
            )
            return Conversation(
                id=conv_id,
                user_id=user_id,
                title="Planner",
                model=model,
                created_at=now,
                updated_at=now,
                is_planning=True,
            )

    def reset_planner_conversation(self, user_id: str) -> Conversation | None:
        """Reset the planner conversation by physically deleting all messages.

        This preserves the conversation itself but removes all messages and their
        associated blobs. Message costs are intentionally preserved for accurate
        cost tracking (following the same pattern as delete_conversation).

        Also updates the user's planner_last_reset_at timestamp.

        Args:
            user_id: The user ID

        Returns:
            The planner Conversation (empty), or None if no planner exists
        """
        logger.info("Resetting planner conversation", extra={"user_id": user_id})

        with self._pool.get_connection() as conn:
            # Get the planner conversation
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1",
                (user_id,),
            ).fetchone()

            if not row:
                logger.warning("No planner conversation found to reset", extra={"user_id": user_id})
                return None

            conv_id = row["id"]

            # Get message IDs to delete associated blobs
            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()

            # Delete all blobs for these messages
            message_ids = [r["id"] for r in message_rows]
            if message_ids:
                delete_messages_blobs(message_ids)

            # Delete messages (costs are preserved for accuracy)
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )

            # Update planner_last_reset_at on user
            now = datetime.now()
            self._execute_with_timing(
                conn,
                "UPDATE users SET planner_last_reset_at = ? WHERE id = ?",
                (now.isoformat(), user_id),
            )

            # Update conversation updated_at and last_reset
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ?, last_reset = ? WHERE id = ?",
                (now.isoformat(), now.isoformat(), conv_id),
            )

            conn.commit()

            logger.info(
                "Planner conversation reset",
                extra={
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "messages_deleted": len(message_ids),
                },
            )

            return self._row_to_conversation(row)

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

    def get_planner_conversation_with_auto_reset(
        self, user: User, model: str | None = None
    ) -> tuple[Conversation, bool]:
        """Get the planner conversation, automatically resetting if 4am passed.

        This is the main entry point for accessing the planner. It:
        1. Gets or creates the planner conversation
        2. Checks if auto-reset is needed (4am daily reset)
        3. Performs reset if needed

        Args:
            user: The User object (needed for reset check)
            model: Optional model to use when creating (defaults to Config.DEFAULT_MODEL)

        Returns:
            Tuple of (Conversation, was_reset: bool)
        """
        # Get or create the planner conversation
        conv = self.get_or_create_planner_conversation(user.id, model)

        # Check if auto-reset is needed
        if should_reset_planner(user):
            logger.info(
                "Auto-resetting planner (4am cutoff passed)",
                extra={"user_id": user.id, "conversation_id": conv.id},
            )
            reset_conv = self.reset_planner_conversation(user.id)
            if reset_conv:
                return reset_conv, True
            # Fallback to original if reset failed
            return conv, False

        return conv, False

    # ============================================================================
    # Dashboard Cache Operations
    # ============================================================================

    def get_cached_dashboard(self, user_id: str) -> dict[str, Any] | None:
        """Get cached dashboard if not expired.

        Args:
            user_id: The user ID

        Returns:
            Dashboard data dict if cached and not expired, None otherwise
        """
        import json
        from datetime import datetime

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """
                SELECT dashboard_data, expires_at
                FROM dashboard_cache
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if not row:
                return None

            # Check if expired
            expires_at = datetime.fromisoformat(row[1])
            if datetime.utcnow() >= expires_at:
                # Expired - delete and return None
                self.delete_cached_dashboard(user_id)
                return None

            # Deserialize and return
            result: dict[str, Any] = json.loads(row[0])
            return result

    def cache_dashboard(
        self,
        user_id: str,
        dashboard_data: dict[str, Any],
        ttl_seconds: int = 300,
    ) -> None:
        """Cache dashboard data with TTL.

        Args:
            user_id: The user ID
            dashboard_data: Dashboard data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 300 = 5 minutes)
        """
        import json
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Serialize dashboard
        dashboard_json = json.dumps(dashboard_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT OR REPLACE INTO dashboard_cache
                (user_id, dashboard_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, dashboard_json, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

    def delete_cached_dashboard(self, user_id: str) -> None:
        """Delete cached dashboard for force refresh.

        Args:
            user_id: The user ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

    def cleanup_expired_dashboard_cache(self) -> int:
        """Delete all expired cache entries.

        Returns:
            Number of entries deleted
        """
        from datetime import datetime

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount

    # ============================================================================
    # Calendar Cache Operations
    # ============================================================================

    def get_cached_calendars(self, user_id: str) -> dict[str, Any] | None:
        """Get cached available calendars for a user.

        Args:
            user_id: User ID

        Returns:
            Calendar list data dict if cached and not expired, None otherwise
        """
        import json
        from datetime import datetime

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """
                SELECT calendars_data FROM calendar_cache
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, datetime.now().isoformat()),
            )
            row = cursor.fetchone()

            if row:
                logger.debug("Calendar cache hit", extra={"user_id": user_id})
                calendars_data: dict[str, Any] = json.loads(row["calendars_data"])
                return calendars_data

            logger.debug("Calendar cache miss", extra={"user_id": user_id})
            return None

    def cache_calendars(
        self, user_id: str, calendars_data: dict[str, Any], ttl_seconds: int = 3600
    ) -> None:
        """Cache available calendars for a user.

        Args:
            user_id: User ID
            calendars_data: Calendar list data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 3600 = 1 hour)
        """
        import json
        from datetime import datetime, timedelta

        cached_at = datetime.now()
        expires_at = cached_at + timedelta(seconds=ttl_seconds)
        calendars_json = json.dumps(calendars_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT INTO calendar_cache (user_id, calendars_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    calendars_data = excluded.calendars_data,
                    cached_at = excluded.cached_at,
                    expires_at = excluded.expires_at
                """,
                (user_id, calendars_json, cached_at.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

        logger.debug("Calendars cached", extra={"user_id": user_id, "ttl": ttl_seconds})

    def clear_calendar_cache(self, user_id: str) -> None:
        """Clear calendar cache for a user (e.g., on disconnect/reconnect).

        Args:
            user_id: User ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM calendar_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

        logger.debug("Calendar cache cleared", extra={"user_id": user_id})

    def invalidate_dashboard_cache(self, user_id: str) -> None:
        """Invalidate dashboard cache when calendar selection changes.

        Args:
            user_id: User ID
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM dashboard_cache WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
        logger.debug("Dashboard cache invalidated", extra={"user_id": user_id})

    # ============================================================================
    # Weather Cache Operations
    # ============================================================================

    def get_cached_weather(self, location: str) -> dict[str, Any] | None:
        """Get cached weather forecast if not expired.

        Args:
            location: Location string (e.g., "Prague" or "lat,lon")

        Returns:
            Weather forecast data dict if cached and not expired, None otherwise
        """
        import json
        from datetime import datetime

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """
                SELECT forecast_data, expires_at
                FROM weather_cache
                WHERE location = ?
                """,
                (location,),
            ).fetchone()

            if not row:
                return None

            # Check if expired
            expires_at = datetime.fromisoformat(row[1])
            if datetime.utcnow() >= expires_at:
                # Expired - delete and return None
                self.delete_cached_weather(location)
                return None

            # Deserialize and return
            result: dict[str, Any] = json.loads(row[0])
            return result

    def cache_weather(
        self,
        location: str,
        forecast_data: dict[str, Any],
        ttl_seconds: int = 21600,
    ) -> None:
        """Cache weather forecast data with TTL.

        Args:
            location: Location string (e.g., "Prague" or "lat,lon")
            forecast_data: Weather forecast data dict to cache
            ttl_seconds: Time-to-live in seconds (default: 21600 = 6 hours)
        """
        import json
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Serialize forecast
        forecast_json = json.dumps(forecast_data)

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT OR REPLACE INTO weather_cache
                (location, forecast_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (location, forecast_json, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()

    def delete_cached_weather(self, location: str) -> None:
        """Delete cached weather for force refresh.

        Args:
            location: Location string
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM weather_cache WHERE location = ?",
                (location,),
            )
            conn.commit()

    def cleanup_expired_weather_cache(self) -> int:
        """Delete all expired weather cache entries.

        Returns:
            Number of entries deleted
        """
        from datetime import datetime

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM weather_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount

    def delete_message(self, message_id: str, user_id: str) -> bool:
        """Delete a message by ID.

        Verifies that the message belongs to a conversation owned by the user.
        Also deletes associated blobs (files, thumbnails).
        Note: Message costs are intentionally preserved for accurate reporting.

        Args:
            message_id: The message ID to delete
            user_id: The user ID (for ownership verification)

        Returns:
            True if the message was deleted, False if not found or not owned
        """
        with self._pool.get_connection() as conn:
            # Verify user owns the conversation containing this message
            row = self._execute_with_timing(
                conn,
                """
                SELECT m.id FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE m.id = ? AND c.user_id = ?
                """,
                (message_id, user_id),
            ).fetchone()

            if not row:
                return False

            # Delete associated blobs (files, thumbnails)
            delete_message_blobs(message_id)

            # Delete the message
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM messages WHERE id = ?",
                (message_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    # Message operations
    def add_message(
        self,
        conversation_id: str,
        role: MessageRole | str,
        content: str,
        files: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
        generated_images: list[dict[str, str]] | None = None,
        language: str | None = None,
    ) -> Message:
        """Add a message to a conversation.

        Files are stored in a separate blob store (files.db) to keep the main
        database small and fast. Only file metadata is stored in the messages table.

        Args:
            conversation_id: The conversation ID
            role: MessageRole.USER or MessageRole.ASSISTANT (also accepts "user"/"assistant" strings)
            content: Plain text message
            files: Optional list of file attachments (with 'data' and optional 'thumbnail')
            sources: Optional list of web sources (for assistant messages)
            generated_images: Optional list of generated image metadata (for assistant messages)
            language: Optional ISO 639-1 language code (e.g., "en", "cs") for TTS

        Returns:
            The created Message
        """
        # Normalize role to enum if passed as string
        if isinstance(role, str) and not isinstance(role, MessageRole):
            role = MessageRole(role)
        msg_id = str(uuid.uuid4())
        now = datetime.now()
        files = files or []

        # Extract metadata and save binary data to blob store
        files_metadata: list[dict[str, Any]] = []
        for idx, file_data in enumerate(files):
            # Save file data and thumbnail to blob store
            save_file_to_blob_store(msg_id, idx, file_data)
            # Keep only metadata in the database
            files_metadata.append(extract_file_metadata(file_data))

        files_json = json.dumps(files_metadata) if files_metadata else None
        sources_json = json.dumps(sources) if sources else None
        generated_images_json = json.dumps(generated_images) if generated_images else None
        logger.debug(
            "Adding message",
            extra={
                "conversation_id": conversation_id,
                "message_id": msg_id,
                "role": role,
                "content_length": len(content),
                "file_count": len(files),
                "has_sources": bool(sources),
                "has_generated_images": bool(generated_images),
            },
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO messages (id, conversation_id, role, content, files, sources, generated_images, language, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    conversation_id,
                    role,
                    content,
                    files_json,
                    sources_json,
                    generated_images_json,
                    language,
                    now.isoformat(),
                ),
            )
            # Update conversation's updated_at
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now.isoformat(), conversation_id),
            )
            conn.commit()

        logger.debug(
            "Message added", extra={"message_id": msg_id, "conversation_id": conversation_id}
        )
        return Message(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
            files=files_metadata,
            sources=sources,
            generated_images=generated_images,
            language=language,
        )

    def get_messages(self, conversation_id: str) -> list[Message]:
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()

            return [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in rows
            ]

    def get_messages_paginated(
        self,
        conversation_id: str,
        limit: int = 50,
        cursor: str | None = None,
        direction: PaginationDirection = PaginationDirection.OLDER,
    ) -> tuple[list[Message], MessagePagination]:
        """Get messages for a conversation with cursor-based pagination.

        By default, returns the newest messages (no cursor) or messages
        older/newer than the cursor position.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of messages to return
            cursor: Optional cursor from previous page (format: '{created_at}:{id}')
            direction: PaginationDirection.OLDER to get messages before cursor,
                      PaginationDirection.NEWER for after

        Returns:
            Tuple of:
            - List of Message objects (oldest first within the returned page)
            - MessagePagination info with cursors and flags
        """
        with self._pool.get_connection() as conn:
            # Get total count
            total_row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)

                if direction == PaginationDirection.OLDER:
                    # Fetch messages OLDER than cursor (created_at < cursor_timestamp)
                    # Order by created_at DESC to get the ones just before cursor
                    rows = self._execute_with_timing(
                        conn,
                        """SELECT * FROM messages
                           WHERE conversation_id = ?
                             AND (created_at < ? OR (created_at = ? AND id < ?))
                           ORDER BY created_at DESC, id DESC
                           LIMIT ?""",
                        (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                    ).fetchall()
                else:  # direction == PaginationDirection.NEWER
                    # Fetch messages NEWER than cursor (created_at > cursor_timestamp)
                    # Order by created_at ASC to get the ones just after cursor
                    rows = self._execute_with_timing(
                        conn,
                        """SELECT * FROM messages
                           WHERE conversation_id = ?
                             AND (created_at > ? OR (created_at = ? AND id > ?))
                           ORDER BY created_at ASC, id ASC
                           LIMIT ?""",
                        (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                    ).fetchall()
            else:
                # No cursor: return newest messages (for initial load)
                # Order by created_at DESC to get newest first, then reverse for display
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM messages
                       WHERE conversation_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT ?""",
                    (conversation_id, limit + 1),
                ).fetchall()

            # Check if there are more in the direction we're paginating
            has_more_in_direction = len(rows) > limit
            if has_more_in_direction:
                rows = rows[:limit]

            # Convert rows to Message objects
            messages = [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in rows
            ]

            # For display, we want messages in chronological order (oldest first)
            # When loading older or initial (newest first in query), we need to reverse
            if not cursor or direction == PaginationDirection.OLDER:
                messages = list(reversed(messages))

            # Build pagination info
            if messages:
                # The oldest message in results becomes the "older_cursor"
                first_msg = messages[0]
                older_cursor = build_cursor(first_msg.created_at.isoformat(), first_msg.id)

                # The newest message in results becomes the "newer_cursor"
                last_msg = messages[-1]
                newer_cursor = build_cursor(last_msg.created_at.isoformat(), last_msg.id)
            else:
                older_cursor = None
                newer_cursor = None

            # Determine has_older and has_newer
            if not cursor:
                # Initial load (newest messages): has_older if we got more, has_newer is False
                has_older = has_more_in_direction
                has_newer = False
            elif direction == PaginationDirection.OLDER:
                # Loading older: has_older if we got more, need to check has_newer separately
                has_older = has_more_in_direction
                # There are newer messages if we had a cursor (we came from somewhere)
                has_newer = True
            else:  # direction == PaginationDirection.NEWER
                # Loading newer: has_newer if we got more, has_older is True (we came from somewhere)
                has_newer = has_more_in_direction
                has_older = True

            pagination = MessagePagination(
                older_cursor=older_cursor if has_older else None,
                newer_cursor=newer_cursor if has_newer else None,
                has_older=has_older,
                has_newer=has_newer,
                total_count=total_count,
            )

            return messages, pagination

    def get_messages_around(
        self,
        conversation_id: str,
        message_id: str,
        before_limit: int = 25,
        after_limit: int = 25,
    ) -> tuple[list[Message], MessagePagination] | None:
        """Get messages around a specific message.

        Loads messages before and after the target message to create a "window"
        centered on the target. Used for efficient search result navigation.

        Args:
            conversation_id: The conversation ID
            message_id: The target message ID to center around
            before_limit: Number of messages to load before the target (inclusive)
            after_limit: Number of messages to load after the target

        Returns:
            Tuple of (messages, pagination) or None if message not found.
            Messages are returned in chronological order (oldest first).
            Pagination includes both older_cursor and newer_cursor for
            bi-directional pagination from the loaded window.
        """
        with self._pool.get_connection() as conn:
            # Get total count
            total_row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Get the target message to verify it exists and get its timestamp
            target_row = self._execute_with_timing(
                conn,
                "SELECT id, created_at FROM messages WHERE id = ? AND conversation_id = ?",
                (message_id, conversation_id),
            ).fetchone()

            if not target_row:
                return None

            target_timestamp = target_row["created_at"]
            target_id = target_row["id"]

            # Get messages before and including the target
            # (created_at < target) OR (created_at = target AND id <= target_id)
            # Order DESC to get the closest ones, then reverse
            before_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at < ? OR (created_at = ? AND id <= ?))
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, before_limit + 1),
            ).fetchall()

            # Check if there are older messages beyond what we fetched
            has_older = len(before_rows) > before_limit
            if has_older:
                before_rows = before_rows[:before_limit]

            # Get messages after the target (excluding target itself)
            # (created_at > target) OR (created_at = target AND id > target_id)
            after_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at > ? OR (created_at = ? AND id > ?))
                   ORDER BY created_at ASC, id ASC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, after_limit + 1),
            ).fetchall()

            # Check if there are newer messages beyond what we fetched
            has_newer = len(after_rows) > after_limit
            if has_newer:
                after_rows = after_rows[:after_limit]

            # Combine: reverse before_rows (they're DESC) + after_rows (already ASC)
            all_rows = list(reversed(before_rows)) + list(after_rows)

            # Convert to Message objects
            messages = [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in all_rows
            ]

            # Build pagination cursors
            if messages:
                first_msg = messages[0]
                older_cursor = build_cursor(first_msg.created_at.isoformat(), first_msg.id)

                last_msg = messages[-1]
                newer_cursor = build_cursor(last_msg.created_at.isoformat(), last_msg.id)
            else:
                older_cursor = None
                newer_cursor = None

            pagination = MessagePagination(
                older_cursor=older_cursor if has_older else None,
                newer_cursor=newer_cursor if has_newer else None,
                has_older=has_older,
                has_newer=has_newer,
                total_count=total_count,
            )

            return messages, pagination

    def get_message_by_id(self, message_id: str) -> Message | None:
        """Get a single message by its ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

            if not row:
                return None

            return Message(
                id=row["id"],
                conversation_id=row["conversation_id"],
                role=MessageRole(row["role"]),
                content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"]),
                files=json.loads(row["files"]) if row["files"] else [],
                sources=json.loads(row["sources"]) if row["sources"] else None,
                generated_images=json.loads(row["generated_images"])
                if row["generated_images"]
                else None,
                language=row["language"],
            )

    def update_message_file_thumbnail(
        self,
        message_id: str,
        file_index: int,
        thumbnail: str | None,
        status: ThumbnailStatus = ThumbnailStatus.READY,
    ) -> bool:
        """Update thumbnail for a specific file in a message.

        Used by background thumbnail generation to update the thumbnail
        after the message has been saved. The thumbnail is saved to the blob store
        and only the status is updated in the message metadata.

        Args:
            message_id: ID of the message
            file_index: Index of the file in the files array
            thumbnail: Base64-encoded thumbnail data (or None if generation failed)
            status: ThumbnailStatus.READY or ThumbnailStatus.FAILED

        Returns:
            True if updated successfully, False if message not found or index out of range
        """
        logger.debug(
            "Updating message file thumbnail",
            extra={"message_id": message_id, "file_index": file_index, "status": status.value},
        )

        with self._pool.get_connection() as conn:
            # Get current files JSON
            cursor = self._execute_with_timing(
                conn,
                "SELECT files FROM messages WHERE id = ?",
                (message_id,),
            )
            row = cursor.fetchone()

            if not row or not row["files"]:
                logger.warning(
                    "Message not found or has no files",
                    extra={"message_id": message_id, "file_index": file_index},
                )
                return False

            files = json.loads(row["files"])

            # Validate file index
            if file_index < 0 or file_index >= len(files):
                logger.warning(
                    "File index out of range",
                    extra={
                        "message_id": message_id,
                        "file_index": file_index,
                        "files_count": len(files),
                    },
                )
                return False

            # Save thumbnail to blob store if provided
            if thumbnail:
                try:
                    thumb_bytes = base64.b64decode(thumbnail)
                    blob_store = get_blob_store()
                    blob_store.save(
                        make_thumbnail_key(message_id, file_index), thumb_bytes, "image/jpeg"
                    )
                    files[file_index]["has_thumbnail"] = True
                except Exception:
                    logger.exception(
                        "Failed to save thumbnail to blob store",
                        extra={"message_id": message_id, "file_index": file_index},
                    )
                    status = ThumbnailStatus.FAILED
                    files[file_index]["has_thumbnail"] = False
            else:
                files[file_index]["has_thumbnail"] = False

            # Update status in metadata (no longer storing thumbnail in JSON)
            files[file_index]["thumbnail_status"] = status.value

            # Save back to database
            self._execute_with_timing(
                conn,
                "UPDATE messages SET files = ? WHERE id = ?",
                (json.dumps(files), message_id),
            )
            conn.commit()

            logger.debug(
                "Message file thumbnail updated",
                extra={"message_id": message_id, "file_index": file_index, "status": status.value},
            )
            return True

    # Cost tracking operations
    def save_message_cost(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        image_generation_cost_usd: float = 0.0,
    ) -> None:
        """Save cost information for a message.

        Args:
            message_id: The message ID
            conversation_id: The conversation ID
            user_id: The user ID
            model: The model used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_usd: Total cost in USD
            image_generation_cost_usd: Cost for image generation in USD (default 0.0)
        """
        cost_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        logger.debug(
            "Saving message cost",
            extra={
                "message_id": message_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            },
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO message_costs (
                    id, message_id, conversation_id, user_id, model,
                    input_tokens, output_tokens, cost_usd, image_generation_cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cost_id,
                    message_id,
                    conversation_id,
                    user_id,
                    model,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    image_generation_cost_usd,
                    now,
                ),
            )
            conn.commit()

        logger.debug("Message cost saved", extra={"cost_id": cost_id, "message_id": message_id})

    def get_message_cost(self, message_id: str) -> dict[str, Any] | None:
        """Get cost information for a specific message.

        Args:
            message_id: The message ID

        Returns:
            Dict with 'cost_usd', 'input_tokens', 'output_tokens', 'model', 'image_generation_cost_usd', or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT cost_usd, input_tokens, output_tokens, model, image_generation_cost_usd
                   FROM message_costs
                   WHERE message_id = ?""",
                (message_id,),
            ).fetchone()

            if not row:
                return None

            return {
                "cost_usd": float(row["cost_usd"] or 0.0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "model": row["model"],
                "image_generation_cost_usd": float(
                    row["image_generation_cost_usd"]
                    if row["image_generation_cost_usd"] is not None
                    else 0.0
                ),
            }

    def get_conversation_cost(self, conversation_id: str) -> float:
        """Get total cost for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Total cost in USD
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT SUM(cost_usd) as total FROM message_costs WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            return float(row["total"] or 0.0) if row else 0.0

    def get_user_monthly_cost(self, user_id: str, year: int, month: int) -> dict[str, Any]:
        """Get cost for a user in a specific month.

        Args:
            user_id: The user ID
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            Dict with 'total_usd', 'message_count', and 'breakdown' (by model)

        Raises:
            ValueError: If month is not in range 1-12
        """
        # Validate month range
        if not (1 <= month <= 12):
            raise ValueError(f"Month must be between 1 and 12, got {month}")

        # Build date range for the month
        start_date = datetime(year, month, 1).isoformat()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).isoformat()
        else:
            end_date = datetime(year, month + 1, 1).isoformat()

        with self._pool.get_connection() as conn:
            # Get total cost and message count
            total_row = self._execute_with_timing(
                conn,
                """SELECT SUM(cost_usd) as total, COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ? AND created_at >= ? AND created_at < ?""",
                (user_id, start_date, end_date),
            ).fetchone()

            # Get breakdown by model
            breakdown_rows = self._execute_with_timing(
                conn,
                """SELECT model, SUM(cost_usd) as total, COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ? AND created_at >= ? AND created_at < ?
                   GROUP BY model""",
                (user_id, start_date, end_date),
            ).fetchall()

            total_usd = float(total_row["total"] or 0.0) if total_row else 0.0
            message_count = int(total_row["count"] or 0) if total_row else 0

            breakdown = {
                row["model"]: {
                    "total_usd": float(row["total"] or 0.0),
                    "message_count": int(row["count"] or 0),
                }
                for row in breakdown_rows
            }

            return {
                "total_usd": total_usd,
                "message_count": message_count,
                "breakdown": breakdown,
            }

    def get_user_cost_history(self, user_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Get monthly cost history for a user.

        Args:
            user_id: The user ID
            limit: Number of months to return (default 12)

        Returns:
            List of dicts with 'year', 'month', 'total_usd', 'message_count'
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT
                    strftime('%Y', created_at) as year,
                    strftime('%m', created_at) as month,
                    SUM(cost_usd) as total,
                    COUNT(*) as count
                   FROM message_costs
                   WHERE user_id = ?
                   GROUP BY year, month
                   ORDER BY year DESC, month DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()

            # Sort from current month to oldest (reverse chronological)
            # The database query already returns DESC, but we ensure proper sorting

            return [
                {
                    "year": int(row["year"]),
                    "month": int(row["month"]),
                    "total_usd": float(row["total"] or 0.0),
                    "message_count": int(row["count"] or 0),
                }
                for row in rows
            ]

    # Memory operations
    def add_memory(self, user_id: str, content: str, category: str | None = None) -> Memory:
        """Add a memory for a user.

        Args:
            user_id: The user ID
            content: The memory content
            category: Optional category (preference, fact, context, goal)

        Returns:
            The created Memory
        """
        memory_id = str(uuid.uuid4())
        now = datetime.now()
        logger.debug(
            "Adding memory",
            extra={"user_id": user_id, "memory_id": memory_id, "category": category},
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO user_memories (id, user_id, content, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (memory_id, user_id, content, category, now.isoformat(), now.isoformat()),
            )
            conn.commit()

        logger.info("Memory added", extra={"memory_id": memory_id, "user_id": user_id})
        return Memory(
            id=memory_id,
            user_id=user_id,
            content=content,
            category=category,
            created_at=now,
            updated_at=now,
        )

    def update_memory(
        self, memory_id: str, user_id: str, content: str, category: str | None = None
    ) -> bool:
        """Update a memory's content.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)
            content: New content
            category: Optional new category

        Returns:
            True if memory was updated, False if not found
        """
        now = datetime.now().isoformat()
        logger.debug(
            "Updating memory",
            extra={"user_id": user_id, "memory_id": memory_id},
        )

        with self._pool.get_connection() as conn:
            if category is not None:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE user_memories SET content = ?, category = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (content, category, now, memory_id, user_id),
                )
            else:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE user_memories SET content = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (content, now, memory_id, user_id),
                )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info("Memory updated", extra={"memory_id": memory_id, "user_id": user_id})
        else:
            logger.warning(
                "Memory not found for update",
                extra={"memory_id": memory_id, "user_id": user_id},
            )
        return updated

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)

        Returns:
            True if memory was deleted, False if not found
        """
        logger.debug(
            "Deleting memory",
            extra={"user_id": user_id, "memory_id": memory_id},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM user_memories WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Memory deleted", extra={"memory_id": memory_id, "user_id": user_id})
        else:
            logger.warning(
                "Memory not found for deletion",
                extra={"memory_id": memory_id, "user_id": user_id},
            )
        return deleted

    def list_memories(self, user_id: str) -> list[Memory]:
        """List all memories for a user.

        Args:
            user_id: The user ID

        Returns:
            List of Memory objects, ordered by updated_at DESC
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_memories WHERE user_id = ?
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()

            return [
                Memory(
                    id=row["id"],
                    user_id=row["user_id"],
                    content=row["content"],
                    category=row["category"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def get_memory_count(self, user_id: str) -> int:
        """Get the count of memories for a user.

        Args:
            user_id: The user ID

        Returns:
            Number of memories
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM user_memories WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def get_users_with_memory_counts(self, min_memories: int = 0) -> list[tuple[User, int]]:
        """Get all users with their memory counts.

        Used by memory defragmentation to find users who need cleanup.

        Args:
            min_memories: Only return users with at least this many memories

        Returns:
            List of (User, memory_count) tuples, ordered by memory count descending
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """
                SELECT u.*, COUNT(m.id) as memory_count
                FROM users u
                LEFT JOIN user_memories m ON u.id = m.user_id
                GROUP BY u.id
                HAVING COUNT(m.id) >= ?
                ORDER BY memory_count DESC
                """,
                (min_memories,),
            ).fetchall()

            return [
                (
                    User(
                        id=row["id"],
                        email=row["email"],
                        name=row["name"],
                        picture=row["picture"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        custom_instructions=row["custom_instructions"],
                    ),
                    int(row["memory_count"]),
                )
                for row in rows
            ]

    def bulk_update_memories(
        self,
        user_id: str,
        to_delete: list[str],
        to_update: list[tuple[str, str, str | None]],
        to_add: list[tuple[str, str | None]],
    ) -> dict[str, int]:
        """Bulk update memories for a user (used by defragmentation).

        Performs deletions, updates, and additions in a single transaction.

        Args:
            user_id: The user ID
            to_delete: List of memory IDs to delete
            to_update: List of (memory_id, new_content, category) tuples
            to_add: List of (content, category) tuples for new memories

        Returns:
            Dict with counts: {"deleted": N, "updated": N, "added": N}
        """
        now = datetime.utcnow().isoformat()
        result = {"deleted": 0, "updated": 0, "added": 0}

        with self._pool.get_connection() as conn:
            # Delete memories
            for memory_id in to_delete:
                cursor = self._execute_with_timing(
                    conn,
                    "DELETE FROM user_memories WHERE id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
                result["deleted"] += cursor.rowcount

            # Update memories
            for memory_id, content, category in to_update:
                cursor = self._execute_with_timing(
                    conn,
                    """
                    UPDATE user_memories
                    SET content = ?, category = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (content, category, now, memory_id, user_id),
                )
                result["updated"] += cursor.rowcount

            # Add new memories
            for content, category in to_add:
                memory_id = str(uuid.uuid4())
                self._execute_with_timing(
                    conn,
                    """
                    INSERT INTO user_memories (id, user_id, content, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (memory_id, user_id, content, category, now, now),
                )
                result["added"] += 1

            conn.commit()

        logger.info(
            "Bulk memory update completed",
            extra={
                "user_id": user_id,
                "deleted": result["deleted"],
                "updated": result["updated"],
                "added": result["added"],
            },
        )

        return result

    # ============================================================================
    # Full-Text Search
    # ============================================================================

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SearchResult], int]:
        """Search conversations and messages using FTS5 full-text search.

        Uses BM25 ranking algorithm for relevance scoring. Searches both
        conversation titles and message content. Results are ordered by
        relevance (best matches first).

        The query supports prefix matching - each word is automatically
        treated as a prefix (e.g., "hel wor" matches "hello world").

        Args:
            user_id: The user ID (only searches this user's data)
            query: Search query text
            limit: Maximum number of results to return (default: 20)
            offset: Number of results to skip for pagination (default: 0)

        Returns:
            Tuple of:
            - List of SearchResult objects ordered by relevance
            - Total count of matching results (for pagination UI)
        """
        # Clean and validate query
        query = query.strip()
        if not query:
            return [], 0

        # Escape FTS5 special characters to prevent query syntax errors
        # FTS5 special chars: " * ( ) : ^ -
        escaped_query = query.replace('"', '""')

        # Build prefix-matching query: "hello world" -> "hello"* "world"*
        # This provides better type-ahead search experience
        words = escaped_query.split()
        fts_query = " ".join(f'"{word}"*' for word in words if word)

        if not fts_query:
            return [], 0

        with self._pool.get_connection() as conn:
            # Get ranked results with conversation titles
            # bm25() returns negative scores where more negative = better match
            # snippet() returns text with highlight markers around matches
            #
            # Note: We fetch ALL matching results and deduplicate in Python because:
            # 1. FTS5's bm25() and snippet() functions don't work with GROUP BY
            # 2. The search index may have duplicate entries for the same message
            # 3. We need accurate total counts after deduplication
            rows = self._execute_with_timing(
                conn,
                """
                SELECT
                    si.conversation_id,
                    c.title as conversation_title,
                    si.message_id,
                    CASE
                        WHEN si.type = 'message' THEN snippet(
                            search_index, 5, '[[HIGHLIGHT]]', '[[/HIGHLIGHT]]', '...', 32
                        )
                        ELSE NULL
                    END as message_snippet,
                    si.type as match_type,
                    bm25(search_index) as rank,
                    m.created_at as message_created_at
                FROM search_index si
                JOIN conversations c ON c.id = si.conversation_id
                LEFT JOIN messages m ON m.id = si.message_id
                WHERE si.user_id = ? AND search_index MATCH ?
                ORDER BY rank ASC, message_created_at DESC NULLS LAST
                """,
                (user_id, fts_query),
            ).fetchall()

            if not rows:
                return [], 0

            # Deduplicate results in Python by message_id (for message matches)
            # or conversation_id (for title matches). This handles duplicate
            # index entries that can occur due to trigger timing or other issues.
            seen: set[str] = set()
            unique_results: list[SearchResult] = []

            for row in rows:
                # Use message_id as unique key for message matches,
                # conversation_id for title matches
                unique_key = row["message_id"] or row["conversation_id"]
                if unique_key in seen:
                    continue
                seen.add(unique_key)

                unique_results.append(
                    SearchResult(
                        conversation_id=row["conversation_id"],
                        conversation_title=row["conversation_title"],
                        message_id=row["message_id"],
                        message_content=row["message_snippet"],
                        match_type=row["match_type"],
                        rank=float(row["rank"]),
                        created_at=(
                            datetime.fromisoformat(row["message_created_at"])
                            if row["message_created_at"]
                            else None
                        ),
                    )
                )

            # Total count is the number of unique results
            total_count = len(unique_results)

            # Apply pagination after deduplication
            paginated_results = unique_results[offset : offset + limit]

            logger.debug(
                "Search completed",
                extra={
                    "user_id": user_id,
                    "query": query,
                    "results": len(paginated_results),
                    "total": total_count,
                },
            )

            return paginated_results, total_count

    # ============================================================================
    # App Settings
    # ============================================================================

    def get_setting(self, key: str) -> str | None:
        """Get an application setting by key.

        Args:
            key: The setting key

        Returns:
            The setting value, or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()

            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set an application setting.

        Args:
            key: The setting key
            value: The setting value (must be a string, use JSON for complex values)
        """
        now = datetime.utcnow().isoformat()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                (key, value, now, value, now),
            )
            conn.commit()
            logger.debug("Setting updated", extra={"key": key})

    def get_currency_rates(self) -> dict[str, float] | None:
        """Get currency rates from the database.

        Returns:
            Dictionary of currency code to rate, or None if not set
        """
        value = self.get_setting("currency_rates")
        if value:
            try:
                rates: dict[str, float] = json.loads(value)
                return rates
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in currency_rates setting")
        return None

    def set_currency_rates(self, rates: dict[str, float]) -> None:
        """Set currency rates in the database.

        Args:
            rates: Dictionary of currency code to rate (USD base)
        """
        self.set_setting("currency_rates", json.dumps(rates))
        logger.info("Currency rates updated", extra={"rates": rates})


# Global database instance
db = Database()
