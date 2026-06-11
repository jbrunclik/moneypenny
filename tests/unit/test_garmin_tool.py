"""Unit tests for the Garmin tool's guard logic (T2 leftovers).

The garth API itself is not exercised - these cover the connection guard,
action dispatch, error mapping and the bulky-field stripping that keeps
50-200KB activity payloads out of LLM context.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.garmin import (
    _GARMIN_ACTIONS,
    _safe_api_call,
    _strip_bulky_fields,
    garmin_connect,
)


class TestGarminGuards:
    def test_not_connected(self) -> None:
        with patch("src.agent.tools.garmin._get_garmin_client", return_value=None):
            result = json.loads(garmin_connect.invoke({"action": "get_stats"}))
        assert result["error"] == "Garmin not connected"
        assert result["retriable"] is False

    def test_unknown_action_lists_available(self) -> None:
        with patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()):
            result = json.loads(garmin_connect.invoke({"action": "fly_to_moon"}))
        assert "Unknown action" in result["error"]
        assert result["available_actions"] == sorted(_GARMIN_ACTIONS)

    def test_activity_details_requires_id(self) -> None:
        with patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()):
            result = json.loads(garmin_connect.invoke({"action": "get_activity_details"}))
        assert "activity_id is required" in result["error"]

    def test_get_stats_happy_path(self) -> None:
        with (
            patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()),
            patch(
                "src.agent.tools.garmin._safe_api_call",
                return_value={"totalSteps": 12000},
            ),
        ):
            result = json.loads(
                garmin_connect.invoke({"action": "get_stats", "date_str": "2026-06-10"})
            )
        assert result["action"] == "get_stats"
        assert result["date"] == "2026-06-10"

    def test_get_activities_applies_limit(self) -> None:
        activities = [{"activityId": i} for i in range(30)]
        with (
            patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin._safe_api_call", return_value=activities),
        ):
            result = json.loads(garmin_connect.invoke({"action": "get_activities", "limit": 5}))
        assert result["count"] == 5

    def test_api_error_is_contained(self) -> None:
        """Errors surface as JSON error envelopes, never as raised exceptions."""
        with (
            patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()),
            patch(
                "src.agent.tools.garmin._safe_api_call",
                side_effect=Exception("Garmin session has expired."),
            ),
        ):
            result = json.loads(garmin_connect.invoke({"action": "get_stats"}))
        assert "expired" in result["error"]


class TestSafeApiCall:
    def _garmin_raising(self, message: str) -> MagicMock:
        garmin = MagicMock()
        garmin.get_stats.side_effect = Exception(message)
        return garmin

    def test_expired_session_mapped(self) -> None:
        with pytest.raises(Exception, match="expired. Please reconnect"):
            _safe_api_call(self._garmin_raising("401 unauthorized"), "get_stats")

    def test_rate_limit_mapped(self) -> None:
        with pytest.raises(Exception, match="rate limited"):
            _safe_api_call(self._garmin_raising("429 too many requests"), "get_stats")

    def test_forbidden_mapped(self) -> None:
        with pytest.raises(Exception, match="access denied"):
            _safe_api_call(self._garmin_raising("403 forbidden"), "get_stats")

    def test_other_errors_re_raise(self) -> None:
        with pytest.raises(Exception, match="weird failure"):
            _safe_api_call(self._garmin_raising("weird failure"), "get_stats")

    def test_success_persists_refreshed_tokens(self) -> None:
        garmin = MagicMock()
        garmin.get_stats.return_value = {"ok": True}
        with patch("src.agent.tools.garmin._persist_refreshed_tokens") as mock_persist:
            result = _safe_api_call(garmin, "get_stats")
        assert result == {"ok": True}
        mock_persist.assert_called_once_with(garmin)


class TestStripBulkyFields:
    def test_long_lists_are_summarized(self) -> None:
        data = {"waypoints": list(range(500)), "name": "Run"}
        stripped = _strip_bulky_fields(data, max_list_items=20)
        assert stripped["name"] == "Run"
        assert "500 items omitted" in stripped["waypoints"]

    def test_short_lists_pass_through(self) -> None:
        data = {"splits": [1, 2, 3]}
        assert _strip_bulky_fields(data)["splits"] == [1, 2, 3]

    def test_nested_structures(self) -> None:
        data = {"summary": {"laps": [{"metrics": list(range(100))}]}}
        stripped = _strip_bulky_fields(data, max_list_items=10)
        assert "100 items omitted" in stripped["summary"]["laps"][0]["metrics"]
