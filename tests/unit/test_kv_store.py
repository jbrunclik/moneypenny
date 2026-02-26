"""Unit tests for the K/V Store feature.

Covers:
- KVStoreMixin database operations (real SQLite in-memory via test_database)
- kv_store agent tool (mock db + context)
- KV Store REST API routes (mock db)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from src.db.models import Database, User


# =============================================================================
# DB Mixin Tests (real SQLite in-memory via test_database fixture)
# =============================================================================


class TestKVStoreMixinSetGet:
    """Tests for basic set/get operations."""

    def test_kv_set_and_get(self, test_database: Database, test_user: User) -> None:
        """Basic round-trip: set a value then get it back."""
        test_database.kv_set(test_user.id, "test-ns", "my-key", "my-value")

        result = test_database.kv_get(test_user.id, "test-ns", "my-key")

        assert result == "my-value"

    def test_kv_get_nonexistent(self, test_database: Database, test_user: User) -> None:
        """Getting a key that doesn't exist returns None."""
        result = test_database.kv_get(test_user.id, "test-ns", "no-such-key")

        assert result is None

    def test_kv_set_overwrites(self, test_database: Database, test_user: User) -> None:
        """Setting an existing key updates the value (upsert)."""
        test_database.kv_set(test_user.id, "test-ns", "my-key", "original")
        test_database.kv_set(test_user.id, "test-ns", "my-key", "updated")

        result = test_database.kv_get(test_user.id, "test-ns", "my-key")

        assert result == "updated"

    def test_kv_set_stores_json_value(self, test_database: Database, test_user: User) -> None:
        """Values can be arbitrary strings including serialized JSON."""
        payload = json.dumps({"count": 42, "items": ["a", "b"]})
        test_database.kv_set(test_user.id, "test-ns", "json-key", payload)

        result = test_database.kv_get(test_user.id, "test-ns", "json-key")

        assert result is not None
        assert json.loads(result) == {"count": 42, "items": ["a", "b"]}


class TestKVStoreMixinDelete:
    """Tests for delete operations."""

    def test_kv_delete_existing(self, test_database: Database, test_user: User) -> None:
        """Deleting an existing key returns True and removes it."""
        test_database.kv_set(test_user.id, "test-ns", "del-key", "val")

        deleted = test_database.kv_delete(test_user.id, "test-ns", "del-key")

        assert deleted is True
        assert test_database.kv_get(test_user.id, "test-ns", "del-key") is None

    def test_kv_delete_nonexistent(self, test_database: Database, test_user: User) -> None:
        """Deleting a key that doesn't exist returns False."""
        deleted = test_database.kv_delete(test_user.id, "test-ns", "phantom-key")

        assert deleted is False


class TestKVStoreMixinList:
    """Tests for list operations."""

    def test_kv_list_all(self, test_database: Database, test_user: User) -> None:
        """Lists all key-value pairs in a namespace."""
        test_database.kv_set(test_user.id, "list-ns", "b-key", "b-val")
        test_database.kv_set(test_user.id, "list-ns", "a-key", "a-val")

        items = test_database.kv_list(test_user.id, "list-ns")

        assert len(items) == 2
        # Results are ordered by key
        assert items[0] == ("a-key", "a-val")
        assert items[1] == ("b-key", "b-val")

    def test_kv_list_with_prefix(self, test_database: Database, test_user: User) -> None:
        """Prefix filter returns only matching keys."""
        test_database.kv_set(test_user.id, "prefix-ns", "config:theme", "dark")
        test_database.kv_set(test_user.id, "prefix-ns", "config:lang", "en")
        test_database.kv_set(test_user.id, "prefix-ns", "data:foo", "bar")

        items = test_database.kv_list(test_user.id, "prefix-ns", prefix="config:")

        assert len(items) == 2
        keys = [k for k, _ in items]
        assert "config:lang" in keys
        assert "config:theme" in keys
        assert "data:foo" not in keys

    def test_kv_list_empty_namespace(self, test_database: Database, test_user: User) -> None:
        """Listing an empty namespace returns an empty list."""
        items = test_database.kv_list(test_user.id, "empty-ns")

        assert items == []

    def test_kv_list_prefix_no_matches(self, test_database: Database, test_user: User) -> None:
        """Prefix that matches nothing returns an empty list."""
        test_database.kv_set(test_user.id, "ns", "alpha", "1")

        items = test_database.kv_list(test_user.id, "ns", prefix="beta")

        assert items == []


