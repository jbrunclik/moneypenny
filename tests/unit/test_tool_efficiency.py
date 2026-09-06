"""Tests for the tool-efficiency work (Sep 2026).

A prod log audit found the agent drip-feeding one tool call per round: 866
web_search calls across 864 separate rounds, 99% single-query, plus 57
get-then-set kv_store round pairs and a Garmin client rebuilt (two extra HTTP
round trips) on every single call. These cover the mechanisms added to stop
that: per-turn call counting, the batching nudges attached to search results,
kv_store merge, and the cached Garmin session.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tool_results import set_current_request_id
from src.agent.tools import garmin_session
from src.agent.tools.agent_kv import _deep_merge, kv_store
from src.agent.tools.turn_usage import (
    get_tool_call_count,
    record_tool_call,
    reset_turn_usage,
)
from src.agent.tools.web import _batching_nudge, _chained_fetch_nudge


@pytest.fixture
def turn():
    """A request-scoped turn, torn down so counts never leak between tests."""
    set_current_request_id("test-request")
    reset_turn_usage()
    yield
    reset_turn_usage()
    set_current_request_id(None)


class TestTurnUsage:
    def test_counts_increment_within_a_turn(self, turn) -> None:
        assert record_tool_call("web_search") == 1
        assert record_tool_call("web_search") == 2
        assert get_tool_call_count("web_search") == 2

    def test_tools_counted_independently(self, turn) -> None:
        record_tool_call("web_search")
        assert record_tool_call("fetch_url") == 1
        assert get_tool_call_count("web_search") == 1

    def test_separate_turns_do_not_share_counts(self, turn) -> None:
        record_tool_call("web_search")
        set_current_request_id("another-request")
        try:
            assert get_tool_call_count("web_search") == 0
        finally:
            reset_turn_usage()
            set_current_request_id("test-request")

    def test_no_request_context_is_inert(self) -> None:
        """Evals and unit tests run without a request; counting must not blow up."""
        set_current_request_id(None)
        assert record_tool_call("web_search") == 0
        assert get_tool_call_count("web_search") == 0


class TestBatchingNudge:
    def test_first_search_is_not_nudged(self) -> None:
        assert _batching_nudge(1) is None

    def test_second_search_suggests_batching_and_research(self) -> None:
        nudge = _batching_nudge(2)
        assert nudge is not None
        assert "queries=[...]" in nudge
        assert "research" in nudge

    def test_third_search_escalates_to_a_prohibition(self) -> None:
        nudge = _batching_nudge(3)
        assert nudge is not None
        assert "Do NOT" in nudge

    def test_batched_call_counts_as_one_search(self, turn) -> None:
        """A five-query call is the desired behaviour, so it must not self-nudge."""
        with patch(
            "src.agent.tools.web._search_one",
            side_effect=lambda q, n: {"query": q, "results": []},
        ):
            from src.agent.tools.web import web_search

            result = json.loads(web_search.invoke({"queries": ["a", "b", "c", "d", "e"]}))
        assert len(result["searches"]) == 5
        assert "_efficiency" not in result

    def test_repeat_single_searches_attach_a_nudge(self, turn) -> None:
        from src.agent.tools.web import web_search

        with patch(
            "src.agent.tools.web._search_one",
            side_effect=lambda q, n: {"query": q, "results": []},
        ):
            first = json.loads(web_search.invoke({"query": "one"}))
            second = json.loads(web_search.invoke({"query": "two"}))
        assert "_efficiency" not in first
        assert "EFFICIENCY" in second["_efficiency"]

    def test_chained_fetch_nudge_only_after_a_search(self, turn) -> None:
        assert _chained_fetch_nudge() is None
        record_tool_call("web_search")
        nudge = _chained_fetch_nudge()
        assert nudge is not None and "research" in nudge


class TestDeepMerge:
    def test_adds_and_overwrites_scalars(self) -> None:
        assert _deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}

    def test_nested_objects_merge_rather_than_replace(self) -> None:
        base = {"progress": {"squat": 100, "bench": 60}}
        assert _deep_merge(base, {"progress": {"bench": 65}}) == {
            "progress": {"squat": 100, "bench": 65}
        }

    def test_null_deletes_a_key(self) -> None:
        assert _deep_merge({"a": 1, "b": 2}, {"b": None}) == {"a": 1}

    def test_base_is_not_mutated(self) -> None:
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"c": 2}})
        assert base == {"a": {"b": 1}}


class TestKvMerge:
    """kv_store merge collapses the get-then-set pattern into one round."""

    def _invoke(self, args: dict, stored: str | None) -> str:
        with (
            patch(
                "src.agent.tools.agent_kv.get_conversation_context",
                return_value=("c1", "u1"),
            ),
            patch("src.agent.tools.context.get_sports_context", return_value="cycling"),
            patch("src.agent.tools.agent_kv.db") as mock_db,
        ):
            mock_db.kv_get.return_value = stored
            mock_db.kv_count.return_value = 0
            result = kv_store.invoke(args)
            self.written = mock_db.kv_set.call_args[0][3] if mock_db.kv_set.call_args else None
        return result

    def test_merges_into_existing_object(self) -> None:
        self._invoke(
            {"action": "merge", "key": "cycling:progress", "value": '{"ftp": 265}'},
            stored='{"ftp": 250, "weight": 74}',
        )
        assert json.loads(self.written) == {"ftp": 265, "weight": 74}

    def test_creates_the_key_when_absent(self) -> None:
        self._invoke(
            {"action": "merge", "key": "cycling:goals", "value": '{"target": "sub-3h"}'},
            stored=None,
        )
        assert json.loads(self.written) == {"target": "sub-3h"}

    def test_rejects_non_object_patch(self) -> None:
        result = self._invoke({"action": "merge", "key": "k", "value": "[1, 2]"}, stored=None)
        assert "requires a JSON object" in result

    def test_rejects_merging_into_a_non_object(self) -> None:
        result = self._invoke({"action": "merge", "key": "k", "value": '{"a": 1}'}, stored="[1, 2]")
        assert "not a JSON object" in result

    def test_invalid_action_lists_merge(self) -> None:
        result = self._invoke({"action": "frobnicate", "key": "k"}, stored=None)
        assert "merge" in result


class TestGarminSessionCache:
    """The client is cached per user; a token change invalidates it at once."""

    def setup_method(self) -> None:
        garmin_session.clear_sessions()

    def teardown_method(self) -> None:
        garmin_session.clear_sessions()

    @staticmethod
    def _user(token: str) -> MagicMock:
        user = MagicMock()
        user.garmin_token = token
        return user

    def test_second_call_reuses_the_session(self) -> None:
        with (
            patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-a")),
            patch(
                "src.auth.garmin_auth.create_client_from_tokens",
                return_value=MagicMock(),
            ) as mock_create,
        ):
            first = garmin_session.get_client("u1")
            second = garmin_session.get_client("u1")

        assert first is second
        mock_create.assert_called_once()

    def test_changed_token_rebuilds_immediately(self) -> None:
        """A reconnect rewrites the token; every worker must drop its session."""
        with (
            patch(
                "src.auth.garmin_auth.create_client_from_tokens",
                side_effect=lambda t: MagicMock(name=t),
            ) as mock_create,
        ):
            with patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-a")):
                first = garmin_session.get_client("u1")
            with patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-b")):
                second = garmin_session.get_client("u1")

        assert first is not second
        assert mock_create.call_count == 2

    def test_no_token_means_not_connected(self) -> None:
        with patch("src.db.models.db.get_user_by_id", return_value=self._user("")):
            assert garmin_session.get_client("u1") is None

    def test_login_failure_returns_none(self) -> None:
        with (
            patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-a")),
            patch(
                "src.auth.garmin_auth.create_client_from_tokens",
                side_effect=Exception("session expired"),
            ),
        ):
            assert garmin_session.get_client("u1") is None

    def test_unchanged_tokens_are_not_rewritten(self) -> None:
        """Persisting on every API call meant 4 identical DB writes per details call."""
        client = MagicMock()
        with (
            patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-a")),
            patch("src.auth.garmin_auth.create_client_from_tokens", return_value=client),
        ):
            garmin_session.get_client("u1")

        with (
            patch("src.auth.garmin_auth.refresh_and_serialize", return_value="tok-a"),
            patch("src.db.models.db.update_user_garmin_token") as mock_update,
        ):
            garmin_session.persist_tokens_if_changed("u1", client)

        mock_update.assert_not_called()

    def test_rotated_tokens_are_written_back(self) -> None:
        client = MagicMock()
        with (
            patch("src.db.models.db.get_user_by_id", return_value=self._user("tok-a")),
            patch("src.auth.garmin_auth.create_client_from_tokens", return_value=client),
        ):
            garmin_session.get_client("u1")

        with (
            patch("src.auth.garmin_auth.refresh_and_serialize", return_value="tok-rotated"),
            patch("src.db.models.db.update_user_garmin_token") as mock_update,
        ):
            garmin_session.persist_tokens_if_changed("u1", client)

        mock_update.assert_called_once_with("u1", "tok-rotated")


class TestReadinessSnapshot:
    """One call replaces readiness + sleep + HRV + stats + status + activities."""

    def _invoke(self, mapping: dict) -> dict:
        def fake(garmin, method, *args, **kwargs):
            val = mapping.get(method, {})
            if isinstance(val, Exception):
                raise val
            return val

        with (
            patch("src.agent.tools.garmin._get_garmin_client", return_value=MagicMock()),
            patch("src.agent.tools.garmin._safe_api_call", side_effect=fake),
        ):
            from src.agent.tools.garmin import garmin_connect

            return json.loads(
                garmin_connect.invoke(
                    {"action": "get_readiness_snapshot", "date_str": "2026-09-06"}
                )
            )

    def test_gathers_every_section(self) -> None:
        out = self._invoke(
            {
                "get_training_readiness": {"score": 72},
                "get_sleep_data": {"dailySleepDTO": {"sleepTimeSeconds": 27000}},
                "get_hrv_data": {"hrvSummary": {"lastNightAvg": 58}},
                "get_stats": {"bodyBatteryAtWakeTime": 81},
                "get_training_status": {"trainingStatus": "productive"},
                "get_activities_by_date": [{"activityId": 1}, {"activityId": 2}],
            }
        )
        assert out["action"] == "get_readiness_snapshot"
        assert out["date"] == "2026-09-06"
        assert out["training_readiness"] == {"score": 72}
        assert out["hrv"] == {"hrvSummary": {"lastNightAvg": 58}}
        assert out["stats"] == {"bodyBatteryAtWakeTime": 81}
        assert out["training_status"] == {"trainingStatus": "productive"}
        assert len(out["recent_activities"]) == 2

    def test_a_failing_section_does_not_sink_the_snapshot(self) -> None:
        """Not every device reports HRV; the rest of the snapshot must survive."""
        out = self._invoke(
            {
                "get_training_readiness": {"score": 60},
                "get_hrv_data": Exception("no HRV for this device"),
            }
        )
        assert out["training_readiness"] == {"score": 60}
        assert "no HRV" in out["hrv"]["error"]

    def test_snapshot_is_an_advertised_action(self) -> None:
        from src.agent.tools.garmin import _GARMIN_ACTIONS

        assert "get_readiness_snapshot" in _GARMIN_ACTIONS
