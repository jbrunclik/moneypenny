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


class TestBulkyFieldStripping:
    """Garmin payloads carry per-minute series that blew a briefing run
    to ~150k input tokens - stripping keeps summaries only."""

    def test_time_series_keys_dropped_summaries_kept(self) -> None:
        from src.agent.tools.garmin import _strip_bulky_fields

        sleep_payload = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 27360,
                "deepSleepSeconds": 5460,
                "remSleepSeconds": 6840,
                "sleepScores": {"overall": {"value": 82}},
            },
            "sleepMovement": [{"startGMT": i, "activityLevel": 1.2} for i in range(480)],
            "sleepHeartRate": [{"value": 52, "startGMT": i} for i in range(456)],
            "hrvData": [{"value": 55}] * 3,
            "avgOvernightHrv": 55,
        }

        slimmed = _strip_bulky_fields(sleep_payload)
        assert slimmed["dailySleepDTO"]["sleepScores"]["overall"]["value"] == 82
        assert slimmed["avgOvernightHrv"] == 55
        assert "sleepMovement" not in slimmed
        assert "sleepHeartRate" not in slimmed
        # Short lists survive
        assert slimmed["hrvData"] == [{"value": 55}] * 3

    def test_unknown_long_lists_collapse_to_note(self) -> None:
        from src.agent.tools.garmin import _strip_bulky_fields

        payload = {"someNewSeries": [{"t": i} for i in range(300)], "avg": 7}
        slimmed = _strip_bulky_fields(payload)
        assert slimmed["avg"] == 7
        assert isinstance(slimmed["someNewSeries"], str)
        assert "300 items omitted" in slimmed["someNewSeries"]

    def test_payload_size_reduction_is_drastic(self) -> None:
        import json

        from src.agent.tools.garmin import _strip_bulky_fields

        payload = {
            "dailySleepDTO": {"sleepTimeSeconds": 27360},
            "sleepMovement": [
                {"startGMT": f"2026-06-12T0{i % 10}:00", "level": 1.5} for i in range(500)
            ],
            "stressValuesArray": [[1718000000 + i, 25] for i in range(480)],
        }
        before = len(json.dumps(payload))
        after = len(json.dumps(_strip_bulky_fields(payload)))
        assert after < before / 10


class TestActivityBreakdowns:
    """get_activity_details attaches per-set / HR-zone / per-lap data that
    live in dedicated endpoints (get_activity returns only the summary)."""

    @staticmethod
    def _dispatch(mapping: dict) -> object:
        """Build a _safe_api_call side_effect dispatching on method name.

        A mapped Exception is raised; an unmapped method returns {}.
        """

        def fake(garmin: object, method: str, *args: object, **kwargs: object) -> object:
            val = mapping.get(method, {})
            if isinstance(val, Exception):
                raise val
            return val

        return fake

    def _invoke(self, mapping: dict) -> dict:
        with (
            patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin._safe_api_call", side_effect=self._dispatch(mapping)),
        ):
            return json.loads(
                garmin_connect.invoke({"action": "get_activity_details", "activity_id": "a1"})
            )

    def test_strength_exercise_sets_slimmed(self) -> None:
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {"duration": 138.5}},
                "get_activity_exercise_sets": {
                    "exerciseSets": [
                        {
                            "setType": "ACTIVE",
                            "exercises": [{"category": "PUSH_UP", "probability": 100.0}],
                            "repetitionCount": 28,
                            "weight": None,
                            "duration": 54.606,
                            "messageIndex": 0,
                        },
                        {"setType": "REST", "exercises": [], "duration": 181.6},
                        {
                            "setType": "ACTIVE",
                            "exercises": [{"category": "PUSH_UP"}],
                            "repetitionCount": 23,
                            "duration": 46.8,
                        },
                    ]
                },
            }
        )
        sets = out["exercise_sets"]
        assert [s.get("reps") for s in sets if s["setType"] == "ACTIVE"] == [28, 23]
        # noise fields (messageIndex, probability, startTime) are dropped
        assert sets[0] == {
            "setType": "ACTIVE",
            "category": "PUSH_UP",
            "reps": 28,
            "weight": None,
            "duration_s": 54.6,
        }

    def test_hr_zones_converted_to_minutes(self) -> None:
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {"averagePower": 115}},
                "get_activity_hr_in_timezones": [
                    {"zoneNumber": 1, "secsInZone": 426.0, "zoneLowBoundary": 96},
                    {"zoneNumber": 2, "secsInZone": 4512.0, "zoneLowBoundary": 115},
                ],
            }
        )
        assert out["hr_zones"] == [
            {"zone": 1, "minutes": 7.1, "low_bpm": 96},
            {"zone": 2, "minutes": 75.2, "low_bpm": 115},
        ]
        assert "exercise_sets" not in out  # no sets for a ride

    def test_multi_lap_splits_exposed(self) -> None:
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {}},
                "get_activity_splits": {
                    "lapDTOs": [
                        {"distance": 5000, "duration": 600, "averageHR": 140, "averagePower": 200},
                        {"distance": 5000, "duration": 620, "averageHR": 150, "averagePower": 210},
                    ]
                },
            }
        )
        assert len(out["laps"]) == 2
        assert out["laps"][0]["lap"] == 1
        assert out["laps"][0]["distance_km"] == 5.0
        assert out["laps"][1]["avg_power"] == 210

    def test_single_lap_omitted(self) -> None:
        """One lap == the whole activity, already in the summary - skip it."""
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {}},
                "get_activity_splits": {"lapDTOs": [{"distance": 32000, "duration": 5400}]},
            }
        )
        assert "laps" not in out

    def test_laps_capped_with_note(self) -> None:
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {}},
                "get_activity_splits": {
                    "lapDTOs": [{"distance": 1000, "duration": 200} for _ in range(45)]
                },
            }
        )
        assert len(out["laps"]) == 40
        assert "first 40 of 45" in out["laps_note"]

    def test_breakdown_endpoint_errors_are_swallowed(self) -> None:
        """A failing breakdown endpoint must not fail the details call."""
        out = self._invoke(
            {
                "get_activity": {"summaryDTO": {"duration": 100}},
                "get_activity_exercise_sets": Exception("500 server error"),
                "get_activity_hr_in_timezones": Exception("403 forbidden"),
            }
        )
        assert out["action"] == "get_activity_details"
        assert "exercise_sets" not in out
        assert "hr_zones" not in out
