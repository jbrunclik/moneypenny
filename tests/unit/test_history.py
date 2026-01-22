"""Unit tests for conversation history enrichment.

Tests for src/agent/history.py functions including timestamp formatting,
session gap detection, file metadata extraction, and tool usage summaries.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from src.agent.history import (
    detect_session_gap,
    enrich_history,
    format_file_metadata,
    format_relative_time,
    format_session_gap,
    format_timestamp,
    format_tool_summary,
    infer_tools_used,
    simplify_mime_type,
)
from src.api.schemas import MessageRole
from src.db.models.dataclasses import Message


class TestFormatTimestamp:
    """Tests for format_timestamp function."""

    def test_formats_datetime_with_timezone(self) -> None:
        """Should format datetime with timezone abbreviation."""
        dt = datetime(2024, 6, 15, 14, 30, 0)
        result = format_timestamp(dt)

        # Should include date and time
        assert "2024-06-15" in result
        assert "14:30" in result
        # Should have some timezone identifier
        assert len(result.split()) == 3

    def test_utc_datetime_converted_to_local(self) -> None:
        """UTC datetime should be converted to local time."""
        dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        result = format_timestamp(dt)

        # Should still have proper format
        assert "2024-06-" in result

    def test_handles_naive_datetime(self) -> None:
        """Naive datetime should be treated as local time."""
        dt = datetime(2024, 1, 1, 9, 0, 0)
        result = format_timestamp(dt)

        assert "2024-01-01" in result
        assert "09:00" in result


class TestFormatRelativeTime:
    """Tests for format_relative_time function."""

    def test_just_now_for_recent(self) -> None:
        """Very recent times should show 'just now'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 14, 29, 45)
        assert format_relative_time(dt, now) == "just now"

    def test_one_minute_ago(self) -> None:
        """1-2 minutes ago should show '1 minute ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 14, 28, 30)
        assert format_relative_time(dt, now) == "1 minute ago"

    def test_multiple_minutes_ago(self) -> None:
        """Multiple minutes should show 'X minutes ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 14, 15, 0)
        assert format_relative_time(dt, now) == "15 minutes ago"

    def test_one_hour_ago(self) -> None:
        """1-2 hours ago should show '1 hour ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 13, 0, 0)
        assert format_relative_time(dt, now) == "1 hour ago"

    def test_multiple_hours_ago(self) -> None:
        """Multiple hours should show 'X hours ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 10, 0, 0)
        assert format_relative_time(dt, now) == "4 hours ago"

    def test_one_day_ago(self) -> None:
        """1-2 days ago should show '1 day ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 14, 14, 30, 0)
        assert format_relative_time(dt, now) == "1 day ago"

    def test_multiple_days_ago(self) -> None:
        """Multiple days should show 'X days ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 12, 14, 30, 0)
        assert format_relative_time(dt, now) == "3 days ago"

    def test_one_week_ago(self) -> None:
        """7-14 days ago should show '1 week ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 8, 14, 30, 0)
        assert format_relative_time(dt, now) == "1 week ago"

    def test_multiple_weeks_ago(self) -> None:
        """Multiple weeks should show 'X weeks ago'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 5, 25, 14, 30, 0)
        assert format_relative_time(dt, now) == "3 weeks ago"

    def test_future_time_returns_just_now(self) -> None:
        """Future times should return 'just now'."""
        now = datetime(2024, 6, 15, 14, 30, 0)
        dt = datetime(2024, 6, 15, 15, 30, 0)
        assert format_relative_time(dt, now) == "just now"

    def test_handles_timezone_aware_datetime(self) -> None:
        """Should handle timezone-aware datetimes."""
        now = datetime(2024, 6, 15, 14, 30, 0, tzinfo=UTC)
        dt = datetime(2024, 6, 15, 12, 30, 0, tzinfo=UTC)
        assert format_relative_time(dt, now) == "2 hours ago"


