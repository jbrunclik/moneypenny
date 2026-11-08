"""Unit tests for tool selection in the src/agent/tools package (__init__.py)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import (
    get_all_tool_names,
    get_available_tools,
    get_tools_for_request,
)
from src.config import Config

ANONYMOUS_WITHHELD = {
    "todoist",
    "google_calendar",
    "garmin_connect",
    "garmin_workout",
    "manage_memory",
    "search_memory",
    "save_place",
    "delete_place",
    "search_conversations",
    "read_conversation",
}


@pytest.fixture
def every_tool_available() -> object:
    """Every registered tool bindable, whatever this machine has configured."""
    tools = []
    for name in sorted(get_all_tool_names()):
        tool = MagicMock()
        tool.name = name
        tools.append(tool)
    with patch("src.agent.tools.get_available_tools", return_value=tools):
        yield


def _names(**kwargs: Any) -> set[str]:
    return {t.name for t in get_tools_for_request(**kwargs)}


# Bound in every interactive chat but the planner on top of get_available_tools()
_ORDINARY_CHAT_ONLY = {"propose_deep_research", "schedule", "create_standing_chat"}


class TestGetToolsForRequest:
    """Tests for get_tools_for_request function."""

    def test_returns_all_tools_by_default(self) -> None:
        """Should return all tools when anonymous_mode is False."""
        tools = get_tools_for_request(anonymous_mode=False)
        # Ordinary chats also get the deep-research offer and scheduling (never agents/programs)
        assert [t for t in tools if t.name not in _ORDINARY_CHAT_ONLY] == get_available_tools()
        # Core tools should always be present
        tool_names = {t.name for t in tools}
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "generate_image" in tool_names
        assert "retrieve_file" in tool_names

    def test_excludes_integration_tools_in_anonymous_mode(self) -> None:
        """Should exclude todoist and google_calendar in anonymous mode."""
        tools = get_tools_for_request(anonymous_mode=True)
        tool_names = {t.name for t in tools}

        # Integration tools should be excluded (even if they were available)
        assert "todoist" not in tool_names
        assert "google_calendar" not in tool_names

        # Core tools should still be present
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "generate_image" in tool_names
        assert "retrieve_file" in tool_names

    def test_excludes_manage_memory_in_anonymous_mode(self) -> None:
        """Anonymous mode must not be able to write to long-term memory.

        The tool is unbound rather than filtered after the fact, so the model
        cannot even attempt a write it is not allowed to make.
        """
        assert "manage_memory" in {t.name for t in get_tools_for_request(anonymous_mode=False)}
        assert "manage_memory" not in {t.name for t in get_tools_for_request(anonymous_mode=True)}

    @pytest.mark.usefixtures("every_tool_available")
    def test_anonymous_mode_withholds_integrations_memory_and_history(self) -> None:
        """Exactly the withheld tools go: everything else a normal chat binds stays."""
        assert _names(anonymous_mode=True) == _names() - ANONYMOUS_WITHHELD

    def test_default_parameter_is_false(self) -> None:
        """Should default to anonymous_mode=False."""
        tools = get_tools_for_request()
        assert [t for t in tools if t.name not in _ORDINARY_CHAT_ONLY] == get_available_tools()

    @pytest.mark.usefixtures("every_tool_available")
    def test_standing_chat_gets_the_full_chat_tools(self) -> None:
        """An agent / sports / language chat is an ordinary chat turn when the
        user writes in it: every chat tool, plus kv_store for its namespace."""
        names = {t.name for t in get_tools_for_request(standing=True)}
        assert {
            "schedule",
            "record_conversation_facts",
            "google_calendar",
            "todoist",
            "manage_memory",
            "create_artifact",
            "garmin_connect",
            "kv_store",
        } <= names

    def test_regular_chat_keeps_all_tools(self) -> None:
        """Subsetting applies only to program conversations."""
        tool_names = {t.name for t in get_tools_for_request()}
        available = {t.name for t in get_available_tools()}
        assert tool_names == available | _ORDINARY_CHAT_ONLY

    def test_non_agent_request_excludes_kv_store(self) -> None:
        """Regular (non-agent, non-sports, non-language) chats must not get kv_store."""
        tools = get_tools_for_request()
        tool_names = {t.name for t in tools}
        assert "kv_store" not in tool_names


class TestGetToolsForAgent:
    """Tool binding for autonomous agent runs."""

    @staticmethod
    def _bound(tool_permissions: list[str] | None) -> list[Any]:
        """A job run's tools: None = all tools (the "*" grant)."""
        from src.agent.tools import tools_for_grants

        return tools_for_grants(["*"] if tool_permissions is None else tool_permissions, "user-1")

    def test_restricted_agent_does_not_get_manage_memory(self) -> None:
        """Baseline agent tools must not include long-term memory writes."""

        tools = self._bound(["web_search"])
        assert "manage_memory" not in {t.name for t in tools}

    def test_agent_with_empty_permissions_does_not_get_manage_memory(self) -> None:
        """tool_permissions=[] means no extra capabilities at all."""

        tools = self._bound([])
        assert "manage_memory" not in {t.name for t in tools}

    def test_agent_granted_manage_memory_gets_it(self) -> None:
        """An explicit grant is honoured."""

        tools = self._bound(["manage_memory"])
        assert "manage_memory" in {t.name for t in tools}

    def test_unrestricted_agent_keeps_manage_memory(self) -> None:
        """tool_permissions=None means unrestricted, including memory."""

        tools = self._bound(None)
        assert "manage_memory" in {t.name for t in tools}

    def test_every_bound_tool_passes_the_permission_gate(self) -> None:
        """A bound tool the gate then refuses wastes a model round on an error.

        create_file and trigger_agent were bound for every agent but denied at
        call time unless listed in tool_permissions (same class of bug as the
        kv_store fix in 0be1fb1).
        """
        from src.agent.permissions import PermissionResult, check_tool_permission

        for permissions in ([], ["web_search"], ["todoist"]):
            for tool in self._bound(permissions):
                result = check_tool_permission(permissions, tool.name, {})
                assert result == PermissionResult.ALLOWED, (permissions, tool.name)

    def test_trigger_agent_only_when_granted(self) -> None:
        """Handing another agent a message is a capability, not a baseline tool."""

        assert "trigger_agent" not in {t.name for t in self._bound([])}
        granted = self._bound(["trigger_agent"])
        assert "trigger_agent" in {t.name for t in granted}
        assert "trigger_agent" in {t.name for t in self._bound(None)}