class TestKVStoreMixinCount:
    """Tests for count operations."""

    def test_kv_count(self, test_database: Database, test_user: User) -> None:
        """Counts the number of keys in a namespace."""
        test_database.kv_set(test_user.id, "count-ns", "k1", "v1")
        test_database.kv_set(test_user.id, "count-ns", "k2", "v2")
        test_database.kv_set(test_user.id, "count-ns", "k3", "v3")

        count = test_database.kv_count(test_user.id, "count-ns")

        assert count == 3

    def test_kv_count_empty_namespace(self, test_database: Database, test_user: User) -> None:
        """Counting an empty namespace returns 0."""
        count = test_database.kv_count(test_user.id, "no-such-ns")

        assert count == 0

    def test_kv_count_after_delete(self, test_database: Database, test_user: User) -> None:
        """Count reflects deletions."""
        test_database.kv_set(test_user.id, "count-del-ns", "k1", "v1")
        test_database.kv_set(test_user.id, "count-del-ns", "k2", "v2")
        test_database.kv_delete(test_user.id, "count-del-ns", "k1")

        count = test_database.kv_count(test_user.id, "count-del-ns")

        assert count == 1


class TestKVStoreMixinNamespaces:
    """Tests for namespace listing."""

    def test_kv_list_namespaces(self, test_database: Database, test_user: User) -> None:
        """Lists all namespaces with their key counts."""
        test_database.kv_set(test_user.id, "ns-alpha", "k1", "v1")
        test_database.kv_set(test_user.id, "ns-alpha", "k2", "v2")
        test_database.kv_set(test_user.id, "ns-beta", "k1", "v1")

        namespaces = test_database.kv_list_namespaces(test_user.id)

        assert len(namespaces) == 2
        ns_dict = dict(namespaces)
        assert ns_dict["ns-alpha"] == 2
        assert ns_dict["ns-beta"] == 1

    def test_kv_list_namespaces_empty(self, test_database: Database, test_user: User) -> None:
        """User with no data returns empty namespace list."""
        # Use a user with a unique ID that has no KV data
        fresh_user = test_database.get_or_create_user(
            email="fresh-ns@example.com",
            name="Fresh NS User",
            picture="",
        )

        namespaces = test_database.kv_list_namespaces(fresh_user.id)

        assert namespaces == []

    def test_kv_list_namespaces_ordered(self, test_database: Database, test_user: User) -> None:
        """Namespaces are returned in alphabetical order."""
        # Create a fresh user to avoid pollution from other tests
        fresh_user = test_database.get_or_create_user(
            email="ns-order@example.com",
            name="NS Order User",
            picture="",
        )
        test_database.kv_set(fresh_user.id, "zebra", "k", "v")
        test_database.kv_set(fresh_user.id, "apple", "k", "v")
        test_database.kv_set(fresh_user.id, "mango", "k", "v")

        namespaces = test_database.kv_list_namespaces(fresh_user.id)
        ns_names = [ns for ns, _ in namespaces]

        assert ns_names == ["apple", "mango", "zebra"]