class TestDetectSessionGap:
    """Tests for detect_session_gap function."""

    def _make_message(self, created_at: datetime) -> Message:
        """Helper to create a Message with a given timestamp."""
        return Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Test",
            created_at=created_at,
        )

    def test_no_gap_for_close_messages(self) -> None:
        """Messages within threshold should not show gap."""
        prev = self._make_message(datetime(2024, 6, 15, 14, 0, 0))
        curr = self._make_message(datetime(2024, 6, 15, 15, 0, 0))

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = detect_session_gap(prev, curr)

        assert result is None

    def test_gap_detected_at_threshold(self) -> None:
        """Messages exactly at threshold should show gap."""
        prev = self._make_message(datetime(2024, 6, 15, 10, 0, 0))
        curr = self._make_message(datetime(2024, 6, 15, 14, 0, 0))

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = detect_session_gap(prev, curr)

        assert result is not None
        assert result == timedelta(hours=4)

    def test_gap_detected_above_threshold(self) -> None:
        """Messages above threshold should show gap."""
        prev = self._make_message(datetime(2024, 6, 14, 10, 0, 0))
        curr = self._make_message(datetime(2024, 6, 15, 14, 0, 0))

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = detect_session_gap(prev, curr)

        assert result is not None
        assert result.total_seconds() > 4 * 3600

    def test_gap_just_below_threshold(self) -> None:
        """Messages just below threshold should not show gap."""
        prev = self._make_message(datetime(2024, 6, 15, 10, 1, 0))
        curr = self._make_message(datetime(2024, 6, 15, 14, 0, 0))

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = detect_session_gap(prev, curr)

        assert result is None


class TestFormatSessionGap:
    """Tests for format_session_gap function."""

    def test_formats_one_hour(self) -> None:
        """1-2 hour gap should show '1 hour'."""
        assert format_session_gap(timedelta(hours=1)) == "1 hour"
        assert format_session_gap(timedelta(hours=1, minutes=30)) == "1 hour"

    def test_formats_multiple_hours(self) -> None:
        """Multiple hours should show 'X hours'."""
        assert format_session_gap(timedelta(hours=6)) == "6 hours"
        assert format_session_gap(timedelta(hours=23)) == "23 hours"

    def test_formats_one_day(self) -> None:
        """24-48 hours should show '1 day'."""
        assert format_session_gap(timedelta(hours=24)) == "1 day"
        assert format_session_gap(timedelta(hours=36)) == "1 day"

    def test_formats_multiple_days(self) -> None:
        """Multiple days should show 'X days'."""
        assert format_session_gap(timedelta(days=3)) == "3 days"
        assert format_session_gap(timedelta(days=7)) == "7 days"


class TestSimplifyMimeType:
    """Tests for simplify_mime_type function."""

    def test_image_types(self) -> None:
        """Image MIME types should return 'image'."""
        assert simplify_mime_type("image/png") == "image"
        assert simplify_mime_type("image/jpeg") == "image"
        assert simplify_mime_type("image/gif") == "image"
        assert simplify_mime_type("image/webp") == "image"

    def test_pdf_type(self) -> None:
        """PDF should return 'PDF'."""
        assert simplify_mime_type("application/pdf") == "PDF"

    def test_text_types(self) -> None:
        """Text MIME types should return appropriate descriptions."""
        assert simplify_mime_type("text/plain") == "text file"
        assert simplify_mime_type("text/markdown") == "Markdown"
        assert simplify_mime_type("text/csv") == "CSV"
        assert simplify_mime_type("text/html") == "text file"

    def test_json_type(self) -> None:
        """JSON should return 'JSON'."""
        assert simplify_mime_type("application/json") == "JSON"

    def test_unknown_type(self) -> None:
        """Unknown types should return 'file'."""
        assert simplify_mime_type("application/octet-stream") == "file"
        assert simplify_mime_type("application/zip") == "file"