# Each integration tool, the availability check that gates it and a value that
# makes it unavailable (browser and code also need their Config switch)
_INTEGRATIONS = [
    ("todoist", "src.agent.tools.is_todoist_available"),
    ("google_calendar", "src.agent.tools.is_google_calendar_available"),
    ("garmin_connect", "src.agent.tools.is_garmin_available"),
    ("garmin_workout", "src.agent.tools.is_garmin_available"),
    ("rouvy_workout", "src.agent.tools.is_rouvy_available"),
    ("browser", "src.agent.tools.is_browser_available"),
]


class TestPermittedIntegrationAvailability:
    """A permitted integration tool is bound only when this deployment can run it."""

    @staticmethod
    def _bound(tool_permissions: list[str] | None) -> list[Any]:
        """A job run's tools: None = all tools (the "*" grant)."""
        from src.agent.tools import tools_for_grants

        return tools_for_grants(["*"] if tool_permissions is None else tool_permissions, "user-1")

    @pytest.mark.parametrize(("tool_name", "check"), _INTEGRATIONS)
    def test_unavailable_integration_is_dropped(self, tool_name: str, check: str) -> None:

        with patch(check, return_value=False), patch.object(Config, "BROWSER_ENABLED", True):
            agent_run = self._bound([tool_name])
        assert tool_name not in {t.name for t in agent_run}

    @pytest.mark.parametrize(("tool_name", "check"), _INTEGRATIONS)
    def test_available_integration_is_bound(self, tool_name: str, check: str) -> None:

        with patch(check, return_value=True), patch.object(Config, "BROWSER_ENABLED", True):
            agent_run = self._bound([tool_name])
        assert tool_name in {t.name for t in agent_run}

    @pytest.mark.parametrize("enabled", [True, False])
    def test_config_switches_gate_browser_and_code(self, enabled: bool) -> None:

        names = ["browser", "execute_code"]
        with (
            patch("src.agent.tools.is_browser_available", return_value=True),
            patch.object(Config, "BROWSER_ENABLED", enabled),
            patch.object(Config, "CODE_SANDBOX_ENABLED", enabled),
        ):
            agent_run = {t.name for t in self._bound(names)}
        assert (set(names) <= agent_run) is enabled

    def test_whatsapp_needs_a_phone_for_agents(self) -> None:

        with (
            patch("src.agent.tools.is_whatsapp_available", return_value=True),
            patch("src.agent.tools._is_whatsapp_available_for_user", return_value=False) as phone,
        ):
            agent_run = self._bound(["whatsapp"])
        assert "whatsapp" not in {t.name for t in agent_run}
        phone.assert_called_with("user-1")

    def test_unknown_permissions_and_duplicates_are_ignored(self) -> None:

        tools = self._bound(["no_such_tool", "web_search"])
        assert [t.name for t in tools].count("web_search") == 1

    def test_unrestricted_agent_gets_every_available_integration(self) -> None:

        with (
            patch("src.agent.tools.is_todoist_available", return_value=True),
            patch("src.agent.tools.is_google_calendar_available", return_value=False),
            patch("src.agent.tools.is_garmin_available", return_value=True),
            patch("src.agent.tools.is_rouvy_available", return_value=False),
            patch("src.agent.tools._is_whatsapp_available_for_user", return_value=True),
            patch.object(Config, "CODE_SANDBOX_ENABLED", False),
            patch.object(Config, "BROWSER_ENABLED", False),
        ):
            names = [t.name for t in self._bound(None)]
        # After the baseline tools, in this order
        assert names[-7:] == [
            "todoist",
            "garmin_connect",
            "garmin_workout",
            "whatsapp",
            "generate_image",
            "manage_memory",
            "trigger_agent",
        ]
        assert "google_calendar" not in names and "rouvy_workout" not in names
