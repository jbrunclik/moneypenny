"""Database models package.

This package provides the Database class and all related dataclasses.
The Database class is composed of mixins for different entity operations.

Usage:
    from src.db.models import Database, User, Conversation, Message, db

    # Use the global instance
    user = db.get_user_by_id("user-123")

    # Or create your own instance
    custom_db = Database(custom_path)
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from src.db.models.admin import AdminMixin
from src.db.models.agent import AgentMixin
from src.db.models.agent_approvals import AgentApprovalMixin
from src.db.models.agent_conversation import AgentConversationMixin
from src.db.models.agent_executions import AgentExecutionMixin
from src.db.models.agent_schedule import AgentScheduleMixin
from src.db.models.agent_stats import AgentStatsMixin
from src.db.models.artifacts import ArtifactMixin
from src.db.models.base import DatabaseBase
from src.db.models.cache import CacheMixin
from src.db.models.client_errors import ClientErrorsMixin
from src.db.models.conversation import ConversationMixin
from src.db.models.conversation_archive import ConversationArchiveMixin
from src.db.models.conversation_listing import ConversationListingMixin
from src.db.models.conversation_trash import ConversationTrashMixin
from src.db.models.cost import CostMixin
from src.db.models.dataclasses import (
    Agent,
    AgentExecution,
    ApprovalRequest,
    Conversation,
    Memory,
    Message,
    MessagePagination,
    PushSubscription,
    SearchResult,
    User,
)
from src.db.models.device_checks import DeviceChecksMixin
from src.db.models.embeddings import EmbeddingsMixin
from src.db.models.helpers import (
    build_cursor,
    check_database_connectivity,
    check_database_writable,
    delete_message_blobs,
    delete_messages_blobs,
    extract_file_metadata,
    make_blob_key,
    make_thumbnail_key,
    parse_cursor,
    save_file_to_blob_store,
    should_reset_planner,
)
from src.db.models.kv_store import KVStoreMixin
from src.db.models.memory import MemoryMixin
from src.db.models.message import MessageMixin
from src.db.models.message_files import MessageFileMixin
from src.db.models.message_pagination import MessagePaginationMixin
from src.db.models.planner import PlannerMixin
from src.db.models.programs import ProgramConversationMixin
from src.db.models.push import PushSubscriptionMixin
from src.db.models.search import SearchMixin
from src.db.models.settings import SettingsMixin
from src.db.models.stream_journal import StreamJournalMixin
from src.db.models.sync_changes import ConversationChange, SyncChangesMixin
from src.db.models.user import UserMixin
from src.db.models.user_integrations import UserIntegrationsMixin
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Database(
    DatabaseBase,
    UserMixin,
    UserIntegrationsMixin,
    ConversationMixin,
    ConversationListingMixin,
    ConversationArchiveMixin,
    ConversationTrashMixin,
    MessageMixin,
    MessagePaginationMixin,
    MessageFileMixin,
    MemoryMixin,
    PlannerMixin,
    CacheMixin,
    CostMixin,
    SearchMixin,
    SettingsMixin,
    AgentMixin,
    AgentScheduleMixin,
    AgentApprovalMixin,
    AgentExecutionMixin,
    AgentConversationMixin,
    AgentStatsMixin,
    KVStoreMixin,
    EmbeddingsMixin,
    ProgramConversationMixin,
    PushSubscriptionMixin,
    StreamJournalMixin,
    SyncChangesMixin,
    ArtifactMixin,
    AdminMixin,
    ClientErrorsMixin,
    DeviceChecksMixin,
):
    """Main database class combining all mixins.

    Provides all database operations through a unified interface.
    Uses connection pooling for efficient database access.
    """

    def __init__(self, db_path: Path | None = None, *, apply_migrations: bool = True) -> None:
        """Initialize the database.

        Args:
            db_path: Optional path to the database file.
                    Defaults to Config.DATABASE_PATH.
            apply_migrations: Apply pending migrations now (see DatabaseBase).
        """
        super().__init__(db_path, apply_migrations=apply_migrations)


class _DatabaseHandle:
    """Stable stand-in for the process-wide Database.

    Modules bind ``db`` at import time (``from src.db.models import db``), so
    rebinding the name reaches none of them - test harnesses used to keep
    per-module patch lists that drifted (a missed module silently hit the
    wrong database). Swapping the target here reaches every importer at once.
    """

    def __init__(self, target: Database) -> None:
        self.target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self.target, name)

    # Writes go to the target too: a test patching db.some_method must patch
    # that Database. Set on the handle, monkeypatch's undo wrote back a bound
    # method of the then-current database, shadowing every later one.
    def __setattr__(self, name: str, value: object) -> None:
        if name == "target":
            object.__setattr__(self, name, value)
        else:
            setattr(self.target, name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self.target, name)


# Never migrates on import: every timer and script imports this module, and only
# the web app may apply migrations (create_app calls db.migrate())
_handle = _DatabaseHandle(Database(apply_migrations=False))

# Global database instance
db = cast(Database, _handle)


def set_database(database: Database) -> Database:
    """Point the global ``db`` at another Database; returns the previous one."""
    previous = _handle.target
    _handle.target = database
    return previous


def skip_if_migrations_pending(job: str) -> bool:
    """True (and an info log) when the schema is behind this code.

    Timers and scripts call this first and skip their run: the new web
    workers apply the migrations at deploy, after the backup.
    """
    pending = db.pending_migration_count()
    if pending:
        logger.info("Migrations pending, skipping", extra={"job": job, "pending": pending})
    return bool(pending)


@contextmanager
def use_database(database: Database) -> Iterator[Database]:
    """Temporarily point the global ``db`` at ``database`` (tests, harnesses)."""
    previous = set_database(database)
    try:
        yield database
    finally:
        set_database(previous)


# Re-export all public symbols
__all__ = [  # noqa: RUF022 - grouped by kind, not alphabetically
    # Database class and instance
    "Database",
    "db",
    "ConversationChange",
    "set_database",
    "skip_if_migrations_pending",
    "use_database",
    # Dataclasses
    "User",
    "Conversation",
    "Message",
    "Memory",
    "MessagePagination",
    "SearchResult",
    "Agent",
    "ApprovalRequest",
    "AgentExecution",
    "PushSubscription",
    # Helper functions
    "make_blob_key",
    "make_thumbnail_key",
    "save_file_to_blob_store",
    "extract_file_metadata",
    "delete_message_blobs",
    "delete_messages_blobs",
    "build_cursor",
    "parse_cursor",
    "should_reset_planner",
    "check_database_connectivity",
    "check_database_writable",
]
