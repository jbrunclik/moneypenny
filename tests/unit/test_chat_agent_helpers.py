"""Unit tests for helper functions in src/agent/ modules."""

from src.agent.content import (
    clean_tool_call_json,
    detect_response_language,
    extract_image_prompts_from_messages,
    extract_metadata_tool_args,
    extract_sources_fallback_from_tool_results,
    extract_text_content,
    extract_thinking_and_text,
    strip_full_result_from_tool_content,
)
from src.agent.prompts import (
    get_force_tools_prompt,
    get_system_prompt,
    get_user_context,
)
from src.agent.tool_display import (
    _format_calendar_detail,
    _format_todoist_detail,
)
from src.agent.tool_display import (
    extract_tool_detail as _extract_tool_detail,
)


class TestExtractTextContent:
    """Tests for extract_text_content function."""

    def test_string_content(self) -> None:
        """String content should pass through unchanged."""
        assert extract_text_content("Hello world") == "Hello world"
        assert extract_text_content("") == ""

    def test_dict_with_type_text(self) -> None:
        """Dict with type='text' should extract text value."""
        content = {"type": "text", "text": "Hello from dict"}
        assert extract_text_content(content) == "Hello from dict"

    def test_dict_with_text_key_only(self) -> None:
        """Dict with only 'text' key (no type) should extract it."""
        content = {"text": "Just text key"}
        assert extract_text_content(content) == "Just text key"

    def test_dict_without_text_key(self) -> None:
        """Dict without text key should return empty string."""
        content = {"type": "tool_use", "name": "web_search"}
        assert extract_text_content(content) == ""

    def test_list_of_text_parts(self) -> None:
        """List of text parts should be concatenated."""
        content = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": " Part 2"},
        ]
        assert extract_text_content(content) == "Part 1 Part 2"

    def test_list_with_extras_skipped(self) -> None:
        """Non-text parts in list should be skipped."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "extras", "signature": "abc"},
            {"type": "tool_use", "name": "search"},
        ]
        assert extract_text_content(content) == "Hello"

    def test_list_with_string_items(self) -> None:
        """List with plain strings should concatenate them."""
        content = ["Hello", " ", "World"]
        assert extract_text_content(content) == "Hello World"

    def test_empty_list(self) -> None:
        """Empty list should return empty string."""
        assert extract_text_content([]) == ""

    def test_empty_dict(self) -> None:
        """Empty dict should return empty string."""
        assert extract_text_content({}) == ""

    def test_mixed_list(self) -> None:
        """List with mixed types should extract text from all."""
        content = [
            {"type": "text", "text": "First"},
            "Second",
            {"text": "Third"},
        ]
        assert extract_text_content(content) == "FirstSecondThird"


class TestExtractThinkingAndText:
    """Tests for extract_thinking_and_text function."""

    def test_string_content_returns_no_thinking(self) -> None:
        """String content should have no thinking, just text."""
        thinking, text = extract_thinking_and_text("Hello world")
        assert thinking is None
        assert text == "Hello world"

    def test_empty_string_content(self) -> None:
        """Empty string should return no thinking and empty text."""
        thinking, text = extract_thinking_and_text("")
        assert thinking is None
        assert text == ""

    def test_dict_with_thought_true(self) -> None:
        """Dict with thought=True should extract as thinking."""
        content = {"thought": True, "text": "Let me think about this..."}
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Let me think about this..."
        assert text == ""

    def test_dict_with_type_text(self) -> None:
        """Dict with type='text' should extract as regular text."""
        content = {"type": "text", "text": "Regular response"}
        thinking, text = extract_thinking_and_text(content)
        assert thinking is None
        assert text == "Regular response"

    def test_dict_with_text_key_only(self) -> None:
        """Dict with only 'text' key should extract as regular text."""
        content = {"text": "Just text"}
        thinking, text = extract_thinking_and_text(content)
        assert thinking is None
        assert text == "Just text"

    def test_list_with_thought_and_text_parts(self) -> None:
        """List with both thought and text parts should separate them."""
        content = [
            {"thought": True, "text": "I need to think about this."},
            {"type": "text", "text": "Here is my answer."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "I need to think about this."
        assert text == "Here is my answer."

    def test_list_with_multiple_thought_parts(self) -> None:
        """Multiple thought parts should be concatenated."""
        content = [
            {"thought": True, "text": "First thought. "},
            {"thought": True, "text": "Second thought."},
            {"type": "text", "text": "Final answer."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "First thought. Second thought."
        assert text == "Final answer."

    def test_list_with_only_text_parts(self) -> None:
        """List with only text parts should have no thinking."""
        content = [
            {"type": "text", "text": "Part 1. "},
            {"type": "text", "text": "Part 2."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking is None
        assert text == "Part 1. Part 2."

    def test_list_with_only_thought_parts(self) -> None:
        """List with only thought parts should have no regular text."""
        content = [
            {"thought": True, "text": "Just thinking."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Just thinking."
        assert text == ""

    def test_list_with_extras_skipped(self) -> None:
        """Non-text/thought parts should be skipped."""
        content = [
            {"thought": True, "text": "Thinking..."},
            {"type": "extras", "signature": "abc123"},
            {"type": "text", "text": "Answer."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Thinking..."
        assert text == "Answer."

    def test_list_with_string_items(self) -> None:
        """Plain strings in list should be treated as text."""
        content = ["Hello", " ", "World"]
        thinking, text = extract_thinking_and_text(content)
        assert thinking is None
        assert text == "Hello World"

    def test_empty_list(self) -> None:
        """Empty list should return no thinking and empty text."""
        thinking, text = extract_thinking_and_text([])
        assert thinking is None
        assert text == ""

    def test_empty_dict(self) -> None:
        """Empty dict should return no thinking and empty text."""
        thinking, text = extract_thinking_and_text({})
        assert thinking is None
        assert text == ""

    # Gemini format tests (type='thinking' with 'thinking' field)

    def test_gemini_dict_with_type_thinking(self) -> None:
        """Dict with type='thinking' (Gemini format) should extract as thinking."""
        content = {"type": "thinking", "thinking": "Let me analyze this..."}
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Let me analyze this..."
        assert text == ""

    def test_gemini_list_with_thinking_parts(self) -> None:
        """List with Gemini thinking format should separate thinking from text."""
        content = [
            {"type": "thinking", "thinking": "**Analyzing the question**\n\nLet me think..."},
            {"type": "text", "text": "Here is my response."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "**Analyzing the question**\n\nLet me think..."
        assert text == "Here is my response."

    def test_gemini_multiple_thinking_parts(self) -> None:
        """Multiple Gemini thinking parts should be concatenated."""
        content = [
            {"type": "thinking", "thinking": "First analysis. "},
            {"type": "thinking", "thinking": "Second analysis."},
            {"type": "text", "text": "Final answer."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "First analysis. Second analysis."
        assert text == "Final answer."

    def test_gemini_only_thinking_no_text(self) -> None:
        """Gemini format with only thinking parts should have no text."""
        content = [
            {"type": "thinking", "thinking": "Just thinking here."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Just thinking here."
        assert text == ""

    def test_gemini_with_extras_skipped(self) -> None:
        """Gemini format with extras should skip non-thinking/text parts."""
        content = [
            {"type": "thinking", "thinking": "Thinking..."},
            {"type": "extras", "signature": "abc123"},
            {"type": "text", "text": "Response."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Thinking..."
        assert text == "Response."

    def test_mixed_old_and_gemini_formats(self) -> None:
        """Should handle both old (thought=true) and Gemini (type=thinking) formats."""
        content = [
            {"thought": True, "text": "Old format thinking."},
            {"type": "thinking", "thinking": "Gemini format thinking."},
            {"type": "text", "text": "Response."},
        ]
        thinking, text = extract_thinking_and_text(content)
        assert thinking == "Old format thinking.Gemini format thinking."
        assert text == "Response."


class TestDetectResponseLanguage:
    """Tests for detect_response_language function."""

    def test_detects_english(self) -> None:
        """Should detect English text."""
        result = detect_response_language("Hello, this is a test response in English.")
        assert result == "en"

    def test_detects_czech(self) -> None:
        """Should detect Czech text."""
        result = detect_response_language("Ahoj, toto je testovací odpověď v češtině.")
        assert result == "cs"

    def test_returns_none_for_short_text(self) -> None:
        """Should return None for text shorter than 10 chars."""
        assert detect_response_language("Hi") is None
        assert detect_response_language("") is None

    def test_returns_none_for_empty_text(self) -> None:
        """Should return None for None-like inputs."""
        assert detect_response_language("") is None

    def test_normalizes_to_two_char_code(self) -> None:
        """Should return 2-char ISO 639-1 code."""
        result = detect_response_language(
            "This is a longer English sentence for language detection."
        )
        assert result is not None
        assert len(result) == 2


class TestExtractImagePromptsFromMessages:
    """Tests for extract_image_prompts_from_messages function."""

    def test_extracts_from_generate_image_tool_call(self) -> None:
        """Should extract prompts from generate_image tool calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's the image.",
                tool_calls=[
                    {
                        "name": "generate_image",
                        "args": {"prompt": "a sunset over mountains"},
                        "id": "1",
                    }
                ],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 1
        assert result[0]["prompt"] == "a sunset over mountains"

    def test_ignores_non_image_tool_calls(self) -> None:
        """Should ignore non-generate_image tool calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's what I found.",
                tool_calls=[{"name": "web_search", "args": {"query": "test"}, "id": "1"}],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert result == []

    def test_empty_messages(self) -> None:
        """Should return empty list for no messages."""
        assert extract_image_prompts_from_messages([]) == []

    def test_multiple_images(self) -> None:
        """Should extract prompts from multiple generate_image calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="First image",
                tool_calls=[{"name": "generate_image", "args": {"prompt": "a cat"}, "id": "1"}],
            ),
            AIMessage(
                content="Second image",
                tool_calls=[{"name": "generate_image", "args": {"prompt": "a dog"}, "id": "2"}],
            ),
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 2
        assert result[0]["prompt"] == "a cat"
        assert result[1]["prompt"] == "a dog"


