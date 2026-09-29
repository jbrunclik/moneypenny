"""The agent must warn when an integration got disconnected - not act as if
it cannot use the tool (Sep 2026: "Garmin not connected" 14x in 30 days,
mostly expired sessions of users who believed they were connected)."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import integration_status
from src.agent.tools.integration_status import not_connected_result


@pytest.fixture
def user(monkeypatch: pytest.MonkeyPatch):
    def make(**fields):
        u = SimpleNamespace(
            garmin_token=None,
            garmin_connected_at=None,
            todoist_access_token=None,
            todoist_connected_at=None,
            google_calendar_access_token=None,
            google_calendar_connected_at=None,
            rouvy_session=None,
            rouvy_connected_at=None,
        )
        for k, v in fields.items():
            setattr(u, k, v)
        db = MagicMock()
        db.get_user_by_id.return_value = u
        monkeypatch.setattr(integration_status, "db", db)
        monkeypatch.setattr(integration_status, "get_conversation_context", lambda: ("c1", "u1"))
        return u

    return make


class TestNotConnectedResult:
    def test_expired_connection_is_reported_as_disconnected(self, user) -> None:
        user(garmin_token="stale", garmin_connected_at=datetime(2026, 8, 1))

        result = not_connected_result("garmin")

        assert result["error"] == "Garmin disconnected"
        assert result["retriable"] is False
        msg = result["message"]
        assert "disconnected" in msg and "reconnect" in msg and "Settings" in msg
        # The model must not pretend the capability is missing
        assert "Do not claim" in msg

    def test_never_connected_offers_to_connect(self, user) -> None:
        user()

        result = not_connected_result("todoist")

        assert result["error"] == "Todoist not connected"
        assert "connect" in result["message"] and "Settings" in result["message"]
        assert "disconnected" not in result["message"]

    def test_explicit_state_overrides_lookup(self, user) -> None:
        user()
        result = not_connected_result("google_calendar", was_connected=True)
        assert result["error"] == "Google Calendar disconnected"

    def test_no_user_context_is_treated_as_not_connected(self, monkeypatch) -> None:
        monkeypatch.setattr(integration_status, "get_conversation_context", lambda: (None, None))
        assert not_connected_result("rouvy")["error"] == "Rouvy not connected"


class TestToolsUseIt:
    def test_garmin_tool_reports_disconnect(self, user) -> None:
        from src.agent.tools.garmin import garmin_connect

        user(garmin_token="stale", garmin_connected_at=datetime(2026, 8, 1))
        with patch("src.agent.tools.garmin._get_garmin_client", return_value=None):
            parsed = json.loads(garmin_connect.invoke({"action": "get_readiness_snapshot"}))

        assert parsed["error"] == "Garmin disconnected"

    def test_todoist_revoked_token_reports_disconnect(self, user) -> None:
        from src.agent.tools.todoist import todoist

        user(todoist_access_token="revoked", todoist_connected_at=datetime(2026, 8, 1))
        response = MagicMock(status_code=401, text="unauthorized")
        with (
            patch("src.agent.tools.todoist._get_todoist_token", return_value="revoked"),
            patch("requests.get", return_value=response),
        ):
            parsed = json.loads(todoist.invoke({"action": "list_projects"}))

        assert parsed["error"] == "Todoist disconnected"
        assert parsed["retriable"] is False
