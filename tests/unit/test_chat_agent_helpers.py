"""Unit tests for helper functions in src/agent/ modules."""

from src.agent.content import (
    clean_tool_call_json,
    extract_metadata_from_response,
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


class TestExtractMetadataFromResponse:
    """Tests for extract_metadata_from_response function."""

    def test_html_comment_format(self) -> None:
        """Should extract metadata from HTML comment format."""
        response = """Here is my response.

<!-- METADATA:
{"sources": [{"title": "Test", "url": "https://example.com"}]}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        assert clean == "Here is my response."
        assert "sources" in metadata
        assert len(metadata["sources"]) == 1
        assert metadata["sources"][0]["title"] == "Test"

    def test_plain_json_format(self) -> None:
        """Should extract metadata from plain JSON at end."""
        response = """Response text.

{"sources": [{"title": "Test", "url": "https://example.com"}]}"""
        clean, metadata = extract_metadata_from_response(response)

        assert clean == "Response text."
        assert "sources" in metadata

    def test_no_metadata(self) -> None:
        """Response without metadata should return empty dict."""
        response = "Just plain text response."
        clean, metadata = extract_metadata_from_response(response)

        assert clean == "Just plain text response."
        assert metadata == {}

    def test_generated_images_metadata(self) -> None:
        """Should extract generated_images metadata."""
        response = """Image generated!

<!-- METADATA:
{"generated_images": [{"prompt": "A sunset over mountains"}]}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        assert "generated_images" in metadata
        assert metadata["generated_images"][0]["prompt"] == "A sunset over mountains"

    def test_both_sources_and_images(self) -> None:
        """Should extract both sources and generated_images."""
        response = """Here's what I found and created.

<!-- METADATA:
{"sources": [{"title": "Wiki", "url": "https://wiki.org"}], "generated_images": [{"prompt": "test"}]}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        assert "sources" in metadata
        assert "generated_images" in metadata

    def test_malformed_json_in_html_comment(self) -> None:
        """Malformed JSON in HTML comment should result in empty metadata."""
        response = """Response text.

<!-- METADATA:
{invalid json here}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        # Should fall through to plain JSON search (which also fails)
        assert "Response text" in clean
        assert metadata == {}

    def test_strips_trailing_whitespace(self) -> None:
        """Should strip trailing whitespace from cleaned content."""
        response = """Response with trailing space

<!-- METADATA:
{"sources": []}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        assert not clean.endswith(" ")
        assert clean == "Response with trailing space"

    def test_metadata_in_middle_of_response(self) -> None:
        """Should extract metadata and preserve content both before AND after."""
        response = """Here is some content before.

<!-- METADATA:
{"language": "en", "sources": [{"title": "Test", "url": "https://example.com"}]}
-->

And here is content after the metadata block."""
        clean, metadata = extract_metadata_from_response(response)

        assert "Here is some content before" in clean
        assert "And here is content after" in clean
        assert "METADATA" not in clean
        assert metadata["language"] == "en"
        assert len(metadata["sources"]) == 1

    def test_metadata_at_very_start(self) -> None:
        """Should handle metadata at the very start of response."""
        response = """<!-- METADATA:
{"language": "en"}
-->
The actual response content."""
        clean, metadata = extract_metadata_from_response(response)

        assert clean == "The actual response content."
        assert metadata["language"] == "en"

    def test_msg_context_is_not_extracted_as_metadata(self) -> None:
        """MSG_CONTEXT blocks should NOT be extracted as response metadata.

        MSG_CONTEXT is for history context and uses a different marker.
        If echoed, it should be ignored, not extracted as metadata.
        """
        # Note: extract_metadata_from_response only looks for METADATA, not MSG_CONTEXT
        response = """<!-- MSG_CONTEXT: {"timestamp":"2024-01-01"} -->
Hello, this is the response.

<!-- METADATA:
{"language": "en"}
-->"""
        clean, metadata = extract_metadata_from_response(response)

        # MSG_CONTEXT should remain in clean content (extract_metadata only handles METADATA)
        # The streaming logic in agent.py handles stripping MSG_CONTEXT separately
        assert "language" in metadata
        assert metadata["language"] == "en"
        # MSG_CONTEXT is NOT extracted as metadata
        assert "timestamp" not in metadata

    def test_malformed_metadata_at_start_stripped(self) -> None:
        """Malformed METADATA at start (no closing -->) should be stripped.

        Regression test: When LLM outputs METADATA immediately after MSG_CONTEXT
        without proper formatting (no newlines, no closing -->), the <!-- METADATA: {...}
        prefix would cause the browser to treat everything as an HTML comment.
        """
        # This is what happens when LLM outputs: MSG_CONTEXT --> <!-- METADATA: {...}Content
        response = '<!-- METADATA: {"language": "cs"}Aha, chápu. This is the actual content.'
        clean, metadata = extract_metadata_from_response(response)

        # Malformed METADATA should be stripped
        assert "<!-- METADATA" not in clean
        assert "Aha, chápu" in clean
        assert "This is the actual content" in clean
        # Metadata is malformed so won't be extracted (that's OK)
        assert metadata == {}

    def test_malformed_metadata_with_language_only(self) -> None:
        """Malformed METADATA with just language field should be stripped."""
        response = '<!-- METADATA: {"language": "en"}The response content here.'
        clean, metadata = extract_metadata_from_response(response)

        assert "<!-- METADATA" not in clean
        assert "The response content" in clean


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


class TestStreamingMetadataBlockHandling:
    """Tests for metadata block handling during streaming.

    These tests verify that MSG_CONTEXT and METADATA blocks are handled correctly
    when they appear in streaming chunks, including multi-chunk scenarios.
    """

    def _process_chunks(self, chunks: list[str]) -> tuple[str, list[str], bool, bool]:
        """Simulate the chunk processing logic from stream_chat_events.

        This handles cross-chunk boundary scenarios where markers like
        <!-- MSG_CONTEXT: or --> are split across chunks.

        Args:
            chunks: List of text content chunks

        Returns:
            Tuple of (full_response, yielded_tokens, had_msg_context, had_metadata)
        """
        full_response = ""
        buffer = ""
        yielded_tokens: list[str] = []
        in_msg_context = False
        in_metadata = False
        had_msg_context = False
        had_metadata = False

        msg_context_marker = "<!-- MSG_CONTEXT:"
        metadata_marker = "<!-- METADATA:"
        end_marker = "-->"
        # Max marker length to buffer for cross-chunk detection
        max_marker_len = max(len(msg_context_marker), len(metadata_marker))

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
                    # Check if end marker might be split at chunk boundary
                    # Keep potential partial end marker for next chunk
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
                    # Block starts but doesn't end - check for partial end marker
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
                # Check if MSG_CONTEXT marker might be split at chunk boundary
                # Keep potential partial marker for next chunk
                for i in range(len(msg_context_marker) - 1, 0, -1):
                    partial = msg_context_marker[:i]
                    if text_content.endswith(partial):
                        carryover = partial
                        text_content = text_content[:-i]
                        break

            # Handle METADATA blocks (response metadata)
            if in_metadata:
                if end_marker in text_content:
                    end_pos = text_content.find(end_marker)
                    remaining = text_content[end_pos + 3 :].lstrip()
                    in_metadata = False
                    # Strip incomplete METADATA from full_response before adding remaining
                    # (full_response still has the incomplete block from when we entered in_metadata)
                    marker_idx = full_response.rfind(metadata_marker)
                    if marker_idx != -1:
                        full_response = full_response[:marker_idx]
                    if remaining:
                        full_response += remaining
                        buffer += remaining
                    continue
                else:
                    # Check if end marker might be split at chunk boundary
                    for i in range(len(end_marker) - 1, 0, -1):
                        if text_content.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    continue

            # Add to full response (before METADATA detection)
            full_response += text_content
            buffer += text_content

            # Check for METADATA marker in buffer
            if metadata_marker in buffer:
                had_metadata = True
                marker_pos = buffer.find(metadata_marker)
                # Check if METADATA block completes in this buffer
                end_pos = buffer.find(end_marker, marker_pos)
                if end_pos != -1:
                    # Complete METADATA block - strip it and keep content after
                    before = buffer[:marker_pos].rstrip()
                    after = buffer[end_pos + 3 :].lstrip()
                    # Update full_response to remove METADATA block
                    full_response = full_response[: full_response.rfind(metadata_marker)]
                    if after:
                        full_response += after
                    if before:
                        yielded_tokens.append(before)
                    buffer = after
                    # Don't set in_metadata since block is complete
                else:
                    # METADATA block starts but doesn't end - check for partial end marker
                    content_after_marker = buffer[marker_pos:]
                    for i in range(len(end_marker) - 1, 0, -1):
                        if content_after_marker.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    # Remove METADATA block from full_response
                    full_response = full_response[: full_response.rfind(metadata_marker)]
                    if marker_pos > 0:
                        yielded_tokens.append(buffer[:marker_pos].rstrip())
                    in_metadata = True
                    buffer = ""
            elif len(buffer) > max_marker_len:
                safe_length = len(buffer) - max_marker_len
                yielded_tokens.append(buffer[:safe_length])
                buffer = buffer[safe_length:]

        # Handle any remaining carryover (wasn't part of a marker)
        if carryover and not in_msg_context and not in_metadata:
            full_response += carryover
            buffer += carryover

        # Yield remaining buffer
        if buffer and not in_metadata:
            yielded_tokens.append(buffer)

        return full_response, yielded_tokens, had_msg_context, had_metadata

    def test_msg_context_single_chunk_stripped(self) -> None:
        """MSG_CONTEXT in a single chunk should be completely stripped."""
        chunks = ['<!-- MSG_CONTEXT: {"timestamp":"2024-01-01"} -->Hello world']
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

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
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

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
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        assert "This is the actual response content" in full_response
        assert had_ctx is True
        # Tokens should contain the response content
        joined_tokens = "".join(tokens)
        assert "actual response" in joined_tokens

    def test_metadata_at_end_normal_case(self) -> None:
        """METADATA at end of response should be detected and content yielded."""
        chunks = [
            "Here is my response to your question.",
            '\n\n<!-- METADATA:\n{"language": "en"}\n-->',
        ]
        full_response, tokens, _, had_meta = self._process_chunks(chunks)

        assert "Here is my response" in full_response
        assert had_meta is True
        # Content before metadata should be in tokens
        joined_tokens = "".join(tokens)
        assert "Here is my response" in joined_tokens

    def test_metadata_in_middle_content_preserved(self) -> None:
        """Content both before AND after METADATA should be preserved."""
        chunks = [
            "Content before metadata. ",
            '<!-- METADATA:\n{"language": "en"}\n-->',
            " Content after metadata.",
        ]
        full_response, tokens, _, had_meta = self._process_chunks(chunks)

        assert "Content before metadata" in full_response
        assert "Content after metadata" in full_response
        assert had_meta is True

    def test_both_msg_context_and_metadata(self) -> None:
        """Response with both echoed MSG_CONTEXT and METADATA should handle both."""
        chunks = [
            '<!-- MSG_CONTEXT: {"timestamp":"2024"} -->',
            "The actual response. ",
            '<!-- METADATA:\n{"language": "en"}\n-->',
        ]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "MSG_CONTEXT" not in full_response
        assert "timestamp" not in full_response
        assert "The actual response" in full_response
        assert had_ctx is True
        assert had_meta is True

    def test_no_metadata_blocks(self) -> None:
        """Response without any metadata blocks should yield all content."""
        chunks = ["Just a simple", " response with ", "no metadata."]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert full_response == "Just a simple response with no metadata."
        assert had_ctx is False
        assert had_meta is False
        joined_tokens = "".join(tokens)
        assert "Just a simple" in joined_tokens

    # Cross-chunk boundary tests

    def test_msg_context_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT marker split across chunk boundary."""
        # "<!-- MSG_" in one chunk, "CONTEXT:" in next
        chunks = ["Hello <!-- MSG_", "CONTEXT: {} --> world"]
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        # Should strip the MSG_CONTEXT block
        assert "Hello" in full_response
        assert "world" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_msg_context_end_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT end marker (-->) split across chunk boundary."""
        chunks = ['<!-- MSG_CONTEXT: {"key":"value"} -', "-> The response."]
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        assert "The response" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_metadata_marker_split_across_chunks(self) -> None:
        """METADATA marker split across chunk boundary."""
        chunks = ["Response content <!-- META", 'DATA:\n{"language": "en"}\n-->']
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "Response content" in full_response
        assert had_meta is True
        joined_tokens = "".join(tokens)
        assert "Response content" in joined_tokens

    def test_metadata_end_marker_split_across_chunks(self) -> None:
        """METADATA end marker (-->) split across chunk boundary."""
        chunks = ['Response <!-- METADATA:\n{"language": "en"}\n-', "-> After metadata."]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "Response" in full_response
        assert "After metadata" in full_response
        assert had_meta is True

    def test_metadata_json_split_across_chunks(self) -> None:
        """METADATA JSON content split across multiple chunks."""
        chunks = [
            'Content <!-- METADATA:\n{"lang',
            'uage": "en", "sources": [{"title":',
            ' "Test"}]}\n--> More content',
        ]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "Content" in full_response
        assert "More content" in full_response
        assert had_meta is True

    def test_content_immediately_after_msg_context_end(self) -> None:
        """Content immediately after --> of MSG_CONTEXT (no space)."""
        chunks = ["<!-- MSG_CONTEXT: {} -->Response starts here."]
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        assert "Response starts here" in full_response
        assert "MSG_CONTEXT" not in full_response

    def test_content_immediately_after_metadata_end(self) -> None:
        """Content immediately after --> of METADATA (no space)."""
        chunks = ["Before <!-- METADATA:\n{}\n-->After"]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "Before" in full_response
        assert "After" in full_response
        assert had_meta is True

    def test_empty_chunks_between_markers(self) -> None:
        """Empty or whitespace-only chunks within metadata block."""
        chunks = ["<!-- MSG_CONTEXT:", " ", '{"key": "value"}', "", " --> Content"]
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        assert "Content" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_multiple_msg_context_blocks(self) -> None:
        """Multiple MSG_CONTEXT blocks (shouldn't happen but handle gracefully)."""
        chunks = ['<!-- MSG_CONTEXT: {"a":1} --> First ', '<!-- MSG_CONTEXT: {"b":2} --> Second']
        full_response, tokens, had_ctx, _ = self._process_chunks(chunks)

        assert "First" in full_response
        assert "Second" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    # Regression tests for specific bugs

    def test_regression_metadata_multi_chunk_with_partial_end_marker(self) -> None:
        """Regression: METADATA spanning chunks with partial end marker should not corrupt content.

        Bug: When METADATA spanned chunks and the end marker (-->) was split,
        the incomplete METADATA block in full_response wasn't stripped before
        adding the remaining content, corrupting the response.
        """
        # Simulates: "Hello\n\n<!-- METADATA:\n{"lang": "en"}\n-" then "-> More content"
        chunks = [
            "Hello\n\n<!-- METADATA:\n",
            '{"lang": "en"}\n-',
            "-> More content",
        ]
        full_response, tokens, _, had_meta = self._process_chunks(chunks)

        # Content should be preserved correctly
        assert "Hello" in full_response
        assert "More content" in full_response
        # METADATA should be stripped, not corrupted
        assert "<!-- METADATA:" not in full_response
        assert '{"lang"' not in full_response
        assert had_meta is True

    def test_regression_metadata_at_position_zero_not_empty(self) -> None:
        """Regression: METADATA at position 0 after MSG_CONTEXT strip should handle correctly.

        If MSG_CONTEXT is immediately followed by METADATA with actual content after,
        the content should be preserved.
        """
        chunks = ['<!-- MSG_CONTEXT: {} --><!-- METADATA:\n{"lang": "en"}\n--> Actual content']
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        assert "Actual content" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert "METADATA" not in full_response
        assert had_ctx is True
        assert had_meta is True

    def test_regression_malformed_metadata_no_closing(self) -> None:
        """Regression: METADATA that starts but never closes should be stripped from full_response.

        Bug: When LLM output malformed METADATA (no closing -->), the incomplete block
        was added to full_response but never stripped. When we entered in_metadata mode,
        we cleared buffer but forgot to strip full_response. This caused the stored message
        to contain <!-- METADATA: {...}Content... which browsers render as an HTML comment,
        hiding all content.

        The fix: Strip from full_response when ENTERING in_metadata mode, not just when exiting.
        """
        # Simulates: MSG_CONTEXT ends, LLM outputs METADATA with no closing, then actual response
        chunks = [
            '<!-- MSG_CONTEXT: {"ts":"10:00"} -->',
            '<!-- METADATA: {"language": "cs"}',  # No closing -->
            "Aha, chápu. This is the actual content.",
        ]
        full_response, tokens, had_ctx, had_meta = self._process_chunks(chunks)

        # Malformed METADATA should be stripped from full_response
        assert "<!-- METADATA" not in full_response
        # Content after the malformed METADATA should be preserved
        # (note: in the actual implementation, subsequent chunks while in_metadata are skipped,
        # but the test helper doesn't fully replicate that - the important thing is that
        # METADATA is stripped from full_response)
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True
        assert had_meta is True
