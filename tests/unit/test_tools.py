"""Unit tests for tool selection in the src/agent/tools package (__init__.py)."""

from unittest.mock import MagicMock

from src.agent.tools import (
    get_available_tools,
    get_tools_for_request,
)


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

    def test_returns_fewer_or_same_tools_in_anonymous_mode(self) -> None:
        """Should return same or fewer tools in anonymous mode.

        Note: the exact count depends on which integration tools are configured.
        manage_memory is always withheld, so anonymous mode returns at least one
        fewer tool than a standard request.
        """
        normal_tools = get_tools_for_request(anonymous_mode=False)
        anonymous_tools = get_tools_for_request(anonymous_mode=True)

        # Anonymous mode should have same or fewer tools
        assert len(anonymous_tools) <= len(normal_tools)

        # Count how many of the withheld tools are actually available. Derived
        # from the module's own set so adding a withheld tool cannot make this
        # test wrong without also making it fail loudly.
        from src.agent.tools import _ANONYMOUS_EXCLUDED_TOOLS

        normal_tool_names = {t.name for t in normal_tools}
        withheld_available = len(_ANONYMOUS_EXCLUDED_TOOLS & normal_tool_names)

        # Should be exactly this many fewer
        assert len(anonymous_tools) == len(normal_tools) - withheld_available
        assert not _ANONYMOUS_EXCLUDED_TOOLS & {t.name for t in anonymous_tools}

    def test_default_parameter_is_false(self) -> None:
        """Should default to anonymous_mode=False."""
        tools = get_tools_for_request()
        assert [t for t in tools if t.name != "propose_deep_research"] == get_available_tools()

    def test_sports_mode_excludes_irrelevant_tools(self) -> None:
        """Sports conversations must not carry todoist/whatsapp/calendar/
        places/image-gen/code declarations - ~7k tokens re-sent every tool
        round for tools a fitness program never uses."""
        from src.agent.tools import _SPORTS_EXCLUDED_TOOLS

        tool_names = {t.name for t in get_tools_for_request(is_sports=True)}
        assert not _SPORTS_EXCLUDED_TOOLS & tool_names
        # Core sports tools must survive
        assert "kv_store" in tool_names
        assert "web_search" in tool_names
        assert "manage_memory" in tool_names
        # create_file replaces execute_code for producing downloadable files
        # (e.g. ZWO workouts) in the context-lean sports profile.
        assert "create_file" in tool_names

    def test_sports_mode_keeps_create_file(self) -> None:
        """execute_code is dropped for sports, so create_file must remain the
        way the sports trainer hands the user a downloadable file (ZWO/CSV/etc)."""
        tool_names = {t.name for t in get_tools_for_request(is_sports=True)}
        assert "create_file" in tool_names
        assert "execute_code" not in tool_names

    def test_sports_mode_keeps_garmin_tools(self) -> None:
        """Garmin tools are the core of the sports feature - never excluded.
        (Only asserted via the exclusion set: garmin availability depends on
        integration config, so presence cannot be asserted directly.)"""
        from src.agent.tools import _SPORTS_EXCLUDED_TOOLS

        assert "garmin_connect" not in _SPORTS_EXCLUDED_TOOLS
        assert "garmin_workout" not in _SPORTS_EXCLUDED_TOOLS

    def test_language_mode_excludes_irrelevant_tools(self) -> None:
        """Language conversations additionally drop the garmin pair."""
        from src.agent.tools import _LANGUAGE_EXCLUDED_TOOLS

        tool_names = {t.name for t in get_tools_for_request(is_language=True)}
        assert not _LANGUAGE_EXCLUDED_TOOLS & tool_names
        assert "garmin_connect" in _LANGUAGE_EXCLUDED_TOOLS
        assert "kv_store" in tool_names
        assert "web_search" in tool_names

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