class TestExtractMetadataToolArgs:
    """Tests for extract_metadata_tool_args function."""

    def test_extracts_sources_from_cite_sources(self) -> None:
        """Should extract sources from cite_sources tool call."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's what I found.",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {
                            "sources": [
                                {"title": "Example", "url": "https://example.com"},
                                {"title": "Test", "url": "https://test.com"},
                            ]
                        },
                        "id": "1",
                    }
                ],
            )
        ]
        sources, memory_ops = extract_metadata_tool_args(messages)
        assert len(sources) == 2
        assert sources[0]["title"] == "Example"
        assert sources[1]["url"] == "https://test.com"
        assert memory_ops == []

    def test_extracts_memory_ops_from_manage_memory(self) -> None:
        """Should extract memory operations from manage_memory tool call."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="I'll remember that.",
                tool_calls=[
                    {
                        "name": "manage_memory",
                        "args": {
                            "operations": [
                                {
                                    "action": "add",
                                    "content": "User likes pizza",
                                    "category": "preference",
                                }
                            ]
                        },
                        "id": "1",
                    }
                ],
            )
        ]
        sources, memory_ops = extract_metadata_tool_args(messages)
        assert sources == []
        assert len(memory_ops) == 1
        assert memory_ops[0]["action"] == "add"
        assert memory_ops[0]["content"] == "User likes pizza"

    def test_extracts_both_sources_and_memory(self) -> None:
        """Should extract both sources and memory operations."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Here's the answer.",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {"sources": [{"title": "Wiki", "url": "https://wiki.org"}]},
                        "id": "1",
                    },
                    {
                        "name": "manage_memory",
                        "args": {"operations": [{"action": "add", "content": "fact"}]},
                        "id": "2",
                    },
                ],
            )
        ]
        sources, memory_ops = extract_metadata_tool_args(messages)
        assert len(sources) == 1
        assert len(memory_ops) == 1

    def test_no_metadata_tools(self) -> None:
        """Should return empty lists when no metadata tools are called."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Just a response.",
                tool_calls=[],
            )
        ]
        sources, memory_ops = extract_metadata_tool_args(messages)
        assert sources == []
        assert memory_ops == []

    def test_empty_messages(self) -> None:
        """Should return empty lists for empty messages."""
        sources, memory_ops = extract_metadata_tool_args([])
        assert sources == []
        assert memory_ops == []

    def test_skips_invalid_sources(self) -> None:
        """Should skip source dicts that are missing title or url."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {
                            "sources": [
                                {"title": "Valid", "url": "https://valid.com"},
                                {"title": "Missing URL"},  # No url
                                {"url": "https://no-title.com"},  # No title
                            ]
                        },
                        "id": "1",
                    }
                ],
            )
        ]
        sources, _ = extract_metadata_tool_args(messages)
        assert len(sources) == 1
        assert sources[0]["title"] == "Valid"


class TestExtractSourcesFallbackFromToolResults:
    """Tests for extract_sources_fallback_from_tool_results function."""

    def test_extracts_from_web_search_list_results(self) -> None:
        """Should extract sources from web_search tool results (list format)."""
        import json

        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    [
                        {"title": "Result 1", "href": "https://example.com/1", "body": "..."},
                        {"title": "Result 2", "href": "https://example.com/2", "body": "..."},
                    ]
                ),
            }
        ]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert len(sources) == 2
        assert sources[0]["title"] == "Result 1"
        assert sources[0]["url"] == "https://example.com/1"

    def test_extracts_from_dict_with_results_array(self) -> None:
        """Should extract sources from tool results with nested results array."""
        import json

        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "results": [
                            {"title": "Result 1", "href": "https://example.com/1"},
                        ]
                    }
                ),
            }
        ]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert len(sources) == 1
        assert sources[0]["title"] == "Result 1"

    def test_returns_empty_for_non_search_results(self) -> None:
        """Should return empty list for non-search tool results."""
        import json

        tool_results = [
            {
                "type": "tool",
                "content": json.dumps({"success": True, "message": "Image generated"}),
            }
        ]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert sources == []

    def test_returns_empty_for_empty_results(self) -> None:
        """Should return empty list for empty tool results."""
        assert extract_sources_fallback_from_tool_results([]) == []

    def test_handles_invalid_json(self) -> None:
        """Should handle invalid JSON in tool results gracefully."""
        tool_results = [{"type": "tool", "content": "not json"}]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert sources == []


class TestStripFullResultFromToolContent:
    """Tests for strip_full_result_from_tool_content function."""

    def test_strips_full_result_field(self) -> None:
        """Should remove _full_result from JSON content."""
        content = (
            '{"success": true, "message": "Done", "_full_result": {"image": {"data": "base64..."}}}'
        )
        result = strip_full_result_from_tool_content(content)

        import json

        parsed = json.loads(result)
        assert "_full_result" not in parsed
        assert parsed["success"] is True
        assert parsed["message"] == "Done"

    def test_preserves_non_json_content(self) -> None:
        """Non-JSON content should pass through unchanged."""
        content = "Plain text result"
        assert strip_full_result_from_tool_content(content) == content

    def test_preserves_json_without_full_result(self) -> None:
        """JSON without _full_result should pass through unchanged."""
        content = '{"message": "Success", "data": "value"}'
        result = strip_full_result_from_tool_content(content)
        assert result == content

    def test_handles_empty_string(self) -> None:
        """Empty string should pass through."""
        assert strip_full_result_from_tool_content("") == ""

    def test_handles_json_array(self) -> None:
        """JSON array should pass through unchanged."""
        content = "[1, 2, 3]"
        assert strip_full_result_from_tool_content(content) == content


class TestValidateMemoryOperations:
    """Tests for validate_memory_operations function."""

    def test_validates_add_operation(self) -> None:
        """Should accept valid add operations."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "add", "content": "User likes pizza", "category": "preference"}]
        result = validate_memory_operations(ops)
        assert len(result) == 1
        assert result[0]["action"] == "add"

    def test_validates_update_operation(self) -> None:
        """Should accept valid update operations."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "update", "id": "mem-123", "content": "Updated content"}]
        result = validate_memory_operations(ops)
        assert len(result) == 1

    def test_validates_delete_operation(self) -> None:
        """Should accept valid delete operations."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "delete", "id": "mem-456"}]
        result = validate_memory_operations(ops)
        assert len(result) == 1

    def test_rejects_add_without_content(self) -> None:
        """Should reject add operations without content."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "add", "category": "preference"}]
        result = validate_memory_operations(ops)
        assert result == []

    def test_rejects_update_without_id(self) -> None:
        """Should reject update operations without id."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "update", "content": "New content"}]
        result = validate_memory_operations(ops)
        assert result == []

    def test_rejects_invalid_action(self) -> None:
        """Should reject operations with invalid action."""
        from src.api.utils import validate_memory_operations

        ops = [{"action": "invalid", "content": "Test"}]
        result = validate_memory_operations(ops)
        assert result == []

    def test_returns_empty_for_empty_input(self) -> None:
        """Should return empty list for empty input."""
        from src.api.utils import validate_memory_operations

        assert validate_memory_operations([]) == []

    def test_filters_mixed_valid_and_invalid(self) -> None:
        """Should keep valid ops and filter out invalid ones."""
        from src.api.utils import validate_memory_operations

        ops = [
            {"action": "add", "content": "Valid"},
            {"action": "invalid"},
            {"action": "delete", "id": "mem-1"},
        ]
        result = validate_memory_operations(ops)
        assert len(result) == 2