class TestFormatFileMetadata:
    """Tests for format_file_metadata function."""

    def _make_message_with_files(self, files: list[dict], msg_id: str = "msg-123") -> Message:
        """Helper to create a Message with file attachments."""
        return Message(
            id=msg_id,
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Test",
            created_at=datetime.now(),
            files=files,
        )

    def test_returns_none_for_no_files(self) -> None:
        """Should return None when message has no files."""
        msg = self._make_message_with_files([])
        assert format_file_metadata(msg) is None

    def test_extracts_single_file(self) -> None:
        """Should extract metadata from a single file."""
        files = [{"name": "report.pdf", "type": "application/pdf", "data": "..."}]
        msg = self._make_message_with_files(files, "msg-abc")
        result = format_file_metadata(msg)

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "report.pdf"
        assert result[0]["type"] == "PDF"
        assert result[0]["message_id"] == "msg-abc"
        assert result[0]["file_index"] == 0

    def test_extracts_multiple_files(self) -> None:
        """Should extract metadata from multiple files."""
        files = [
            {"name": "photo.png", "type": "image/png", "data": "..."},
            {"name": "data.csv", "type": "text/csv", "data": "..."},
        ]
        msg = self._make_message_with_files(files, "msg-xyz")
        result = format_file_metadata(msg)

        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "photo.png"
        assert result[0]["type"] == "image"
        assert result[0]["file_index"] == 0
        assert result[1]["name"] == "data.csv"
        assert result[1]["type"] == "CSV"
        assert result[1]["file_index"] == 1

    def test_handles_missing_name(self) -> None:
        """Should use default name when file name is missing."""
        files = [{"type": "image/png", "data": "..."}]
        msg = self._make_message_with_files(files)
        result = format_file_metadata(msg)

        assert result is not None
        assert result[0]["name"] == "file_0"

    def test_handles_missing_type(self) -> None:
        """Should use default type when MIME type is missing."""
        files = [{"name": "unknown.bin", "data": "..."}]
        msg = self._make_message_with_files(files)
        result = format_file_metadata(msg)

        assert result is not None
        assert result[0]["type"] == "file"


class TestInferToolsUsed:
    """Tests for infer_tools_used function."""

    def test_empty_when_no_sources_or_images(self) -> None:
        """Should return empty list when no tools used."""
        assert infer_tools_used(None, None) == []
        assert infer_tools_used([], []) == []

    def test_web_search_from_sources(self) -> None:
        """Should infer web_search when sources present."""
        sources = [{"title": "Test", "url": "https://example.com"}]
        result = infer_tools_used(sources, None)
        assert "web_search" in result
        assert "generate_image" not in result

    def test_generate_image_from_generated_images(self) -> None:
        """Should infer generate_image when generated_images present."""
        images = [{"prompt": "A cat"}]
        result = infer_tools_used(None, images)
        assert "generate_image" in result
        assert "web_search" not in result

    def test_both_tools_from_both_metadata(self) -> None:
        """Should infer both tools when both metadata present."""
        sources = [{"title": "Test", "url": "https://example.com"}]
        images = [{"prompt": "A cat"}]
        result = infer_tools_used(sources, images)
        assert "web_search" in result
        assert "generate_image" in result


class TestFormatToolSummary:
    """Tests for format_tool_summary function."""

    def test_returns_none_for_no_tools(self) -> None:
        """Should return None when no tools used."""
        assert format_tool_summary(None, None) is None
        assert format_tool_summary([], []) is None

    def test_formats_single_source(self) -> None:
        """Should format single source correctly."""
        sources = [{"title": "Test", "url": "https://example.com"}]
        result = format_tool_summary(sources, None)
        assert result == "searched 1 web source"

    def test_formats_multiple_sources(self) -> None:
        """Should format multiple sources correctly."""
        sources = [
            {"title": "Test 1", "url": "https://example1.com"},
            {"title": "Test 2", "url": "https://example2.com"},
            {"title": "Test 3", "url": "https://example3.com"},
        ]
        result = format_tool_summary(sources, None)
        assert result == "searched 3 web sources"

    def test_formats_single_image(self) -> None:
        """Should format single image correctly."""
        images = [{"prompt": "A cat"}]
        result = format_tool_summary(None, images)
        assert result == "generated 1 image"

    def test_formats_multiple_images(self) -> None:
        """Should format multiple images correctly."""
        images = [{"prompt": "A cat"}, {"prompt": "A dog"}]
        result = format_tool_summary(None, images)
        assert result == "generated 2 images"

    def test_formats_both_sources_and_images(self) -> None:
        """Should format both sources and images correctly."""
        sources = [{"title": "Test", "url": "https://example.com"}]
        images = [{"prompt": "A cat"}]
        result = format_tool_summary(sources, images)
        assert result == "searched 1 web source, generated 1 image"


