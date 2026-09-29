"""Unit tests for ChatAgent._build_messages and src/agent/message_content.py."""


class TestFormatMessageWithMetadata:
    """Tests for format_message_with_metadata (src/agent/message_content.py)."""

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
        """Should include absolute timestamp in JSON (no volatile relative time)."""
        msg = {
            "role": "user",
            "content": "Hello",
            "metadata": {
                "timestamp": "2024-06-15 14:30 CET",
            },
        }
        result = self._format_message(msg)

        assert result.startswith("<!-- MSG_CONTEXT:")
        assert '"timestamp":"2024-06-15 14:30 CET"' in result
        # Relative time is intentionally omitted to keep the history prefix stable
        assert "relative_time" not in result
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
            "metadata": {"timestamp": "2024-06-15 14:30 CET", "session_gap": "2 days"},
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
        assert '"session_gap":"' in json_str

    def test_context_format_distinct_from_response_metadata(self) -> None:
        """Should use <!-- MSG_CONTEXT: --> format (different from response METADATA)."""
        msg = {
            "role": "user",
            "content": "Hello",
            "metadata": {"timestamp": "2024-06-15 14:30 CET"},
        }
        result = self._format_message(msg)

        # Should use MSG_CONTEXT marker (distinct from response METADATA)
        assert result.startswith("<!-- MSG_CONTEXT: {")
        assert "} -->" in result
        # Should NOT use METADATA marker (reserved for response metadata)
        assert "<!-- METADATA:" not in result


class TestBuildMessageContentVideo:
    """Video attachments become Files API media blocks in message content."""

    def test_video_with_uri_becomes_media_block(self) -> None:
        from src.agent.message_content import build_message_content

        files = [
            {
                "name": "clip.mp4",
                "type": "video/mp4",
                "data": "aaaa",
                "gemini_file_uri": "https://files.example/f1",
            }
        ]
        blocks = build_message_content("what is this?", files)
        assert isinstance(blocks, list)
        media = [b for b in blocks if isinstance(b, dict) and b.get("type") == "media"]
        assert media == [
            {
                "type": "media",
                "file_uri": "https://files.example/f1",
                "mime_type": "video/mp4",
            }
        ]

    def test_video_without_uri_becomes_text_notice(self) -> None:
        from src.agent.message_content import build_message_content

        files = [
            {
                "name": "clip.mp4",
                "type": "video/mp4",
                "data": "aaaa",
                "gemini_upload_error": "boom",
            }
        ]
        blocks = build_message_content("what is this?", files)
        assert isinstance(blocks, list)
        texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        assert any("could not be attached" in t for t in texts)


class TestBuildMessagesConversationTitle:
    """conversation_title must reach the prompt in both cached and uncached modes."""

    @staticmethod
    def _agent(cached: bool):
        from src.agent.agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent._cached_content_name = "cache/x" if cached else None
        agent.system_prompt_override = None
        agent.with_tools = True
        agent.anonymous_mode = False
        agent.is_autonomous = False
        agent.agent_context = None
        return agent

    def test_uncached_system_prompt_contains_title(self) -> None:
        messages = self._agent(cached=False)._build_messages(
            "hi", conversation_title="🐍 Python List Sorting"
        )
        system_content = str(messages[0].content)
        assert "🐍 Python List Sorting" in system_content

    def test_cached_dynamic_context_contains_title(self) -> None:
        messages = self._agent(cached=True)._build_messages(
            "hi", conversation_title="🐍 Python List Sorting"
        )
        combined = "".join(str(m.content) for m in messages)
        assert "🐍 Python List Sorting" in combined


class TestMsgContextToolDigest:
    """tool_digest must reach the model via the REAL formatter (the mirror
    helper above would pass even if production dropped the field)."""

    def _format(self, msg: dict) -> str:
        from src.agent.message_content import format_message_with_metadata

        return format_message_with_metadata(msg)

    def test_tool_digest_included_in_msg_context(self) -> None:
        msg = {
            "role": "assistant",
            "content": "Found it.",
            "metadata": {
                "timestamp": "2024-06-15 14:30 CET",
                "tool_digest": "read: Alpine Guide (https://example.com/a)",
            },
        }
        result = self._format(msg)

        assert result.startswith("<!-- MSG_CONTEXT:")
        assert '"tool_digest":"read: Alpine Guide (https://example.com/a)"' in result

    def test_tool_outputs_included_in_msg_context(self) -> None:
        msg = {
            "role": "assistant",
            "content": "HRV 62.",
            "metadata": {
                "timestamp": "2024-06-15 14:30 CET",
                "tool_outputs": 'garmin_connect({}) -> {"hrv":62}',
            },
        }
        assert '"tool_outputs":"garmin_connect({}) -> {\\"hrv\\":62}"' in self._format(msg)

    def test_no_digest_key_when_absent(self) -> None:
        msg = {
            "role": "assistant",
            "content": "Plain.",
            "metadata": {"timestamp": "2024-06-15 14:30 CET"},
        }
        assert "tool_digest" not in self._format(msg)