class TestKVStoreMixinClear:
    """Tests for clear operations."""

    def test_kv_clear_namespace(self, test_database: Database, test_user: User) -> None:
        """Clears all keys in a namespace and returns the count deleted."""
        test_database.kv_set(test_user.id, "clear-ns", "k1", "v1")
        test_database.kv_set(test_user.id, "clear-ns", "k2", "v2")
        test_database.kv_set(test_user.id, "other-ns", "k1", "v1")

        deleted = test_database.kv_clear_namespace(test_user.id, "clear-ns")

        assert deleted == 2
        assert test_database.kv_list(test_user.id, "clear-ns") == []
        # Other namespace is untouched
        assert test_database.kv_count(test_user.id, "other-ns") == 1

    def test_kv_clear_namespace_empty(self, test_database: Database, test_user: User) -> None:
        """Clearing an empty namespace returns 0."""
        deleted = test_database.kv_clear_namespace(test_user.id, "no-such-ns")

        assert deleted == 0

    def test_kv_clear_user(self, test_database: Database, test_user: User) -> None:
        """Deletes all keys for a user across all namespaces."""
        clear_user = test_database.get_or_create_user(
            email="clear-user@example.com",
            name="Clear User",
            picture="",
        )
        test_database.kv_set(clear_user.id, "ns-a", "k1", "v1")
        test_database.kv_set(clear_user.id, "ns-a", "k2", "v2")
        test_database.kv_set(clear_user.id, "ns-b", "k1", "v1")

        deleted = test_database.kv_clear_user(clear_user.id)

        assert deleted == 3
        assert test_database.kv_list_namespaces(clear_user.id) == []

    def test_kv_clear_user_does_not_touch_other_users(
        self, test_database: Database, test_user: User
    ) -> None:
        """kv_clear_user only removes data for the given user."""
        user_a = test_database.get_or_create_user(
            email="isolation-a@example.com", name="User A", picture=""
        )
        user_b = test_database.get_or_create_user(
            email="isolation-b@example.com", name="User B", picture=""
        )
        test_database.kv_set(user_a.id, "shared-ns", "key", "a-value")
        test_database.kv_set(user_b.id, "shared-ns", "key", "b-value")

        test_database.kv_clear_user(user_a.id)

        assert test_database.kv_get(user_a.id, "shared-ns", "key") is None
        assert test_database.kv_get(user_b.id, "shared-ns", "key") == "b-value"


class TestKVStoreMixinIsolation:
    """Tests for namespace and user isolation."""

    def test_namespace_isolation(self, test_database: Database, test_user: User) -> None:
        """Data in namespace A is not visible when querying namespace B."""
        test_database.kv_set(test_user.id, "ns-a", "shared-key", "value-in-a")

        result = test_database.kv_get(test_user.id, "ns-b", "shared-key")

        assert result is None

    def test_user_isolation(self, test_database: Database) -> None:
        """User A's data is not visible to user B."""
        user_a = test_database.get_or_create_user(
            email="user-iso-a@example.com", name="User Iso A", picture=""
        )
        user_b = test_database.get_or_create_user(
            email="user-iso-b@example.com", name="User Iso B", picture=""
        )
        test_database.kv_set(user_a.id, "shared-ns", "key", "a-value")

        result = test_database.kv_get(user_b.id, "shared-ns", "key")

        assert result is None

    def test_user_list_isolation(self, test_database: Database) -> None:
        """kv_list only returns data belonging to the requesting user."""
        user_a = test_database.get_or_create_user(
            email="list-iso-a@example.com", name="List Iso A", picture=""
        )
        user_b = test_database.get_or_create_user(
            email="list-iso-b@example.com", name="List Iso B", picture=""
        )
        test_database.kv_set(user_a.id, "shared-ns", "a-key", "a-val")
        test_database.kv_set(user_b.id, "shared-ns", "b-key", "b-val")

        items_a = test_database.kv_list(user_a.id, "shared-ns")
        items_b = test_database.kv_list(user_b.id, "shared-ns")

        assert items_a == [("a-key", "a-val")]
        assert items_b == [("b-key", "b-val")]


# =============================================================================
# Tool Tests (mock db + context)
# =============================================================================


@pytest.fixture
def mock_db_for_tool() -> MagicMock:
    """Mock database for tool tests."""
    return MagicMock()


@pytest.fixture
def mock_agent_context() -> MagicMock:
    """Mock AgentContext with a test agent."""
    agent = MagicMock()
    agent.id = "agent-abc"
    context = MagicMock()
    context.agent = agent
    return context