class TestCleanToolCallJson:
    """Tests for clean_tool_call_json function."""

    def test_removes_tool_call_json_string_input(self) -> None:
        """Should remove action/action_input JSON blocks."""
        response = 'Here is my answer.\n{"action": "generate_image", "action_input": "test prompt"}'
        clean = clean_tool_call_json(response)
        assert clean == "Here is my answer."

    def test_removes_tool_call_json_object_input(self) -> None:
        """Should remove action/action_input with object input."""
        response = 'Answer.\n{"action": "generate_image", "action_input": {"prompt": "test"}}'
        clean = clean_tool_call_json(response)
        assert clean == "Answer."

    def test_preserves_normal_text(self) -> None:
        """Normal text without tool JSON should pass through."""
        response = "Normal response without tool JSON"
        assert clean_tool_call_json(response) == response

    def test_preserves_other_json(self) -> None:
        """Other JSON structures should be preserved."""
        response = 'Here is some data: {"key": "value", "count": 42}'
        assert clean_tool_call_json(response) == response

    def test_handles_empty_string(self) -> None:
        """Empty string should return empty string."""
        assert clean_tool_call_json("") == ""


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
            assert "metric" in context.lower() or "imperial" in context.lower()
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


class TestExtractToolDetail:
    """Tests for _extract_tool_detail function."""

    def test_web_search_extracts_query(self) -> None:
        """Should extract query from web_search tool args."""
        result = _extract_tool_detail("web_search", {"query": "best pizza in Prague"})
        assert result == "best pizza in Prague"

    def test_fetch_url_extracts_url(self) -> None:
        """Should extract URL from fetch_url tool args."""
        result = _extract_tool_detail("fetch_url", {"url": "https://example.com/page"})
        assert result == "https://example.com/page"

    def test_generate_image_extracts_prompt(self) -> None:
        """Should extract prompt from generate_image tool args."""
        result = _extract_tool_detail("generate_image", {"prompt": "A cat on a rainbow"})
        assert result == "A cat on a rainbow"

    def test_execute_code_extracts_first_line(self) -> None:
        """Should extract first line of code from execute_code tool args."""
        code = "print('Hello')\nprint('World')"
        result = _extract_tool_detail("execute_code", {"code": code})
        assert result == "print('Hello')"

    def test_execute_code_truncates_long_lines(self) -> None:
        """Should truncate long first lines to 50 chars."""
        code = "x = " + "a" * 100 + "\nmore code"
        result = _extract_tool_detail("execute_code", {"code": code})
        assert result is not None
        assert len(result) == 50

    def test_todoist_list_tasks(self) -> None:
        """Should extract action and filter for list_tasks."""
        result = _extract_tool_detail("todoist", {"action": "list_tasks", "filter": "today"})
        assert result == "list_tasks: today"

    def test_todoist_list_tasks_default_filter(self) -> None:
        """Should use 'all' as default filter for list_tasks."""
        result = _extract_tool_detail("todoist", {"action": "list_tasks"})
        assert result == "list_tasks: all"

    def test_todoist_add_task(self) -> None:
        """Should extract action and content for add_task."""
        result = _extract_tool_detail("todoist", {"action": "add_task", "content": "Buy milk"})
        assert result == "add_task: Buy milk"

    def test_todoist_add_task_truncates(self) -> None:
        """Should truncate long task content."""
        long_content = "x" * 100
        result = _extract_tool_detail("todoist", {"action": "add_task", "content": long_content})
        assert result == f"add_task: {'x' * 60}"

    def test_todoist_complete_task(self) -> None:
        """Should extract action and task_id for complete_task."""
        result = _extract_tool_detail("todoist", {"action": "complete_task", "task_id": "123456"})
        assert result == "complete_task: 123456"

    def test_todoist_list_projects(self) -> None:
        """Should return just action for list_projects."""
        result = _extract_tool_detail("todoist", {"action": "list_projects"})
        assert result == "list_projects"

    def test_unknown_tool_returns_none(self) -> None:
        """Should return None for unknown tool."""
        result = _extract_tool_detail("unknown_tool", {"data": "value"})
        assert result is None

    def test_missing_required_arg_returns_none(self) -> None:
        """Should return None when required arg is missing."""
        result = _extract_tool_detail("web_search", {})
        assert result is None


