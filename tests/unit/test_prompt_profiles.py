"""The static prompt profiles and the per-turn dynamic context.

Each profile's static prompt leads the request as the SystemMessage, so
Gemini's implicit cache reuses it (with the tools) across turns; the dynamic
context rides at the tail.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from langchain_google_genai._function_utils import convert_to_genai_function_declarations

from src.agent.prompts import CacheProfile
from src.agent.tools.artifacts import update_artifact
from src.agent.tools.browser import browser


class TestCacheProfile:
    """Tests for CacheProfile enum."""

    def test_standard_profile(self) -> None:
        assert CacheProfile.STANDARD.value == "standard"

    def test_anonymous_profile(self) -> None:
        assert CacheProfile.ANONYMOUS.value == "anonymous"

    def test_planning_profile(self) -> None:
        assert CacheProfile.PLANNING.value == "planning"

    def test_no_program_cache_profiles(self) -> None:
        """One profile for all standing chats (agent / sports / language) - their
        instructions ride in the dynamic part - and none per program."""
        assert {p.name for p in CacheProfile} == {"STANDARD", "ANONYMOUS", "PLANNING", "STANDING"}

    def test_standing_profile_has_the_standard_static_prompt(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        assert get_static_prompt_for_profile("standing") == get_static_prompt_for_profile(
            "standard"
        )


class TestGetStaticPromptForProfile:
    """Tests for static prompt generation per profile."""

    def test_standard_includes_productivity(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("standard")
        assert "Strategic Productivity Partner" in prompt
        assert "Core Principles" in prompt
        assert "Tools Available" in prompt

    def test_standard_without_productivity_integrations(self) -> None:
        """A user with neither Todoist nor Calendar connected skips their section."""
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("standard", productivity=False)
        assert "Strategic Productivity Partner" not in prompt
        assert "Tools Available" in prompt

    def test_anonymous_excludes_productivity(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("anonymous")
        assert "Strategic Productivity Partner" not in prompt
        assert "Tools Available" in prompt
        assert "Core Principles" in prompt

    def test_planning_includes_planner(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("planning")
        assert "Strategic Productivity Partner" in prompt
        assert "Planner Mode" in prompt
        assert "Daily Planning Session" in prompt

    def test_standard_excludes_planner(self) -> None:
        from src.agent.prompts import get_static_prompt_for_profile

        prompt = get_static_prompt_for_profile("standard")
        assert "Planner Mode" not in prompt


# ============ get_dynamic_prompt_parts Tests ============


class TestGetDynamicPromptParts:
    """Tests for dynamic prompt generation."""

    def test_includes_datetime(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts()
        assert "Current date and time:" in result

    def test_includes_user_name(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(user_name="Alice")
        assert "Alice" in result

    def test_includes_custom_instructions(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(custom_instructions="Always respond in Czech")
        assert "Always respond in Czech" in result

    @patch("src.agent.prompt_memory.db")
    def test_includes_memory_list(self, mock_db: MagicMock) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        mock_db.list_memories.return_value = []
        result = get_dynamic_prompt_parts(user_id="user-1")
        assert "Current Memories" in result

    @patch("src.agent.prompt_memory.db")
    def test_excludes_static_memory_instructions(self, mock_db: MagicMock) -> None:
        """The instructions are invariant, so they belong in the cached prefix.

        Bundling them with the per-request memory list re-sent ~1k uncached
        tokens on every single request.
        """
        from src.agent.prompts import get_dynamic_prompt_parts, get_static_prompt_for_profile

        mock_db.list_memories.return_value = []
        dynamic = get_dynamic_prompt_parts(user_id="user-1")

        assert "User Memory System" not in dynamic
        assert "User Memory System" in get_static_prompt_for_profile("standard")

    def test_excludes_memories_in_anonymous(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(user_id="user-1", anonymous_mode=True)
        assert "Current Memories" not in result

    def test_anonymous_static_prompt_has_no_memory_instructions(self) -> None:
        """Anonymous conversations have no memory tool, so no instructions either."""
        from src.agent.prompts import get_static_prompt_for_profile

        assert "User Memory System" not in get_static_prompt_for_profile("anonymous")

    def test_includes_force_tools(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts

        result = get_dynamic_prompt_parts(force_tools=["web_search"])
        assert "Mandatory Tool Usage" in result
        assert "web_search" in result

    def test_includes_the_standing_chat_section(self) -> None:
        from src.agent.prompts import get_dynamic_prompt_parts
        from src.agent.standing import StandingContext

        result = get_dynamic_prompt_parts(
            standing=StandingContext(
                "sports", "Marathon Prep", "Coach the marathon plan", '{"goal": "sub-4h"}', "sports"
            )
        )
        assert "# This Chat: Marathon Prep" in result
        assert "Coach the marathon plan" in result
        assert "sub-4h" in result

    def test_language_instructions_reach_the_prompt(self) -> None:
        """A language chat's quiz rules ride in the per-turn part (the quiz XOR
        conversation contract the client's quiz renderer depends on)."""
        from src.agent.prompt_programs import format_program_kv_data
        from src.agent.prompt_texts.language import LANGUAGE_TUTOR_SYSTEM_PROMPT
        from src.agent.prompts import get_dynamic_prompt_parts
        from src.agent.standing import StandingContext

        instructions = LANGUAGE_TUTOR_SYSTEM_PROMPT.format(
            program_name="Spanish", program_id="spanish", kv_data_section=""
        )
        data = format_program_kv_data("language", {"kv_data": {}})
        result = get_dynamic_prompt_parts(
            standing=StandingContext("language", "Spanish", instructions, data, "language")
        )
        assert "```quiz" in result
        assert "No data stored yet" in result

    def test_standing_section_in_the_uncached_prompt(self) -> None:
        from src.agent.prompts import get_system_prompt
        from src.agent.standing import StandingContext

        prompt = get_system_prompt(
            standing=StandingContext("agent", "VWCE Watcher", "Watch VWCE weekly", None, "agent:a1")
        )
        assert "# This Chat: VWCE Watcher" in prompt
        assert "Watch VWCE weekly" in prompt


# ============ Cache invalidation by content ============


class TestNestedToolSchemas:
    """Pydantic puts nested argument models under `$defs` and langchain logs
    "Key '$defs' is not supported in schema, ignoring" for them. That is only
    noise while langchain inlines each `$ref` before dropping `$defs`; these
    tests catch an upgrade that stops inlining and sends Gemini a bare array."""

    @staticmethod
    def _items(tool: Any, field: str) -> dict[str, Any]:
        converted = convert_to_genai_function_declarations([tool])
        genai_tool = converted[0] if isinstance(converted, list) else converted
        declaration = genai_tool.model_dump(exclude_none=True)["function_declarations"][0]
        items: dict[str, Any] = declaration["parameters"]["properties"][field]["items"]
        return items

    def test_artifact_edits_reach_gemini(self) -> None:
        items = self._items(update_artifact, "edits")
        assert set(items["properties"]) == {"find", "replace"}
        assert items["required"] == ["find", "replace"]

    def test_browser_steps_reach_gemini(self) -> None:
        items = self._items(browser, "actions")
        assert {"action", "url", "selector", "text"} <= set(items["properties"])
        assert items["required"] == ["action"]
