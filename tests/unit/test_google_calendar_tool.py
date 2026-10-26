"""Unit tests for the Google Calendar tool (src/agent/tools/google_calendar.py)."""

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.google_calendar import google_calendar


def _response(status: int, body: object = None) -> MagicMock:
    response = MagicMock(status_code=status, text="boom")
    response.json.return_value = body
    return response


class TestCalendarRequests:
    """The REST layer under the tool: methods, empty replies, errors, the 401 retry."""

    @pytest.fixture(autouse=True)
    def connected(self) -> Iterator[MagicMock]:
        with (
            patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "id"),
            patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "s"),
            patch("src.agent.tools.google_calendar._get_google_calendar_access_token") as token,
        ):
            token.return_value = ("tok", "user@example.com")
            yield token

    @patch("src.agent.tools.google_calendar.httpx.get")
    def test_reads_send_the_bearer_token(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _response(200, {"items": [{"id": "c1", "primary": True}]})

        result = json.loads(google_calendar.invoke({"action": "list_calendars"}))

        assert result["count"] == 1
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok"}

    @patch("src.agent.tools.google_calendar.httpx.patch")
    @patch("src.agent.tools.google_calendar.httpx.post")
    def test_writes_send_json(self, mock_post: MagicMock, mock_patch: MagicMock) -> None:
        mock_post.return_value = _response(200, {"id": "e1", "summary": "Run"})
        mock_patch.return_value = _response(200, {"id": "e1", "summary": "Walk"})
        times = {"start_time": "2026-06-10T08:00:00", "end_time": "2026-06-10T09:00:00"}

        google_calendar.invoke({"action": "create_event", "summary": "Run", **times})
        google_calendar.invoke({"action": "update_event", "event_id": "e1", "summary": "Walk"})

        for call in (mock_post.call_args, mock_patch.call_args):
            assert call.kwargs["headers"]["Content-Type"] == "application/json"
        assert mock_post.call_args.kwargs["json"]["summary"] == "Run"
        assert mock_patch.call_args.kwargs["json"] == {"summary": "Walk"}

    @patch("src.agent.tools.google_calendar.httpx.delete")
    def test_delete_accepts_no_content(self, mock_delete: MagicMock) -> None:
        mock_delete.return_value = _response(204)

        result = json.loads(google_calendar.invoke({"action": "delete_event", "event_id": "e1"}))

        assert "error" not in result
        mock_delete.assert_called_once()

    @patch("src.agent.tools.google_calendar.httpx.get")
    def test_401_retries_once_with_a_refreshed_token(
        self, mock_get: MagicMock, connected: MagicMock
    ) -> None:
        mock_get.side_effect = [_response(401), _response(200, {"items": []})]
        connected.side_effect = [("stale", "user@example.com"), ("fresh", "user@example.com")]

        result = json.loads(google_calendar.invoke({"action": "list_calendars"}))

        assert result["count"] == 0
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer fresh"}

    @patch("src.agent.tools.google_calendar.httpx.get")
    def test_401_after_the_refresh_reports_disconnected(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _response(401)

        result = json.loads(google_calendar.invoke({"action": "list_calendars"}))

        assert mock_get.call_count == 2
        assert result["retriable"] is False
        assert "disconnected" in result["error"].lower()

    @patch("src.agent.tools.google_calendar.httpx.get")
    def test_error_status_is_reported_with_the_body(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _response(500)

        result = json.loads(google_calendar.invoke({"action": "list_calendars"}))

        assert result["error"] == "Google Calendar API error (500): boom"


# ============================================================================
# Tests for Google Calendar Tool
# ============================================================================


class TestGoogleCalendarTool:
    """Tests for google_calendar tool."""

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "")
    def test_returns_error_when_not_configured(self) -> None:
        """Should return error when Google Calendar is not configured."""
        from src.agent.tools import google_calendar

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not configured" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_returns_error_when_not_connected(self, mock_get_token: MagicMock) -> None:
        """Should return error when Google Calendar is not connected."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = None

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not connected" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_returns_error_for_unknown_action(self, mock_get_token: MagicMock) -> None:
        """Should return error for unknown action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke({"action": "unknown_action"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar.get_conversation_context")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    @patch("src.db.models.db.get_user_by_id")
    def test_list_calendars_success(
        self,
        mock_get_user: MagicMock,
        mock_api: MagicMock,
        mock_get_token: MagicMock,
        mock_context: MagicMock,
    ) -> None:
        """Should successfully list calendars filtered by user selection."""
        from src.agent.tools import google_calendar
        from src.db.models import User

        # Mock conversation context to return a user ID
        mock_context.return_value = ("conv-id", "user-id")

        # Mock user with both calendars selected
        mock_user = MagicMock(spec=User)
        mock_user.google_calendar_selected_ids = ["primary", "work"]
        mock_get_user.return_value = mock_user

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "items": [
                {"id": "primary", "summary": "Main Calendar"},
                {"id": "work", "summary": "Work Calendar"},
            ]
        }

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "calendars" in parsed
        assert len(parsed["calendars"]) == 2

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_list_events_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully list events."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Team Meeting",
                    "start": {"dateTime": "2024-01-15T10:00:00Z"},
                    "end": {"dateTime": "2024-01-15T11:00:00Z"},
                }
            ]
        }

        result = google_calendar.invoke(
            {
                "action": "list_events",
                "calendar_id": "primary",
            }
        )
        parsed = json.loads(result)

        assert "events" in parsed
        assert len(parsed["events"]) == 1
        assert parsed["events"][0]["summary"] == "Team Meeting"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_create_event_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully create an event."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "id": "new-evt-1",
            "summary": "New Meeting",
            "start": {"dateTime": "2024-01-16T14:00:00Z"},
            "end": {"dateTime": "2024-01-16T15:00:00Z"},
        }

        result = google_calendar.invoke(
            {
                "action": "create_event",
                "summary": "New Meeting",
                "start_time": "2024-01-16T14:00:00Z",
                "end_time": "2024-01-16T15:00:00Z",
            }
        )
        parsed = json.loads(result)

        assert "event" in parsed
        assert parsed["event"]["summary"] == "New Meeting"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_delete_event_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully delete an event."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {}  # Delete returns empty

        result = google_calendar.invoke(
            {
                "action": "delete_event",
                "event_id": "evt-123",
            }
        )
        parsed = json.loads(result)

        assert "action" in parsed
        assert parsed["action"] == "delete_event"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_get_event_requires_event_id(self, mock_get_token: MagicMock) -> None:
        """Should require event_id for get_event action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke(
            {
                "action": "get_event",
                # Missing event_id
            }
        )
        parsed = json.loads(result)

        assert "error" in parsed
        assert "event_id" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_respond_event_requires_response_status(self, mock_get_token: MagicMock) -> None:
        """Should require response_status for respond_event action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke(
            {
                "action": "respond_event",
                "event_id": "evt-123",
                # Missing response_status
            }
        )
        parsed = json.loads(result)

        assert "error" in parsed
        assert "response_status" in parsed["error"].lower()