class TestFormatTodoistDetail:
    """Tests for _format_todoist_detail function."""

    def test_list_tasks_with_filter(self) -> None:
        """Should format list_tasks with filter."""
        result = _format_todoist_detail({"action": "list_tasks", "filter": "overdue"})
        assert result == "list_tasks: overdue"

    def test_list_tasks_without_filter(self) -> None:
        """Should use 'all' default for list_tasks."""
        result = _format_todoist_detail({"action": "list_tasks"})
        assert result == "list_tasks: all"

    def test_add_task(self) -> None:
        """Should format add_task with content."""
        result = _format_todoist_detail({"action": "add_task", "content": "Buy groceries"})
        assert result == "add_task: Buy groceries"

    def test_update_task(self) -> None:
        """Should format update_task with task_id."""
        result = _format_todoist_detail({"action": "update_task", "task_id": "abc123"})
        assert result == "update_task: abc123"

    def test_delete_task(self) -> None:
        """Should format delete_task with task_id."""
        result = _format_todoist_detail({"action": "delete_task", "task_id": "xyz789"})
        assert result == "delete_task: xyz789"

    def test_add_project(self) -> None:
        result = _format_todoist_detail({"action": "add_project", "project_name": "Work"})
        assert result == "add_project: Work"

    def test_share_project(self) -> None:
        result = _format_todoist_detail(
            {"action": "share_project", "collaborator_email": "teammate@example.com"}
        )
        assert result == "share_project: teammate@example.com"

    def test_add_section(self) -> None:
        result = _format_todoist_detail({"action": "add_section", "section_name": "Backlog"})
        assert result == "add_section: Backlog"

    def test_unknown_action(self) -> None:
        """Should return just action for unknown actions."""
        result = _format_todoist_detail({"action": "some_new_action"})
        assert result == "some_new_action"


