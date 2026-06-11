"""Unit tests for previously untested agent tool modules (T2).

Covers metadata.py (structured extraction contract), trigger_agent.py
(delegation guards incl. cycle prevention), agent_kv.py (validation and
namespace defaulting) and file_retrieval.py (authorization guards).
"""

import json
from unittest.mock import MagicMock, patch

from src.agent.tools.agent_kv import kv_store
from src.agent.tools.file_retrieval import retrieve_file
from src.agent.tools.metadata import METADATA_TOOL_NAMES, cite_sources, manage_memory
from src.agent.tools.trigger_agent import trigger_agent

# ============ metadata.py ============


class TestMetadataTools:
    def test_cite_sources_acknowledges_count(self) -> None:
        result = cite_sources.invoke(
            {"sources": [{"title": "A", "url": "https://a"}, {"title": "B", "url": "https://b"}]}
        )
        assert "2" in result

    def test_manage_memory_acknowledges_count(self) -> None:
        result = manage_memory.invoke(
            {"operations": [{"action": "add", "content": "likes tea", "category": "preference"}]}
        )
        assert "1" in result

    def test_metadata_tool_names_match_tools(self) -> None:
        """should_continue routes on this set - it must match the tool names."""
        assert METADATA_TOOL_NAMES == frozenset({cite_sources.name, manage_memory.name})


# ============ trigger_agent.py ============


def _agent(agent_id: str = "agent-2", name: str = "helper", enabled: bool = True) -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id
    agent.name = name
    agent.enabled = enabled
    return agent


def _context(agent_id: str = "agent-1") -> MagicMock:
    ctx = MagicMock()
    ctx.agent = _agent(agent_id=agent_id, name="source")
    ctx.user.id = "user-1"
    return ctx


class TestTriggerAgent:
    def test_requires_agent_context(self) -> None:
        with patch("src.agent.executor.get_agent_context", return_value=None):
            result = trigger_agent.invoke({"agent_name": "helper"})
        assert "only be used by autonomous agents" in result

    def test_unknown_agent(self) -> None:
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
        ):
            mock_db.get_agent_by_name.return_value = None
            result = trigger_agent.invoke({"agent_name": "ghost"})
        assert "not found" in result

    def test_disabled_agent(self) -> None:
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
        ):
            mock_db.get_agent_by_name.return_value = _agent(enabled=False)
            result = trigger_agent.invoke({"agent_name": "helper"})
        assert "disabled" in result

    def test_circular_trigger_blocked(self) -> None:
        """An agent already in the trigger chain must not be re-triggered."""
        target = _agent(agent_id="agent-2")
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.executor.get_trigger_chain", return_value=["agent-2"]),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
            patch("src.agent.executor.AgentExecutor") as mock_executor,
        ):
            mock_db.get_agent_by_name.return_value = target
            result = trigger_agent.invoke({"agent_name": "helper"})
        assert "circular" in result
        mock_executor.assert_not_called()

    def test_successful_trigger(self) -> None:
        target = _agent(agent_id="agent-2")
        run_result = MagicMock()
        run_result.status = "completed"
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.executor.get_trigger_chain", return_value=["agent-1"]),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
            patch("src.agent.executor.AgentExecutor") as mock_executor_cls,
        ):
            mock_db.get_agent_by_name.return_value = target
            mock_executor_cls.return_value.run.return_value = run_result
            result = trigger_agent.invoke({"agent_name": "helper", "message": "do the thing"})

        assert "completed successfully" in result
        # The triggering agent must be recorded for chain/cycle tracking
        kwargs = mock_executor_cls.call_args.kwargs
        assert kwargs["triggered_by_agent_id"] == "agent-1"
        assert kwargs["trigger_type"] == "agent_trigger"

    def test_approval_pause_is_reported(self) -> None:
        from src.agent.tools.request_approval import ApprovalRequestedException

        target = _agent(agent_id="agent-2")
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.executor.get_trigger_chain", return_value=[]),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
            patch("src.agent.executor.AgentExecutor") as mock_executor_cls,
        ):
            mock_db.get_agent_by_name.return_value = target
            mock_executor_cls.return_value.run.side_effect = ApprovalRequestedException(
                "ap-1", "send email"
            )
            result = trigger_agent.invoke({"agent_name": "helper"})
        assert "waiting for user approval" in result

    def test_target_failure_is_contained(self) -> None:
        """A crash in the target agent must not propagate into the caller's run."""
        target = _agent(agent_id="agent-2")
        with (
            patch("src.agent.executor.get_agent_context", return_value=_context()),
            patch("src.agent.executor.get_trigger_chain", return_value=[]),
            patch("src.agent.tools.trigger_agent.db") as mock_db,
            patch("src.agent.executor.AgentExecutor") as mock_executor_cls,
        ):
            mock_db.get_agent_by_name.return_value = target
            mock_executor_cls.return_value.run.side_effect = RuntimeError("boom")
            result = trigger_agent.invoke({"agent_name": "helper"})
        assert "failed" in result
        assert "boom" in result


# ============ agent_kv.py ============


