"""Unit tests for system prompt assembly in src/agent/prompts.py."""

from src.agent.prompts import (
    get_force_tools_prompt,
    get_system_prompt,
    get_user_context,
)


class TestGetSystemPrompt:
    """Tests for get_system_prompt function."""

    def test_includes_tool_instructions_by_default(self) -> None:
        """With tools enabled, prompt should include tool instructions."""
        prompt = get_system_prompt(with_tools=True)
        assert "web_search" in prompt
        assert "generate_image" in prompt
        assert "fetch_url" in prompt

    def test_excludes_tool_instructions_when_disabled(self) -> None:
        """With tools disabled, prompt should not include tool instructions."""
        prompt = get_system_prompt(with_tools=False)
        # Should still have base prompt
        assert "helpful" in prompt.lower()
        # But not tool-specific instructions
        assert "METADATA:" not in prompt

    def test_includes_force_tools_instruction(self) -> None:
        """Should include force tools instruction when specified."""
        prompt = get_system_prompt(with_tools=True, force_tools=["web_search"])
        assert "MUST use the following tools" in prompt
        assert "web_search" in prompt

    def test_includes_multiple_force_tools(self) -> None:
        """Should list all forced tools."""
        prompt = get_system_prompt(with_tools=True, force_tools=["web_search", "generate_image"])
        assert "web_search" in prompt
        assert "generate_image" in prompt

    def test_includes_current_date(self) -> None:
        """Prompt should include current date/time."""
        prompt = get_system_prompt()
        assert "Current date and time:" in prompt

    def test_base_prompt_content(self) -> None:
        """Prompt should include base instructions."""
        prompt = get_system_prompt(with_tools=False)
        assert "helpful" in prompt.lower()
        assert "markdown" in prompt.lower()