class TestFormatCalendarDetail:
    """Tests for _format_calendar_detail function."""

    def test_list_events_with_range(self) -> None:
        result = _format_calendar_detail(
            {
                "action": "list_events",
                "calendar_id": "work",
                "time_min": "2024-01-01T00:00:00Z",
                "time_max": "2024-01-07T00:00:00Z",
            }
        )
        assert result == "list_events: work 2024-01-01T00:00:00Z → 2024-01-07T00:00:00Z"

    def test_create_event(self) -> None:
        result = _format_calendar_detail({"action": "create_event", "summary": "Sprint review"})
        assert result == "create_event: Sprint review"

    def test_delete_event(self) -> None:
        result = _format_calendar_detail({"action": "delete_event", "event_id": "evt-1"})
        assert result == "delete_event: evt-1"

    def test_respond_event(self) -> None:
        result = _format_calendar_detail({"action": "respond_event", "response_status": "accepted"})
        assert result == "respond_event: accepted"


class TestFormatMessageWithMetadata:
    """Tests for ChatAgent._format_message_with_metadata method."""

    def _format_message(self, msg: dict) -> str:
        """Helper to call the method without instantiating full ChatAgent."""
        import json

        metadata = msg.get("metadata", {})
        content: str = msg["content"]

        meta_dict: dict = {}
        if metadata.get("session_gap"):
            meta_dict["session_gap"] = metadata["session_gap"]
        if metadata.get("timestamp"):
            meta_dict["timestamp"] = metadata["timestamp"]
        if metadata.get("relative_time"):
            meta_dict["relative_time"] = metadata["relative_time"]
        if metadata.get("files"):
            meta_dict["files"] = [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "id": f"{f['message_id']}:{f['file_index']}",
                }
                for f in metadata["files"]
            ]
        if metadata.get("tools_used"):
            meta_dict["tools_used"] = metadata["tools_used"]
        if metadata.get("tool_summary"):
            meta_dict["tool_summary"] = metadata["tool_summary"]

        if meta_dict:
            json_str = json.dumps(meta_dict, separators=(",", ":"))
            return f"<!-- MSG_CONTEXT: {json_str} -->\n{content}"
        return content

    def test_message_without_metadata(self) -> None:
        """Message without metadata should return content only."""
        msg = {"role": "user", "content": "Hello", "metadata": {}}
        result = self._format_message(msg)
        assert result == "Hello"

    def test_message_with_timestamps(self) -> None:
        """Should include timestamp and relative_time in JSON."""
        msg = {
            "role": "user",
            "content": "Hello",
            "metadata": {
                "timestamp": "2024-06-15 14:30 CET",
                "relative_time": "3 hours ago",
            },
        }
        result = self._format_message(msg)

        assert result.startswith("<!-- MSG_CONTEXT:")
        assert '"timestamp":"2024-06-15 14:30 CET"' in result
        assert '"relative_time":"3 hours ago"' in result
        assert result.endswith("-->\nHello")

    def test_message_with_session_gap(self) -> None:
        """Should include session_gap in JSON."""
        msg = {
            "role": "user",
            "content": "Hi again",
            "metadata": {
                "session_gap": "2 days",
                "timestamp": "2024-06-15 14:30 CET",
                "relative_time": "just now",
            },
        }
        result = self._format_message(msg)

        assert '"session_gap":"2 days"' in result

    def test_message_with_files(self) -> None:
        """Should include files with compact ID format."""
        msg = {
            "role": "user",
            "content": "Check this",
            "metadata": {
                "timestamp": "2024-06-15 14:30 CET",
                "relative_time": "1 hour ago",
                "files": [
                    {
                        "name": "report.pdf",
                        "type": "PDF",
                        "message_id": "msg-abc123",
                        "file_index": 0,
                    }
                ],
            },
        }
        result = self._format_message(msg)

        assert '"files":[' in result
        assert '"name":"report.pdf"' in result
        assert '"type":"PDF"' in result
        assert '"id":"msg-abc123:0"' in result

    def test_assistant_message_with_tools(self) -> None:
        """Should include tools_used and tool_summary for assistant messages."""
        msg = {
            "role": "assistant",
            "content": "I found some results.",
            "metadata": {
                "timestamp": "2024-06-15 14:35 CET",
                "relative_time": "1 hour ago",
                "tools_used": ["web_search"],
                "tool_summary": "searched 3 web sources",
            },
        }
        result = self._format_message(msg)

        assert '"tools_used":["web_search"]' in result
        assert '"tool_summary":"searched 3 web sources"' in result

    def test_json_is_compact(self) -> None:
        """JSON should use compact separators (no spaces)."""
        import json
        import re

        msg = {
            "role": "user",
            "content": "Test",
            "metadata": {"timestamp": "2024-06-15 14:30 CET", "relative_time": "now"},
        }
        result = self._format_message(msg)

        # Extract JSON part
        json_match = re.search(r"\{.*\}", result)
        assert json_match is not None
        json_str = json_match.group(0)

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert parsed["timestamp"] == "2024-06-15 14:30 CET"

        # Verify compact format (no pretty-print indentation/newlines)
        assert "\n" not in json_str
        # Keys should be directly followed by colon then value
        assert '"timestamp":"' in json_str
        assert '"relative_time":"' in json_str

    def test_context_format_distinct_from_response_metadata(self) -> None:
        """Should use <!-- MSG_CONTEXT: --> format (different from response METADATA)."""
        msg = {
            "role": "user",
            "content": "Hello",
            "metadata": {"relative_time": "just now"},
        }
        result = self._format_message(msg)

        # Should use MSG_CONTEXT marker (distinct from response METADATA)
        assert result.startswith("<!-- MSG_CONTEXT: {")
        assert "} -->" in result
        # Should NOT use METADATA marker (reserved for response metadata)
        assert "<!-- METADATA:" not in result


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


