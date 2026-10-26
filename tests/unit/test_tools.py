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

# What each program conversation withholds: their declarations cost ~7-10k
# tokens re-sent every tool round, for tools a fitness or language program
# never uses (the spec; src/agent/tools/__init__.py implements it)
SPORTS_WITHHELD = {
    "todoist",
    "whatsapp",
    "google_calendar",
    "generate_image",
    "execute_code",
    "search_places",
    "save_place",
    "delete_place",
    "list_places",
    "get_route",
    "create_artifact",
    "update_artifact",
    "read_artifact",
}
LANGUAGE_WITHHELD = SPORTS_WITHHELD | {"garmin_connect", "garmin_workout"}
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


class TestGetToolsForRequest:
    """Tests for get_tools_for_request function."""

    def test_returns_all_tools_by_default(self) -> None:
        """Should return all tools when anonymous_mode is False."""
        tools = get_tools_for_request(anonymous_mode=False)
        # Ordinary chats also get the deep-research offer (never agents/programs)
        assert [t for t in tools if t.name != "propose_deep_research"] == get_available_tools()
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
        assert [t for t in tools if t.name != "propose_deep_research"] == get_available_tools()

    @pytest.mark.usefixtures("every_tool_available")
    def test_sports_mode_excludes_irrelevant_tools(self) -> None:
        """Sports conversations must not carry todoist/whatsapp/calendar/
        places/image-gen/code declarations - ~7k tokens re-sent every tool
        round for tools a fitness program never uses."""
        names = _names(is_sports=True)
        assert not SPORTS_WITHHELD & names
        # Core sports tools must survive
        assert {"kv_store", "web_search", "manage_memory"} <= names
        # create_file replaces execute_code for producing downloadable files
        # (e.g. ZWO workouts) in the context-lean sports profile.
        assert "create_file" in names

    def test_sports_mode_keeps_create_file(self) -> None:
        """execute_code is dropped for sports, so create_file must remain the
        way the sports trainer hands the user a downloadable file (ZWO/CSV/etc)."""
        tool_names = {t.name for t in get_tools_for_request(is_sports=True)}
        assert "create_file" in tool_names
        assert "execute_code" not in tool_names

    @pytest.mark.usefixtures("every_tool_available")
    def test_sports_mode_keeps_the_training_tools(self) -> None:
        """Garmin and Rouvy are the core of the sports feature - never withheld."""
        assert {"garmin_connect", "garmin_workout", "rouvy_workout"} <= _names(is_sports=True)

    @pytest.mark.usefixtures("every_tool_available")
    def test_language_mode_excludes_irrelevant_tools(self) -> None:
        """Language conversations additionally drop the garmin pair."""
        names = _names(is_language=True)
        assert not LANGUAGE_WITHHELD & names
        assert {"kv_store", "web_search"} <= names

    def test_regular_chat_keeps_all_tools(self) -> None:
        """Subsetting applies only to program conversations."""
        tool_names = {t.name for t in get_tools_for_request()}
        available = {t.name for t in get_available_tools()}
        assert tool_names == available | {"propose_deep_research"}

    def test_agent_permissions_always_include_kv_store(self) -> None:
        """Interactive agent turns must get kv_store, matching get_tools_for_agent."""
        tools = get_tools_for_request(agent_tool_permissions=["web_search"])
        tool_names = {t.name for t in tools}
        assert "kv_store" in tool_names

    def test_agent_empty_permissions_include_kv_store(self) -> None:
        """Even an agent with no extra integrations gets kv_store."""
        tools = get_tools_for_request(agent_tool_permissions=[])
        tool_names = {t.name for t in tools}
        assert "kv_store" in tool_names

    def test_agent_unrestricted_permissions_include_kv_store(self) -> None:
        """Agent with tool_permissions=None (all tools) still gets kv_store via is_agent."""
        tools = get_tools_for_request(agent_tool_permissions=None, is_agent=True)
        tool_names = {t.name for t in tools}
        assert "kv_store" in tool_names

    def test_non_agent_request_excludes_kv_store(self) -> None:
        """Regular (non-agent, non-sports, non-language) chats must not get kv_store."""
        tools = get_tools_for_request()
        tool_names = {t.name for t in tools}
        assert "kv_store" not in tool_names

    def test_restricted_agent_does_not_get_manage_memory(self) -> None:
        """Memory writes are a granted capability for agents, not a baseline one.

        An unattended run that reads the web could otherwise persist
        attacker-controlled text into memory that is injected into every later
        conversation.
        """
        tools = get_tools_for_request(agent_tool_permissions=["web_search"])
        assert "manage_memory" not in {t.name for t in tools}

    def test_agent_granted_manage_memory_gets_it(self) -> None:
        """An explicit grant is honoured."""
        tools = get_tools_for_request(agent_tool_permissions=["manage_memory"])
        assert "manage_memory" in {t.name for t in tools}


