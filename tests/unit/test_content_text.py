"""Unit tests for text/thinking extraction helpers in src/agent/content.py."""

from src.agent.content import (
    clean_tool_call_json,
    extract_text_content,
    extract_thinking_and_text,
    strip_full_result_from_tool_content,
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