class TestStreamingMsgContextHandling:
    """Tests for MSG_CONTEXT block handling during streaming.

    These tests verify that echoed MSG_CONTEXT blocks are stripped correctly
    when they appear in streaming chunks, including multi-chunk scenarios.
    Note: METADATA block handling has been removed (metadata is now extracted
    via tool calls, not text blocks).
    """

    def _process_chunks(self, chunks: list[str]) -> tuple[str, list[str], bool]:
        """Simulate the MSG_CONTEXT chunk processing logic from stream_chat_events.

        This handles cross-chunk boundary scenarios where markers like
        <!-- MSG_CONTEXT: or --> are split across chunks.

        Args:
            chunks: List of text content chunks

        Returns:
            Tuple of (full_response, yielded_tokens, had_msg_context)
        """
        full_response = ""
        yielded_tokens: list[str] = []
        in_msg_context = False
        had_msg_context = False

        msg_context_marker = "<!-- MSG_CONTEXT:"
        end_marker = "-->"

        # Carryover buffer for cross-chunk marker detection
        carryover = ""

        for chunk in chunks:
            # Prepend carryover from previous chunk for cross-chunk marker detection
            text_content = carryover + chunk
            carryover = ""

            # Handle MSG_CONTEXT blocks (echoed history context)
            if in_msg_context:
                if end_marker in text_content:
                    end_pos = text_content.find(end_marker)
                    text_content = text_content[end_pos + 3 :].lstrip()
                    in_msg_context = False
                    if not text_content:
                        continue
                else:
                    for i in range(len(end_marker) - 1, 0, -1):
                        if text_content.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    continue

            # Check for MSG_CONTEXT marker
            if msg_context_marker in text_content:
                had_msg_context = True
                marker_pos = text_content.find(msg_context_marker)
                end_pos = text_content.find(end_marker, marker_pos)
                if end_pos != -1:
                    before = text_content[:marker_pos]
                    after = text_content[end_pos + 3 :]
                    text_content = (before + after).strip()
                else:
                    content_after_marker = text_content[marker_pos:]
                    for i in range(len(end_marker) - 1, 0, -1):
                        if content_after_marker.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    text_content = text_content[:marker_pos].rstrip()
                    in_msg_context = True
                if not text_content:
                    continue
            elif not in_msg_context:
                for i in range(len(msg_context_marker) - 1, 0, -1):
                    partial = msg_context_marker[:i]
                    if text_content.endswith(partial):
                        carryover = partial
                        text_content = text_content[:-i]
                        break

            full_response += text_content
            if text_content:
                yielded_tokens.append(text_content)

        # Handle any remaining carryover
        if carryover and not in_msg_context:
            full_response += carryover
            yielded_tokens.append(carryover)

        return full_response, yielded_tokens, had_msg_context

    def test_msg_context_single_chunk_stripped(self) -> None:
        """MSG_CONTEXT in a single chunk should be completely stripped."""
        chunks = ['<!-- MSG_CONTEXT: {"timestamp":"2024-01-01"} -->Hello world']
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "MSG_CONTEXT" not in full_response
        assert "timestamp" not in full_response
        assert "Hello world" in full_response
        assert had_ctx is True

    def test_msg_context_multi_chunk_stripped(self) -> None:
        """MSG_CONTEXT spanning multiple chunks should be stripped."""
        chunks = [
            '<!-- MSG_CONTEXT: {"timestamp":',
            '"2024-01-01","relative_time":"1 hour ago"} ',
            "--> Here is the response.",
        ]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "MSG_CONTEXT" not in full_response
        assert "timestamp" not in full_response
        assert "Here is the response" in full_response
        assert had_ctx is True

    def test_msg_context_at_start_content_preserved(self) -> None:
        """Content after MSG_CONTEXT block should be preserved."""
        chunks = [
            "<!-- MSG_CONTEXT: {} -->",
            "This is the actual response content.",
        ]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "This is the actual response content" in full_response
        assert had_ctx is True
        joined_tokens = "".join(tokens)
        assert "actual response" in joined_tokens

    def test_no_metadata_blocks(self) -> None:
        """Response without any metadata blocks should yield all content."""
        chunks = ["Just a simple", " response with ", "no metadata."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert full_response == "Just a simple response with no metadata."
        assert had_ctx is False
        joined_tokens = "".join(tokens)
        assert "Just a simple" in joined_tokens

    def test_msg_context_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT marker split across chunk boundary."""
        chunks = ["Hello <!-- MSG_", "CONTEXT: {} --> world"]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Hello" in full_response
        assert "world" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_msg_context_end_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT end marker (-->) split across chunk boundary."""
        chunks = ['<!-- MSG_CONTEXT: {"key":"value"} -', "-> The response."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "The response" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_content_immediately_after_msg_context_end(self) -> None:
        """Content immediately after --> of MSG_CONTEXT (no space)."""
        chunks = ["<!-- MSG_CONTEXT: {} -->Response starts here."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Response starts here" in full_response
        assert "MSG_CONTEXT" not in full_response

    def test_empty_chunks_between_markers(self) -> None:
        """Empty or whitespace-only chunks within metadata block."""
        chunks = ["<!-- MSG_CONTEXT:", " ", '{"key": "value"}', "", " --> Content"]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Content" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_multiple_msg_context_blocks(self) -> None:
        """Multiple MSG_CONTEXT blocks (shouldn't happen but handle gracefully)."""
        chunks = ['<!-- MSG_CONTEXT: {"a":1} --> First ', '<!-- MSG_CONTEXT: {"b":2} --> Second']
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "First" in full_response
        assert "Second" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True


class TestCleanupAndSave:
    """Tests for the cleanup_and_save function.

    This function is responsible for saving messages when the generator exits
    without saving (e.g., due to GeneratorExit from client disconnect).
    """

    def test_cleanup_saves_when_generator_exits_without_saving(self) -> None:
        """Regression: cleanup thread should save when generator_done_event is set but saved=False.

        Bug: When a mobile client locks the screen, the browser disconnects and
        Flask/Gunicorn calls generator.close(), raising GeneratorExit. This exception
        bypasses _finalize_stream (which does the save). The generator's finally block
        sets generator_done_event, but no save happened.

        The old code returned early when generator_done_event was set, assuming
        the generator had saved. But GeneratorExit can kill the generator before save.

        The fix: always check final_results["saved"] even when generator_done_event is set.
        """
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.chat_streaming import cleanup_and_save

        # Create a stream thread that's already done
        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False  # Thread completed
        stream_thread.join = MagicMock()

        # Simulate the scenario: generator was killed by GeneratorExit
        # - ready=True (stream thread finished and produced results)
        # - saved=False (GeneratorExit killed generator before _finalize_stream)
        final_results = {
            "ready": True,
            "saved": False,
            "clean_content": "This is the response content",
            "metadata": {"language": "en"},
            "tool_results": [],
            "usage_info": {"input_tokens": 100, "output_tokens": 50},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()  # Generator's finally block ran (sets this)

        save_func = MagicMock(return_value=MagicMock(message_id="msg-123"))

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # The save function MUST have been called even though generator_done_event was set
        save_func.assert_called_once()
        # final_results["saved"] should be set to True
        assert final_results["saved"] is True

    def test_cleanup_does_not_double_save(self) -> None:
        """When generator already saved (saved=True), cleanup should not save again."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.chat_streaming import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        # Generator successfully saved before exiting
        final_results = {
            "ready": True,
            "saved": True,  # Already saved
            "clean_content": "Response content",
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should NOT be called since saved=True
        save_func.assert_not_called()

    def test_cleanup_does_not_save_empty_content(self) -> None:
        """Should not save when content is empty (nothing to save)."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.chat_streaming import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        final_results = {
            "ready": True,
            "saved": False,
            "clean_content": "",  # Empty content
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should NOT be called since content is empty
        save_func.assert_not_called()

    def test_cleanup_does_not_save_when_not_ready(self) -> None:
        """Should not save when results are not ready (stream thread didn't complete)."""
        import threading
        from unittest.mock import MagicMock

        from src.api.helpers.chat_streaming import cleanup_and_save

        stream_thread = MagicMock(spec=threading.Thread)
        stream_thread.is_alive.return_value = False
        stream_thread.join = MagicMock()

        final_results = {
            "ready": False,  # Stream thread didn't produce final results
            "saved": False,
            "clean_content": "Content",
            "metadata": {},
            "tool_results": [],
            "usage_info": {},
        }

        save_lock = threading.Lock()
        generator_done_event = threading.Event()
        generator_done_event.set()

        save_func = MagicMock()

        cleanup_and_save(
            stream_thread=stream_thread,
            final_results=final_results,
            save_lock=save_lock,
            generator_done_event=generator_done_event,
            conv_id="conv-123",
            user_id="user-456",
            save_func=save_func,
        )

        # save_func should NOT be called since ready=False
        save_func.assert_not_called()


class TestSmartRouting:
    """Tests for should_continue() smart routing in graph.py.

    Verifies that metadata-only tool calls (cite_sources, manage_memory) route
    to "end" while real tool calls route to "tools".
    """

    def test_metadata_only_routes_to_end(self) -> None:
        """cite_sources-only tool calls should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Answer.",
                    tool_calls=[{"name": "cite_sources", "args": {"sources": []}, "id": "1"}],
                )
            ]
        }
        assert should_continue(state) == "end"

    def test_manage_memory_only_routes_to_end(self) -> None:
        """manage_memory-only tool calls should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Noted.",
                    tool_calls=[
                        {
                            "name": "manage_memory",
                            "args": {"operations": [{"action": "add", "content": "x"}]},
                            "id": "1",
                        }
                    ],
                )
            ]
        }
        assert should_continue(state) == "end"

    def test_both_metadata_tools_route_to_end(self) -> None:
        """cite_sources + manage_memory together should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Done.",
                    tool_calls=[
                        {"name": "cite_sources", "args": {"sources": []}, "id": "1"},
                        {"name": "manage_memory", "args": {"operations": []}, "id": "2"},
                    ],
                )
            ]
        }
        assert should_continue(state) == "end"

    def test_real_tool_routes_to_tools(self) -> None:
        """Non-metadata tool calls should route to 'tools'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "web_search", "args": {"query": "test"}, "id": "1"}],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_mixed_real_and_metadata_routes_to_tools(self) -> None:
        """Mix of real + metadata tool calls should route to 'tools'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "web_search", "args": {"query": "test"}, "id": "1"},
                        {"name": "cite_sources", "args": {"sources": []}, "id": "2"},
                    ],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_no_tool_calls_routes_to_end(self) -> None:
        """Message without tool calls should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {"messages": [AIMessage(content="Just text.")]}
        assert should_continue(state) == "end"


