import json
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from yoyo import get_backend, read_migrations

from src.config import Config

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
    details: list[dict[str, Any]] | None = None  # Thinking/tool events (assistant only)


@dataclass
class AgentState:
    conversation_id: str
    state_json: str
    updated_at: datetime


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Config.DATABASE_PATH
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Run yoyo migrations to initialize/update the database schema."""
        backend = get_backend(f"sqlite:///{self.db_path}")
        migrations = read_migrations(str(MIGRATIONS_DIR))
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))

    # User operations
    def get_or_create_user(self, email: str, name: str, picture: str | None = None) -> User:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    name=row["name"],
                    picture=row["picture"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )

            user_id = str(uuid.uuid4())
            now = datetime.now()
            conn.execute(
                "INSERT INTO users (id, email, name, picture, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, name, picture, now.isoformat()),
            )
            conn.commit()

            return User(
                id=user_id,
                email=email,
                name=name,
                picture=picture,
                created_at=now,
            )

    def get_user_by_id(self, user_id: str) -> User | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

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

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conv_id, user_id, title, model, now.isoformat(), now.isoformat()),
            )
            conn.commit()

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
            row = conn.execute(
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
            rows = conn.execute(
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
            cursor = conn.execute(
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        with self._get_conn() as conn:
            # Delete messages first
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            # Delete agent state
            conn.execute("DELETE FROM agent_states WHERE conversation_id = ?", (conv_id,))
            # Delete conversation
            cursor = conn.execute(
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
        details: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Add a message to a conversation.

        Args:
            conversation_id: The conversation ID
            role: "user" or "assistant"
            content: Plain text message
            files: Optional list of file attachments
            details: Optional list of detail events (thinking/tool calls for assistant)

        Returns:
            The created Message
        """
        msg_id = str(uuid.uuid4())
        now = datetime.now()
        files = files or []
        files_json = json.dumps(files) if files else None
        details_json = json.dumps(details) if details else None

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO messages (id, conversation_id, role, content, files, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, conversation_id, role, content, files_json, details_json, now.isoformat()),
            )
            # Update conversation's updated_at
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now.isoformat(), conversation_id),
            )
            conn.commit()

        return Message(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
            files=files,
            details=details,
        )

    def get_messages(self, conversation_id: str, include_details: bool = False) -> list[Message]:
        """Get all messages for a conversation.

        Args:
            conversation_id: The conversation ID
            include_details: If True, include full details. If False, details is None
                           (use has_details() to check if details exist for lazy loading)
        """
        with self._get_conn() as conn:
            rows = conn.execute(
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
                    details=json.loads(row["details"])
                    if include_details and row["details"]
                    else None,
                )
                for row in rows
            ]

    def has_details(self, message_id: str) -> bool:
        """Check if a message has details (for lazy loading indicator)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT details IS NOT NULL AND details != '[]' as has_details FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            return bool(row and row["has_details"])

    def get_message_details(self, message_id: str) -> list[dict[str, Any]] | None:
        """Get just the details for a message (for lazy loading)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT details FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

            if not row or not row["details"]:
                return None

            return json.loads(row["details"])  # type: ignore[no-any-return]

    def get_message_by_id(self, message_id: str) -> Message | None:
        """Get a single message by its ID (includes full details)."""
        with self._get_conn() as conn:
            row = conn.execute(
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
                details=json.loads(row["details"]) if row["details"] else None,
            )

    # Agent state operations
    def save_agent_state(self, conversation_id: str, state: dict[str, Any]) -> None:
        state_json = json.dumps(state)
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO agent_states (conversation_id, state_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                   state_json = excluded.state_json,
                   updated_at = excluded.updated_at""",
                (conversation_id, state_json, now),
            )
            conn.commit()

    def get_agent_state(self, conversation_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT state_json FROM agent_states WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            if not row:
                return None

            return json.loads(row["state_json"])  # type: ignore[no-any-return]


# Global database instance
db = Database()