def _invoke_kv_store(**kwargs) -> str:
    """Helper to call the kv_store tool's underlying function directly."""
    from src.agent.tools.agent_kv import kv_store

    return kv_store.invoke(kwargs)


class TestKVStoreTool:
    """Tests for the kv_store agent tool."""

    def test_kv_store_set_and_get(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Happy path: set then get returns the stored value."""
        mock_db_for_tool.kv_get.return_value = "hello"

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", key="my-key", namespace="agent:agent-abc")

        assert result == "hello"
        mock_db_for_tool.kv_get.assert_called_once_with("user-1", "agent:agent-abc", "my-key")

    def test_kv_store_set(self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock) -> None:
        """Set action stores the value and returns confirmation."""
        mock_db_for_tool.kv_count.return_value = 0
        mock_db_for_tool.kv_get.return_value = None  # key doesn't exist yet

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="set", key="my-key", value='"my-value"')

        assert "Stored 'my-key'" in result
        mock_db_for_tool.kv_set.assert_called_once_with(
            "user-1", "agent:agent-abc", "my-key", '"my-value"'
        )

    def test_kv_store_delete(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Delete action removes the key and returns confirmation."""
        mock_db_for_tool.kv_delete.return_value = True

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="delete", key="my-key")

        assert "Deleted 'my-key'" in result
        mock_db_for_tool.kv_delete.assert_called_once()

    def test_kv_store_delete_missing_key(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Delete of nonexistent key returns not-found message."""
        mock_db_for_tool.kv_delete.return_value = False

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="delete", key="ghost-key")

        assert "not found" in result

    def test_kv_store_list(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """List action returns a summary of keys with value previews."""
        mock_db_for_tool.kv_list.return_value = [
            ("key-a", "short-value"),
            ("key-b", "x" * 150),  # Value longer than 100 chars
        ]

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="list", namespace="agent:agent-abc")

        assert "key-a" in result
        assert "key-b" in result
        assert "short-value" in result
        # Long values are truncated with "..."
        assert "..." in result

    def test_kv_store_list_empty(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """List on empty namespace returns descriptive message."""
        mock_db_for_tool.kv_list.return_value = []

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="list", namespace="empty-ns")

        assert "No keys found" in result

    def test_kv_store_auto_namespace_for_agents(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """When namespace is omitted, the tool auto-defaults to 'agent:<agent_id>'."""
        mock_db_for_tool.kv_count.return_value = 0
        mock_db_for_tool.kv_get.return_value = None

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            # No namespace argument — should auto-default
            result = _invoke_kv_store(action="set", key="k", value='"v"')

        assert "agent:agent-abc" in result
        # The db.kv_set should have been called with the auto namespace
        call_args = mock_db_for_tool.kv_set.call_args
        assert call_args[0][1] == "agent:agent-abc"

    def test_kv_store_no_context_error(self, mock_db_for_tool: MagicMock) -> None:
        """Without user context the tool returns an error string."""
        with (
            patch("src.agent.tools.agent_kv.get_conversation_context", return_value=(None, None)),
            patch("src.agent.executor.get_agent_context", return_value=MagicMock()),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", key="k", namespace="ns")

        assert "No user context" in result
        mock_db_for_tool.kv_get.assert_not_called()

    def test_kv_store_no_agent_context_error(self, mock_db_for_tool: MagicMock) -> None:
        """Without agent context the tool returns an error string."""
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=None),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", key="k", namespace="ns")

        assert "only available during autonomous agent execution" in result
        mock_db_for_tool.kv_get.assert_not_called()

    def test_kv_store_key_length_limit(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Keys longer than 256 characters are rejected."""
        too_long_key = "x" * 257

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", key=too_long_key, namespace="ns")

        assert "Key too long" in result
        mock_db_for_tool.kv_get.assert_not_called()

    def test_kv_store_key_at_max_length_is_accepted(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """A key of exactly 256 characters is accepted."""
        max_key = "x" * 256
        mock_db_for_tool.kv_get.return_value = "val"

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", key=max_key, namespace="ns")

        assert "Key too long" not in result
        mock_db_for_tool.kv_get.assert_called_once()

    def test_kv_store_value_size_limit(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Values larger than 64KB are rejected."""
        oversized_value = "x" * 65537  # One byte over the 64KB limit

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="set", key="k", value=oversized_value)

        assert "Value too large" in result
        mock_db_for_tool.kv_set.assert_not_called()

    def test_kv_store_max_keys_limit(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Namespace at 1000 keys rejects new keys."""
        mock_db_for_tool.kv_count.return_value = 1000
        mock_db_for_tool.kv_get.return_value = None  # Key doesn't exist yet

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="set", key="new-key", value='"v"', namespace="ns")

        assert "maximum" in result.lower()
        mock_db_for_tool.kv_set.assert_not_called()

    def test_kv_store_max_keys_allows_update(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """At 1000 keys, updating an existing key is still allowed."""
        mock_db_for_tool.kv_count.return_value = 1000
        mock_db_for_tool.kv_get.return_value = "existing-value"  # Key already exists

        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(
                action="set", key="existing-key", value='"new-val"', namespace="ns"
            )

        assert "Stored" in result
        mock_db_for_tool.kv_set.assert_called_once()

    def test_kv_store_invalid_action(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """Unknown action returns an error message."""
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="explode", key="k", namespace="ns")

        assert "Invalid action" in result
        assert "explode" in result

    def test_kv_store_get_missing_key_parameter(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """get action without key parameter returns an error."""
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="get", namespace="ns")

        assert "'key' is required" in result

    def test_kv_store_set_invalid_json_value(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """set action with non-JSON value returns an error."""
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="set", key="k", value="not json", namespace="ns")

        assert "must be valid JSON" in result
        mock_db_for_tool.kv_set.assert_not_called()

    def test_kv_store_set_missing_value_parameter(
        self, mock_db_for_tool: MagicMock, mock_agent_context: MagicMock
    ) -> None:
        """set action without value parameter returns an error."""
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.agent.executor.get_agent_context", return_value=mock_agent_context),
            patch("src.agent.tools.agent_kv.db", mock_db_for_tool),
        ):
            result = _invoke_kv_store(action="set", key="k", namespace="ns")

        assert "'value' is required" in result


# =============================================================================
# API Route Tests
# =============================================================================


@pytest.fixture
def mock_kv_db() -> MagicMock:
    """Mock database for KV route tests."""
    db = MagicMock()
    db.kv_list_namespaces.return_value = []
    db.kv_list.return_value = []
    db.kv_get.return_value = None
    db.kv_count.return_value = 0
    db.kv_delete.return_value = False
    db.kv_clear_namespace.return_value = 0
    return db


class TestKVListNamespacesRoute:
    """Tests for GET /api/kv."""

    def test_list_namespaces_returns_list(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Should return namespace list for authenticated user."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_list_namespaces.return_value = [
                ("agent:abc", 3),
                ("notes", 1),
            ]
            response = client.get("/api/kv", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert "namespaces" in data
        assert len(data["namespaces"]) == 2
        namespaces = {item["namespace"]: item["key_count"] for item in data["namespaces"]}
        assert namespaces["agent:abc"] == 3
        assert namespaces["notes"] == 1

    def test_list_namespaces_empty(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return empty list when user has no namespaces."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_list_namespaces.return_value = []
            response = client.get("/api/kv", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["namespaces"] == []

    def test_list_namespaces_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/kv")

        assert response.status_code == 401


class TestKVGetKeysRoute:
    """Tests for GET /api/kv/<namespace>."""

    def test_get_keys_returns_all_keys(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return all keys in the namespace."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_list.return_value = [
                ("key-a", "val-a"),
                ("key-b", "val-b"),
            ]
            response = client.get("/api/kv/my-namespace", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["namespace"] == "my-namespace"
        assert len(data["keys"]) == 2
        keys_dict = {item["key"]: item["value"] for item in data["keys"]}
        assert keys_dict["key-a"] == "val-a"
        assert keys_dict["key-b"] == "val-b"

    def test_get_keys_empty_namespace(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return empty keys list for empty namespace."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_list.return_value = []
            response = client.get("/api/kv/empty-ns", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["keys"] == []

    def test_get_keys_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/kv/some-ns")

        assert response.status_code == 401

    def test_get_keys_with_nested_namespace(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Namespaces with path separators (e.g. 'agent:id') are routed correctly."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_list.return_value = [("k", "v")]
            response = client.get("/api/kv/agent:abc-123", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["namespace"] == "agent:abc-123"


class TestKVGetValueRoute:
    """Tests for GET /api/kv/<namespace>/<key>."""

    def test_get_value_returns_value(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return the stored value for an existing key."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_get.return_value = "stored-value"
            response = client.get("/api/kv/my-ns/my-key", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["namespace"] == "my-ns"
        assert data["key"] == "my-key"
        assert data["value"] == "stored-value"

    def test_get_value_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when key does not exist."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_get.return_value = None
            response = client.get("/api/kv/my-ns/missing-key", headers=auth_headers)

        assert response.status_code == 404

    def test_get_value_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/kv/some-ns/some-key")

        assert response.status_code == 401


class TestKVSetValueRoute:
    """Tests for PUT /api/kv/<namespace>/<key>."""

    def test_set_value_creates_key(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should create/update a key and return the stored value."""
        json_value = '{"greeting": "hello world"}'
        with patch("src.api.routes.kv_store.db") as mock_db:
            response = client.put(
                "/api/kv/my-ns/my-key",
                headers=auth_headers,
                json={"value": json_value},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["namespace"] == "my-ns"
        assert data["key"] == "my-key"
        assert data["value"] == json_value
        mock_db.kv_set.assert_called_once()

    def test_set_value_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.put(
            "/api/kv/ns/key",
            json={"value": "v"},
        )

        assert response.status_code == 401

    def test_set_value_key_too_long(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 when key exceeds 256 characters."""
        too_long_key = "x" * 257

        with patch("src.api.routes.kv_store.db"):
            response = client.put(
                f"/api/kv/my-ns/{too_long_key}",
                headers=auth_headers,
                json={"value": '"v"'},
            )

        assert response.status_code == 400

    def test_set_value_invalid_json(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 when value is not valid JSON."""
        with patch("src.api.routes.kv_store.db"):
            response = client.put(
                "/api/kv/my-ns/my-key",
                headers=auth_headers,
                json={"value": "not valid json"},
            )

        assert response.status_code == 400

    def test_set_value_missing_body(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 422 when request body is missing."""
        with patch("src.api.routes.kv_store.db"):
            response = client.put(
                "/api/kv/my-ns/my-key",
                headers=auth_headers,
                json={},
            )

        assert response.status_code == 422


class TestKVDeleteKeyRoute:
    """Tests for DELETE /api/kv/<namespace>/<key>."""

    def test_delete_key_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should delete an existing key and return status."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_delete.return_value = True
            response = client.delete("/api/kv/my-ns/my-key", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "deleted"

    def test_delete_key_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when key does not exist."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_delete.return_value = False
            response = client.delete("/api/kv/my-ns/ghost-key", headers=auth_headers)

        assert response.status_code == 404

    def test_delete_key_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/kv/ns/key")

        assert response.status_code == 401


class TestKVClearNamespaceRoute:
    """Tests for DELETE /api/kv/<namespace>."""

    def test_clear_namespace_success(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should clear all keys and report count in status."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_clear_namespace.return_value = 5
            response = client.delete("/api/kv/my-ns", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert "5" in data["status"]
        assert "cleared" in data["status"]

    def test_clear_namespace_empty(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Clearing an already-empty namespace returns 0 deleted."""
        with patch("src.api.routes.kv_store.db") as mock_db:
            mock_db.kv_clear_namespace.return_value = 0
            response = client.delete("/api/kv/empty-ns", headers=auth_headers)

        assert response.status_code == 200
        data = response.get_json()
        assert "0" in data["status"]

    def test_clear_namespace_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.delete("/api/kv/some-ns")

        assert response.status_code == 401