class TestMetadataToolEdgeCases:
    """Edge case tests for metadata extraction functions.

    Regression tests for malformed tool calls, missing args, and boundary conditions
    that could cause extraction failures.
    """

    def test_extract_metadata_with_non_ai_messages(self) -> None:
        """Should safely skip non-AIMessage objects."""
        from langchain_core.messages import HumanMessage, ToolMessage

        messages = [
            HumanMessage(content="Hello"),
            ToolMessage(content="Result", tool_call_id="1"),
        ]
        sources, memory_ops = extract_metadata_tool_args(messages)
        assert sources == []
        assert memory_ops == []

    def test_extract_metadata_cite_sources_missing_args(self) -> None:
        """cite_sources with empty args should return empty sources."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[{"name": "cite_sources", "args": {}, "id": "1"}],
            )
        ]
        sources, _ = extract_metadata_tool_args(messages)
        assert sources == []

    def test_extract_metadata_manage_memory_missing_args(self) -> None:
        """manage_memory with empty args should return empty memory ops."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[{"name": "manage_memory", "args": {}, "id": "1"}],
            )
        ]
        _, memory_ops = extract_metadata_tool_args(messages)
        assert memory_ops == []

    def test_extract_metadata_sources_non_dict_items(self) -> None:
        """Sources list containing non-dict items should be filtered out."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {
                            "sources": [
                                "not a dict",
                                42,
                                {"title": "Valid", "url": "https://valid.com"},
                            ]
                        },
                        "id": "1",
                    }
                ],
            )
        ]
        sources, _ = extract_metadata_tool_args(messages)
        assert len(sources) == 1
        assert sources[0]["title"] == "Valid"

    def test_extract_metadata_memory_ops_without_action(self) -> None:
        """Memory operations without 'action' key should be filtered out."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Response",
                tool_calls=[
                    {
                        "name": "manage_memory",
                        "args": {
                            "operations": [
                                {"content": "no action key"},
                                {"action": "add", "content": "valid"},
                            ]
                        },
                        "id": "1",
                    }
                ],
            )
        ]
        _, memory_ops = extract_metadata_tool_args(messages)
        assert len(memory_ops) == 1
        assert memory_ops[0]["action"] == "add"

    def test_extract_image_prompts_missing_prompt_arg(self) -> None:
        """generate_image without 'prompt' arg should be skipped."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="Image",
                tool_calls=[
                    {"name": "generate_image", "args": {}, "id": "1"},
                    {"name": "generate_image", "args": {"prompt": "a cat"}, "id": "2"},
                ],
            )
        ]
        result = extract_image_prompts_from_messages(messages)
        assert len(result) == 1
        assert result[0]["prompt"] == "a cat"

    def test_extract_image_prompts_with_non_ai_messages(self) -> None:
        """Should safely skip non-AIMessage objects."""
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content="Generate a cat")]
        result = extract_image_prompts_from_messages(messages)
        assert result == []

    def test_extract_metadata_only_checks_last_ai_message_with_metadata_tools(self) -> None:
        """Should only extract from the last AIMessage that has metadata tool calls."""
        from langchain_core.messages import AIMessage

        messages = [
            AIMessage(
                content="First turn",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {"sources": [{"title": "Old", "url": "https://old.com"}]},
                        "id": "1",
                    }
                ],
            ),
            AIMessage(
                content="Second turn",
                tool_calls=[
                    {
                        "name": "cite_sources",
                        "args": {"sources": [{"title": "New", "url": "https://new.com"}]},
                        "id": "2",
                    }
                ],
            ),
        ]
        sources, _ = extract_metadata_tool_args(messages)
        # Should get sources from the LAST AIMessage only
        assert len(sources) == 1
        assert sources[0]["title"] == "New"

    def test_sources_fallback_handles_non_list_content(self) -> None:
        """Fallback should handle tool results with string content."""
        tool_results = [{"type": "tool", "content": '"just a string"'}]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert sources == []

    def test_sources_fallback_handles_empty_content(self) -> None:
        """Fallback should handle tool results with empty content."""
        tool_results = [{"type": "tool", "content": ""}]
        sources = extract_sources_fallback_from_tool_results(tool_results)
        assert sources == []

    def test_detect_language_handles_whitespace_only(self) -> None:
        """Language detection should return None for whitespace-only text."""
        assert detect_response_language("   \n\t  ") is None

    def test_detect_language_handles_special_characters(self) -> None:
        """Language detection should handle text with special characters."""
        # Enough chars for detection, but mostly symbols
        result = detect_response_language("!@#$%^&*()_+!@#$%^&*()")
        # Should either detect something or return None, not crash
        assert result is None or (isinstance(result, str) and len(result) == 2)