class TestEnrichHistory:
    """Tests for enrich_history function."""

    def _make_message(
        self,
        msg_id: str,
        role: MessageRole,
        content: str,
        created_at: datetime,
        files: list[dict] | None = None,
        sources: list[dict] | None = None,
        generated_images: list[dict] | None = None,
    ) -> Message:
        """Helper to create a Message."""
        return Message(
            id=msg_id,
            conversation_id="conv-1",
            role=role,
            content=content,
            created_at=created_at,
            files=files or [],
            sources=sources,
            generated_images=generated_images,
        )

    def test_empty_history(self) -> None:
        """Should return empty list for empty input."""
        assert enrich_history([]) == []

    def test_basic_message_enrichment(self) -> None:
        """Should add timestamps to messages."""
        msg = self._make_message(
            "msg-1",
            MessageRole.USER,
            "Hello",
            datetime(2024, 6, 15, 14, 30, 0),
        )
        result = enrich_history([msg])

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert "metadata" in result[0]
        assert "timestamp" in result[0]["metadata"]
        assert "relative_time" in result[0]["metadata"]

    def test_session_gap_detection(self) -> None:
        """Should detect session gaps between messages."""
        msg1 = self._make_message(
            "msg-1",
            MessageRole.USER,
            "Hello",
            datetime(2024, 6, 15, 10, 0, 0),
        )
        msg2 = self._make_message(
            "msg-2",
            MessageRole.ASSISTANT,
            "Hi there!",
            datetime(2024, 6, 15, 14, 30, 0),
        )

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = enrich_history([msg1, msg2])

        # First message should not have session_gap
        assert "session_gap" not in result[0]["metadata"]
        # Second message should have session_gap
        assert "session_gap" in result[1]["metadata"]
        assert result[1]["metadata"]["session_gap"] == "4 hours"

    def test_file_metadata_for_user_messages(self) -> None:
        """Should include file metadata for user messages with files."""
        msg = self._make_message(
            "msg-1",
            MessageRole.USER,
            "Check this file",
            datetime(2024, 6, 15, 14, 30, 0),
            files=[{"name": "doc.pdf", "type": "application/pdf", "data": "..."}],
        )
        result = enrich_history([msg])

        assert "files" in result[0]["metadata"]
        assert len(result[0]["metadata"]["files"]) == 1
        assert result[0]["metadata"]["files"][0]["name"] == "doc.pdf"
        assert result[0]["metadata"]["files"][0]["message_id"] == "msg-1"

    def test_no_file_metadata_for_assistant_messages(self) -> None:
        """Should not include files metadata for assistant messages."""
        msg = self._make_message(
            "msg-1",
            MessageRole.ASSISTANT,
            "Here is the result",
            datetime(2024, 6, 15, 14, 30, 0),
            files=[{"name": "output.png", "type": "image/png", "data": "..."}],
        )
        result = enrich_history([msg])

        # Assistant messages should not have files in metadata (they have them in content)
        assert "files" not in result[0]["metadata"]

    def test_tool_usage_for_assistant_messages(self) -> None:
        """Should include tool usage for assistant messages."""
        msg = self._make_message(
            "msg-1",
            MessageRole.ASSISTANT,
            "I found some info",
            datetime(2024, 6, 15, 14, 30, 0),
            sources=[{"title": "Wikipedia", "url": "https://wiki.org"}],
            generated_images=[{"prompt": "A sunset"}],
        )
        result = enrich_history([msg])

        assert "tools_used" in result[0]["metadata"]
        assert "web_search" in result[0]["metadata"]["tools_used"]
        assert "generate_image" in result[0]["metadata"]["tools_used"]
        assert "tool_summary" in result[0]["metadata"]
        assert "1 web source" in result[0]["metadata"]["tool_summary"]
        assert "1 image" in result[0]["metadata"]["tool_summary"]

    def test_no_tool_usage_for_user_messages(self) -> None:
        """Should not include tool usage for user messages."""
        msg = self._make_message(
            "msg-1",
            MessageRole.USER,
            "Search for cats",
            datetime(2024, 6, 15, 14, 30, 0),
        )
        result = enrich_history([msg])

        assert "tools_used" not in result[0]["metadata"]
        assert "tool_summary" not in result[0]["metadata"]

    def test_full_conversation_enrichment(self) -> None:
        """Should enrich a full conversation with all metadata types."""
        messages = [
            self._make_message(
                "msg-1",
                MessageRole.USER,
                "Analyze this",
                datetime(2024, 6, 15, 10, 0, 0),
                files=[{"name": "data.csv", "type": "text/csv", "data": "..."}],
            ),
            self._make_message(
                "msg-2",
                MessageRole.ASSISTANT,
                "I've analyzed the data",
                datetime(2024, 6, 15, 10, 1, 0),
            ),
            self._make_message(
                "msg-3",
                MessageRole.USER,
                "Now search for more info",
                datetime(2024, 6, 15, 16, 0, 0),  # 6 hour gap (from 10:01 to 16:00)
            ),
            self._make_message(
                "msg-4",
                MessageRole.ASSISTANT,
                "Here's what I found",
                datetime(2024, 6, 15, 16, 2, 0),
                sources=[{"title": "Article", "url": "https://example.com"}],
            ),
        ]

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = enrich_history(messages)

        assert len(result) == 4

        # First message: user with files, no session gap
        assert result[0]["role"] == "user"
        assert "files" in result[0]["metadata"]
        assert "session_gap" not in result[0]["metadata"]

        # Second message: assistant without tools
        assert result[1]["role"] == "assistant"
        assert "tools_used" not in result[1]["metadata"]

        # Third message: user with session gap (resumed after 6 hours)
        assert result[2]["role"] == "user"
        assert "session_gap" in result[2]["metadata"]
        assert result[2]["metadata"]["session_gap"] == "5 hours"  # 10:01 to 16:00 is ~5.98 hours

        # Fourth message: assistant with web_search
        assert result[3]["role"] == "assistant"
        assert "tools_used" in result[3]["metadata"]
        assert "web_search" in result[3]["metadata"]["tools_used"]


