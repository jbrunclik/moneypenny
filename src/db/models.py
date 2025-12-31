import json
import os
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from yoyo import get_backend, read_migrations

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


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


@dataclass
class Conversation:
    id: str
    user_id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str  # "user" or "assistant"
    content: str  # Plain text message
    created_at: datetime
    files: list[dict[str, Any]] = field(default_factory=list)  # File attachments
    sources: list[dict[str, str]] | None = None  # Web sources for assistant messages
    generated_images: list[dict[str, str]] | None = None  # Generated image metadata
    has_cost: bool = False  # Whether cost tracking data exists for this message


@dataclass
class Memory:
    id: str
    user_id: str
    content: str
    category: str | None
    created_at: datetime
    updated_at: datetime


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Config.DATABASE_PATH
        # Query logging is only active in development/debug mode
        self._should_log_queries = Config.LOG_LEVEL == "DEBUG" or Config.is_development()
        self._slow_query_threshold_ms = Config.SLOW_QUERY_THRESHOLD_MS
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute a query with optional timing and logging.

        In development/debug mode, this method tracks query execution time
        and logs warnings for slow queries.

        Args:
            conn: SQLite connection
            query: SQL query string
            params: Query parameters

        Returns:
            SQLite cursor with results
        """
        if not self._should_log_queries:
            return conn.execute(query, params)

        start_time = time.perf_counter()
        cursor = conn.execute(query, params)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Truncate query for logging (normalize whitespace)
        query_snippet = " ".join(query.split())
        if len(query_snippet) > 200:
            query_snippet = query_snippet[:200] + "..."

        # Truncate params for logging (avoid logging large data like base64 files)
        params_str = str(params)
        if len(params_str) > 100:
            params_snippet = params_str[:100] + "..."
        else:
            params_snippet = params_str

        if elapsed_ms >= self._slow_query_threshold_ms:
            logger.warning(
                "Slow query detected",
                extra={
                    "query_snippet": query_snippet,
                    "params_snippet": params_snippet,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "threshold_ms": self._slow_query_threshold_ms,
                },
            )
        elif Config.LOG_LEVEL == "DEBUG":
            logger.debug(
                "Query executed",
                extra={
                    "query_snippet": query_snippet,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )

        return cursor

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
        with self._get_conn() as conn:
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
            return User(
                id=row["id"],
                email=row["email"],
                name=row["name"],
                picture=row["picture"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def get_user_by_id(self, user_id: str) -> User | None:
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn, "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()

            if not row:
                return None

            return User(
                id=row["id"],
                email=row["email"],
                name=row["name"],
                picture=row["picture"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

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

        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()

            if not row:
                return None

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                model=row["model"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_conversations(self, user_id: str) -> list[Conversation]:
        with self._get_conn() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM conversations WHERE user_id = ?
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()

            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    model=row["model"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def list_conversations_with_message_count(self, user_id: str) -> list[tuple[Conversation, int]]:
        """List all conversations for a user with message counts.

        This method is used for sync operations to detect unread messages.
        Returns conversations with their message counts for comparison.

        Args:
            user_id: The user ID

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._get_conn() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                          COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ?
                   GROUP BY c.id
                   ORDER BY c.updated_at DESC""",
                (user_id,),
            ).fetchall()

            return [
                (
                    Conversation(
                        id=row["id"],
                        user_id=row["user_id"],
                        title=row["title"],
                        model=row["model"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                    ),
                    int(row["message_count"]),
                )
                for row in rows
            ]

    def get_conversations_updated_since(
        self, user_id: str, since: datetime
    ) -> list[tuple[Conversation, int]]:
        """Get conversations updated since a given timestamp with message counts.

        This method is used for incremental sync operations to fetch only
        conversations that have changed since the last sync.

        Args:
            user_id: The user ID
            since: The timestamp to check against (conversations updated after this)

        Returns:
            List of tuples containing (Conversation, message_count)
        """
        with self._get_conn() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT c.id, c.user_id, c.title, c.model, c.created_at, c.updated_at,
                          COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.updated_at > ?
                   GROUP BY c.id
                   ORDER BY c.updated_at DESC""",
                (user_id, since.isoformat()),
            ).fetchall()

            return [
                (
                    Conversation(
                        id=row["id"],
                        user_id=row["user_id"],
                        title=row["title"],
                        model=row["model"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                    ),
                    int(row["message_count"]),
                )
                for row in rows
            ]

    def update_conversation(
        self, conv_id: str, user_id: str, title: str | None = None, model: str | None = None
    ) -> bool:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [datetime.now().isoformat()]

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if model is not None:
            updates.append("model = ?")
            params.append(model)

        params.extend([conv_id, user_id])

        with self._get_conn() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        with self._get_conn() as conn:
            # Note: We intentionally keep message_costs even after conversation deletion
            # to preserve accurate cost reporting (the money was already spent)
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

    # Message operations
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        files: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
        generated_images: list[dict[str, str]] | None = None,
    ) -> Message:
        """Add a message to a conversation.

        Args:
            conversation_id: The conversation ID
            role: "user" or "assistant"
            content: Plain text message
            files: Optional list of file attachments
            sources: Optional list of web sources (for assistant messages)
            generated_images: Optional list of generated image metadata (for assistant messages)

        Returns:
            The created Message
        """
        msg_id = str(uuid.uuid4())
        now = datetime.now()
        files = files or []
        files_json = json.dumps(files) if files else None
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

        with self._get_conn() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO messages (id, conversation_id, role, content, files, sources, generated_images, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    conversation_id,
                    role,
                    content,
                    files_json,
                    sources_json,
                    generated_images_json,
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
            files=files,
            sources=sources,
            generated_images=generated_images,
        )

    def get_messages(self, conversation_id: str) -> list[Message]:
        with self._get_conn() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()

            return [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=row["role"],
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                )
                for row in rows
            ]

    def get_message_by_id(self, message_id: str) -> Message | None:
        """Get a single message by its ID."""
        with self._get_conn() as conn:
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
                role=row["role"],
                content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"]),
                files=json.loads(row["files"]) if row["files"] else [],
                sources=json.loads(row["sources"]) if row["sources"] else None,
                generated_images=json.loads(row["generated_images"])
                if row["generated_images"]
                else None,
            )

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

        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
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

        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
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

        with self._get_conn() as conn:
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

        with self._get_conn() as conn:
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

        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM user_memories WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            return int(row["count"]) if row else 0


# Global database instance
db = Database()
