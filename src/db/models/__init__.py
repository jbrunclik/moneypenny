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

from pathlib import Path

from src.db.models.agent import AgentMixin
from src.db.models.base import DatabaseBase
from src.db.models.cache import CacheMixin
from src.db.models.conversation import ConversationMixin
from src.db.models.cost import CostMixin
from src.db.models.dataclasses import (
    Agent,
    AgentExecution,
    ApprovalRequest,
    Conversation,
    Memory,
    Message,
    MessagePagination,
    SearchResult,
    User,
)
from src.db.models.helpers import (
    build_cursor,
    check_database_connectivity,
    delete_message_blobs,
    delete_messages_blobs,
    extract_file_metadata,
    make_blob_key,
    make_thumbnail_key,
    parse_cursor,
    save_file_to_blob_store,
    should_reset_planner,
)
from src.db.models.memory import MemoryMixin
from src.db.models.message import MessageMixin
from src.db.models.planner import PlannerMixin
from src.db.models.search import SearchMixin
from src.db.models.settings import SettingsMixin
from src.db.models.user import UserMixin


class Database(
    DatabaseBase,
    UserMixin,
    ConversationMixin,
    MessageMixin,
    MemoryMixin,
    PlannerMixin,
    CacheMixin,
    CostMixin,
    SearchMixin,
    SettingsMixin,
    AgentMixin,
):
    """Main database class combining all mixins.

    Provides all database operations through a unified interface.
    Uses connection pooling for efficient database access.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the database.

        Args:
            db_path: Optional path to the database file.
                    Defaults to Config.DATABASE_PATH.
        """
        super().__init__(db_path)


# Global database instance
db = Database()

# Re-export all public symbols
__all__ = [
    # Database class and instance
    "Database",
    "db",
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
]