class _KVHarness:
    """Patches the context lookups + db for kv_store calls."""

    def __init__(
        self,
        user_id: str | None = "user-1",
        agent_context: MagicMock | None = None,
        sports: str | None = None,
        language: str | None = None,
    ) -> None:
        self.patches = [
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("conv-1", user_id),
            ),
            patch("src.agent.executor.get_agent_context", return_value=agent_context),
            patch("src.agent.tools.context.get_sports_context", return_value=sports),
            patch("src.agent.tools.context.get_language_context", return_value=language),
            patch("src.agent.tools.agent_kv.db"),
        ]

    def __enter__(self) -> MagicMock:
        started = [p.start() for p in self.patches]
        return started[-1]  # the db mock

    def __exit__(self, *args: object) -> None:
        for p in self.patches:
            p.stop()


class TestKvStoreTool:
    def test_requires_user_context(self) -> None:
        with _KVHarness(user_id=None):
            result = kv_store.invoke({"action": "get", "key": "k"})
        assert "No user context" in result

    def test_requires_feature_context(self) -> None:
        with _KVHarness():
            result = kv_store.invoke({"action": "get", "key": "k"})
        assert "only available during" in result

    def test_namespace_defaults_to_agent(self) -> None:
        ctx = _context(agent_id="agent-9")
        with _KVHarness(agent_context=ctx) as mock_db:
            mock_db.kv_get.return_value = '{"a": 1}'
            result = kv_store.invoke({"action": "get", "key": "k"})
        mock_db.kv_get.assert_called_once_with("user-1", "agent:agent-9", "k")
        assert result == '{"a": 1}'

    def test_namespace_defaults_to_sports(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            mock_db.kv_get.return_value = "{}"
            kv_store.invoke({"action": "get", "key": "k"})
        assert mock_db.kv_get.call_args.args[1] == "sports"

    def test_language_wins_namespace_default(self) -> None:
        with _KVHarness(sports="running", language="spanish") as mock_db:
            mock_db.kv_get.return_value = "{}"
            kv_store.invoke({"action": "get", "key": "k"})
        assert mock_db.kv_get.call_args.args[1] == "language"

    def test_invalid_action(self) -> None:
        with _KVHarness(sports="running"):
            result = kv_store.invoke({"action": "drop"})
        assert "Invalid action" in result

    def test_key_length_limit(self) -> None:
        with _KVHarness(sports="running"):
            result = kv_store.invoke({"action": "get", "key": "k" * 257})
        assert "Key too long" in result

    def test_set_rejects_invalid_json(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            result = kv_store.invoke({"action": "set", "key": "k", "value": "not json"})
        assert "must be valid JSON" in result
        mock_db.kv_set.assert_not_called()

    def test_set_rejects_oversized_value(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            result = kv_store.invoke({"action": "set", "key": "k", "value": "x" * 65537})
        assert "too large" in result
        mock_db.kv_set.assert_not_called()

    def test_set_enforces_key_cap_for_new_keys_only(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            mock_db.kv_count.return_value = 1000
            mock_db.kv_get.return_value = None  # new key
            result = kv_store.invoke({"action": "set", "key": "new", "value": "{}"})
            assert "maximum" in result

            mock_db.kv_get.return_value = "{}"  # existing key updates are fine
            result = kv_store.invoke({"action": "set", "key": "existing", "value": "{}"})
            assert "Stored" in result

    def test_delete_reports_missing_key(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            mock_db.kv_delete.return_value = False
            result = kv_store.invoke({"action": "delete", "key": "k"})
        assert "not found" in result

    def test_list_uses_key_as_prefix(self) -> None:
        with _KVHarness(sports="running") as mock_db:
            mock_db.kv_list.return_value = [("run:goals", '{"goal": 1}')]
            result = kv_store.invoke({"action": "list", "key": "run:"})
        mock_db.kv_list.assert_called_once_with("user-1", "sports", prefix="run:")
        assert "run:goals" in result


# ============ file_retrieval.py ============


class TestRetrieveFile:
    def _invoke(self) -> str | list:
        return retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

    def test_requires_conversation_context(self) -> None:
        with patch(
            "src.agent.tools.file_retrieval.get_conversation_context",
            return_value=(None, None),
        ):
            result = self._invoke()
        assert "No conversation context" in json.loads(result)["error"]

    def test_rejects_unowned_conversation(self) -> None:
        with (
            patch(
                "src.agent.tools.file_retrieval.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.db.models.db") as mock_db,
        ):
            mock_db.get_conversation.return_value = None
            result = self._invoke()
        assert "not authorized" in json.loads(result)["error"]

    def test_rejects_message_from_other_conversation(self) -> None:
        """A message id from a DIFFERENT conversation must not leak files."""
        message = MagicMock()
        message.conversation_id = "conv-OTHER"
        with (
            patch(
                "src.agent.tools.file_retrieval.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.db.models.db") as mock_db,
        ):
            mock_db.get_conversation.return_value = MagicMock()
            mock_db.get_message_by_id.return_value = message
            result = self._invoke()
        assert "error" in json.loads(result)

    def test_reports_missing_file_index(self) -> None:
        message = MagicMock()
        message.conversation_id = "conv-1"
        message.files = [{"name": "a.png"}]
        with (
            patch(
                "src.agent.tools.file_retrieval.get_conversation_context",
                return_value=("conv-1", "user-1"),
            ),
            patch("src.db.models.db") as mock_db,
        ):
            mock_db.get_conversation.return_value = MagicMock()
            mock_db.get_message_by_id.return_value = message
            result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 5})
        assert "File index 5 not found" in json.loads(result)["error"]