class TestConversationTitleContext:
    """Current-title injection so the agent can judge title staleness."""

    def test_system_prompt_includes_current_title(self) -> None:
        prompt = get_system_prompt(conversation_title="🐍 Python List Sorting")
        assert "🐍 Python List Sorting" in prompt
        assert "set_conversation_title" in prompt

    def test_dynamic_parts_include_current_title(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        dynamic = get_dynamic_prompt_parts(conversation_title="🐍 Python List Sorting")
        assert "🐍 Python List Sorting" in dynamic
        assert "set_conversation_title" in dynamic

    def test_no_title_context_when_absent(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        assert "set_conversation_title" not in get_dynamic_prompt_parts()
        prompt = get_system_prompt(with_tools=False)
        assert "set_conversation_title" not in prompt

    def test_no_title_context_in_program_modes(self) -> None:
        """Sports/language/planner conversations keep their titles — no nudge."""
        from src.agent.prompts import get_dynamic_prompt_parts

        for kwargs in (
            {"is_sports": True},
            {"is_language": True},
            {"is_planning": True},
        ):
            dynamic = get_dynamic_prompt_parts(
                conversation_title="🏃 Running Program",
                **kwargs,  # type: ignore[arg-type]
            )
            assert "set_conversation_title" not in dynamic


class TestGetForceToolsPrompt:
    """Tests for get_force_tools_prompt function."""

    def test_single_tool(self) -> None:
        """Should format single tool correctly."""
        prompt = get_force_tools_prompt(["web_search"])
        assert "MUST use the following tools" in prompt
        assert "- web_search" in prompt

    def test_multiple_tools(self) -> None:
        """Should format multiple tools correctly."""
        prompt = get_force_tools_prompt(["web_search", "fetch_url"])
        assert "- web_search" in prompt
        assert "- fetch_url" in prompt

    def test_empty_list(self) -> None:
        """Empty list should still generate prompt structure."""
        prompt = get_force_tools_prompt([])
        assert "MUST use the following tools" in prompt


class TestGetUserContext:
    """Tests for get_user_context function."""

    def test_returns_empty_string_when_no_context(self) -> None:
        """Should return empty string when no user name and no location configured."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = ""
            context = get_user_context(user_name=None)
            assert context == ""

    def test_includes_user_name_when_provided(self) -> None:
        """Should include user name section when provided."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = ""
            context = get_user_context(user_name="John Doe")
            assert "# User Context" in context
            assert "## User" in context
            assert "John Doe" in context

    def test_includes_location_when_configured(self) -> None:
        """Should include location section when USER_LOCATION is set."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = "Prague, Czech Republic"
            context = get_user_context(user_name=None)
            assert "# User Context" in context
            assert "## Location" in context
            assert "Prague, Czech Republic" in context

    def test_location_includes_usage_guidance(self) -> None:
        """Should include guidance on how to use location context."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = "New York, USA"
            context = get_user_context(user_name=None)
            assert "measurement units" in context.lower()
            assert "currency" in context.lower()
            assert "local" in context.lower()

    def test_includes_both_user_name_and_location(self) -> None:
        """Should include both sections when both are provided."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = "Prague, Czech Republic"
            context = get_user_context(user_name="John Doe")
            assert "## User" in context
            assert "John Doe" in context
            assert "## Location" in context
            assert "Prague, Czech Republic" in context


class TestGetSystemPromptWithUserContext:
    """Tests for get_system_prompt with user context integration."""

    def test_includes_user_name_in_prompt(self) -> None:
        """Should include user name in system prompt when provided."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = ""
            prompt = get_system_prompt(user_name="Alice")
            assert "Alice" in prompt
            assert "User Context" in prompt

    def test_includes_location_in_prompt(self) -> None:
        """Should include location in system prompt when configured."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = "London, UK"
            prompt = get_system_prompt(user_name=None)
            assert "London, UK" in prompt

    def test_no_user_context_when_not_configured(self) -> None:
        """Should not include user context section when nothing is configured."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = ""
            prompt = get_system_prompt(user_name=None)
            assert "# User Context" not in prompt


class TestGetSystemPromptAnonymousMode:
    """Tests for get_system_prompt with anonymous_mode parameter."""

    def test_excludes_memories_in_anonymous_mode(self) -> None:
        """Should NOT include user memories when anonymous_mode is True."""
        from unittest.mock import patch

        with patch("src.agent.prompts.get_user_memories_prompt") as mock_memories:
            mock_memories.return_value = "# User Memories\n- User prefers dark mode"

            # With user_id and anonymous_mode=True, memories should be skipped
            get_system_prompt(
                with_tools=True,
                user_id="user-123",
                anonymous_mode=True,
            )

            # get_user_memories_prompt should NOT be called
            mock_memories.assert_not_called()

    def test_includes_memories_when_not_anonymous(self) -> None:
        """Should include user memories when anonymous_mode is False."""
        from unittest.mock import patch

        with patch("src.agent.prompts.get_user_memories_prompt") as mock_memories:
            mock_memories.return_value = "# User Memories\n- User prefers dark mode"

            # With user_id and anonymous_mode=False (default), memories should be included
            prompt = get_system_prompt(
                with_tools=True,
                user_id="user-123",
                anonymous_mode=False,
            )

            # get_user_memories_prompt should be called
            mock_memories.assert_called_once_with("user-123")
            assert "User Memories" in prompt

    def test_anonymous_mode_default_is_false(self) -> None:
        """Should default to anonymous_mode=False (include memories)."""
        from unittest.mock import patch

        with patch("src.agent.prompts.get_user_memories_prompt") as mock_memories:
            mock_memories.return_value = "# User Memories\n- Memory content"

            # When anonymous_mode is not specified, memories should be included
            get_system_prompt(
                with_tools=True,
                user_id="user-456",
            )

            mock_memories.assert_called_once_with("user-456")

    def test_anonymous_mode_still_includes_other_features(self) -> None:
        """Anonymous mode should still include tools, user context, etc."""
        from unittest.mock import patch

        with patch("src.agent.prompts.Config") as mock_config:
            mock_config.USER_LOCATION = "Prague, Czech Republic"

            prompt = get_system_prompt(
                with_tools=True,
                user_name="John",
                anonymous_mode=True,
            )

            # Tools should still be included
            assert "web_search" in prompt
            assert "generate_image" in prompt

            # User context (name, location) should still be included
            assert "John" in prompt
            assert "Prague" in prompt