class TestGetToolsForAgent:
    """Tool binding for autonomous agent runs."""

    @staticmethod
    def _agent(tool_permissions: list[str] | None) -> MagicMock:
        """Minimal agent stub for tool selection."""
        agent = MagicMock()
        agent.id = "agent-1"
        agent.user_id = "user-1"
        agent.tool_permissions = tool_permissions
        return agent

    def test_restricted_agent_does_not_get_manage_memory(self) -> None:
        """Baseline agent tools must not include long-term memory writes."""
        from src.agent.tools import get_tools_for_agent

        tools = get_tools_for_agent(self._agent(["web_search"]))
        assert "manage_memory" not in {t.name for t in tools}

    def test_agent_with_empty_permissions_does_not_get_manage_memory(self) -> None:
        """tool_permissions=[] means no extra capabilities at all."""
        from src.agent.tools import get_tools_for_agent

        tools = get_tools_for_agent(self._agent([]))
        assert "manage_memory" not in {t.name for t in tools}

    def test_agent_granted_manage_memory_gets_it(self) -> None:
        """An explicit grant is honoured."""
        from src.agent.tools import get_tools_for_agent

        tools = get_tools_for_agent(self._agent(["manage_memory"]))
        assert "manage_memory" in {t.name for t in tools}

    def test_unrestricted_agent_keeps_manage_memory(self) -> None:
        """tool_permissions=None means unrestricted, including memory."""
        from src.agent.tools import get_tools_for_agent

        tools = get_tools_for_agent(self._agent(None))
        assert "manage_memory" in {t.name for t in tools}

    def test_every_bound_tool_passes_the_permission_gate(self) -> None:
        """A bound tool the gate then refuses wastes a model round on an error.

        create_file and trigger_agent were bound for every agent but denied at
        call time unless listed in tool_permissions (same class of bug as the
        kv_store fix in 0be1fb1).
        """
        from src.agent.permissions import PermissionResult, check_tool_permission
        from src.agent.tools import get_tools_for_agent

        for permissions in ([], ["web_search"], ["todoist"]):
            agent = self._agent(permissions)
            for tool in get_tools_for_agent(agent):
                result = check_tool_permission(agent, tool.name, {})
                assert result == PermissionResult.ALLOWED, (permissions, tool.name)

    def test_trigger_agent_only_when_granted(self) -> None:
        """Handing another agent a message is a capability, not a baseline tool."""
        from src.agent.tools import get_tools_for_agent

        assert "trigger_agent" not in {t.name for t in get_tools_for_agent(self._agent([]))}
        granted = get_tools_for_agent(self._agent(["trigger_agent"]))
        assert "trigger_agent" in {t.name for t in granted}
        assert "trigger_agent" in {t.name for t in get_tools_for_agent(self._agent(None))}


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
    def _agent(tool_permissions: list[str] | None) -> MagicMock:
        agent = MagicMock()
        agent.id = "agent-1"
        agent.user_id = "user-1"
        agent.tool_permissions = tool_permissions
        return agent

    @pytest.mark.parametrize(("tool_name", "check"), _INTEGRATIONS)
    def test_unavailable_integration_is_dropped(self, tool_name: str, check: str) -> None:
        from src.agent.tools import get_tools_for_agent

        with patch(check, return_value=False), patch.object(Config, "BROWSER_ENABLED", True):
            requested = get_tools_for_request(agent_tool_permissions=[tool_name])
            agent_run = get_tools_for_agent(self._agent([tool_name]))
        assert tool_name not in {t.name for t in requested}
        assert tool_name not in {t.name for t in agent_run}

    @pytest.mark.parametrize(("tool_name", "check"), _INTEGRATIONS)
    def test_available_integration_is_bound(self, tool_name: str, check: str) -> None:
        from src.agent.tools import get_tools_for_agent

        with patch(check, return_value=True), patch.object(Config, "BROWSER_ENABLED", True):
            requested = get_tools_for_request(agent_tool_permissions=[tool_name])
            agent_run = get_tools_for_agent(self._agent([tool_name]))
        assert tool_name in {t.name for t in requested}
        assert tool_name in {t.name for t in agent_run}

    @pytest.mark.parametrize("enabled", [True, False])
    def test_config_switches_gate_browser_and_code(self, enabled: bool) -> None:
        from src.agent.tools import get_tools_for_agent

        names = ["browser", "execute_code"]
        with (
            patch("src.agent.tools.is_browser_available", return_value=True),
            patch.object(Config, "BROWSER_ENABLED", enabled),
            patch.object(Config, "CODE_SANDBOX_ENABLED", enabled),
        ):
            requested = {t.name for t in get_tools_for_request(agent_tool_permissions=names)}
            agent_run = {t.name for t in get_tools_for_agent(self._agent(names))}
        assert (set(names) <= requested) is enabled
        assert (set(names) <= agent_run) is enabled

    def test_whatsapp_needs_the_app_for_requests_and_a_phone_for_agents(self) -> None:
        from src.agent.tools import get_tools_for_agent

        with (
            patch("src.agent.tools.is_whatsapp_available", return_value=True),
            patch("src.agent.tools._is_whatsapp_available_for_user", return_value=False) as phone,
        ):
            requested = get_tools_for_request(agent_tool_permissions=["whatsapp"])
            agent_run = get_tools_for_agent(self._agent(["whatsapp"]))
        assert "whatsapp" in {t.name for t in requested}
        assert "whatsapp" not in {t.name for t in agent_run}
        phone.assert_called_with("user-1")

    def test_unknown_permissions_and_duplicates_are_ignored(self) -> None:
        tools = get_tools_for_request(agent_tool_permissions=["no_such_tool", "web_search"])
        assert [t.name for t in tools].count("web_search") == 1

    def test_unrestricted_agent_gets_every_available_integration(self) -> None:
        from src.agent.tools import get_tools_for_agent

        with (
            patch("src.agent.tools.is_todoist_available", return_value=True),
            patch("src.agent.tools.is_google_calendar_available", return_value=False),
            patch("src.agent.tools.is_garmin_available", return_value=True),
            patch("src.agent.tools.is_rouvy_available", return_value=False),
            patch("src.agent.tools._is_whatsapp_available_for_user", return_value=True),
            patch.object(Config, "CODE_SANDBOX_ENABLED", False),
            patch.object(Config, "BROWSER_ENABLED", False),
        ):
            names = [t.name for t in get_tools_for_agent(self._agent(None))]
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