class TestFileIdIntegration:
    """Tests to verify file IDs work with tool parameters."""

    def test_file_metadata_format_matches_tool_params(self) -> None:
        """File metadata format should match retrieve_file tool parameters."""
        msg = Message(
            id="msg-abc123",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Check this",
            created_at=datetime.now(),
            files=[
                {"name": "doc.pdf", "type": "application/pdf", "data": "..."},
                {"name": "img.png", "type": "image/png", "data": "..."},
            ],
        )
        result = format_file_metadata(msg)

        assert result is not None

        # Verify first file can be used with retrieve_file tool
        assert result[0]["message_id"] == "msg-abc123"
        assert result[0]["file_index"] == 0

        # Verify second file can be used with generate_image history params
        assert result[1]["message_id"] == "msg-abc123"
        assert result[1]["file_index"] == 1


class TestPartialDataBackwardCompatibility:
    """Tests to ensure enrichment works with existing conversations that have partial data."""

    def test_handles_message_without_sources(self) -> None:
        """Should handle assistant messages without sources field."""
        msg = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Hello",
            created_at=datetime.now(),
            sources=None,
            generated_images=None,
        )
        result = enrich_history([msg])

        assert len(result) == 1
        # Should not have tool metadata
        assert "tools_used" not in result[0]["metadata"]
        assert "tool_summary" not in result[0]["metadata"]

    def test_handles_message_with_empty_files_list(self) -> None:
        """Should handle messages with empty files list."""
        msg = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
            created_at=datetime.now(),
            files=[],
        )
        result = enrich_history([msg])

        assert len(result) == 1
        # Should not have files metadata
        assert "files" not in result[0]["metadata"]

    def test_handles_mixed_old_and_new_messages(self) -> None:
        """Should handle conversations with both old (partial) and new (full) messages."""
        old_msg = Message(
            id="msg-old",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Old response",
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            sources=None,  # Old message without sources
        )
        new_msg = Message(
            id="msg-new",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="New response",
            created_at=datetime(2024, 6, 15, 14, 0, 0),
            sources=[{"title": "Source", "url": "https://example.com"}],
        )

        with patch("src.agent.history.Config") as mock_config:
            mock_config.HISTORY_SESSION_GAP_HOURS = 4
            result = enrich_history([old_msg, new_msg])

        assert len(result) == 2

        # Old message should work without tool metadata
        assert "tools_used" not in result[0]["metadata"]

        # New message should have tool metadata
        assert "tools_used" in result[1]["metadata"]
        assert "web_search" in result[1]["metadata"]["tools_used"]
