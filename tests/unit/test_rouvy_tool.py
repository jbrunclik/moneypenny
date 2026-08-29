"""Tests for the rouvy_workout tool dispatcher + registration/gating."""

import json
from unittest.mock import patch

from src.agent.tools.rouvy import rouvy_workout


class _User:
    id = "u1"
    rouvy_email = "e@x.com"
    rouvy_password = "pw"
    rouvy_session = "[]"


def _connected():
    return _User()


def _disconnected():
    u = _User()
    u.rouvy_session = None
    return u


def test_not_connected_message():
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_disconnected()):
        out = json.loads(rouvy_workout.invoke({"action": "list"}))
    assert out["success"] is False
    assert "connect" in out["error"].lower()


def test_create_dispatch():
    with (
        patch("src.agent.tools.rouvy._resolve_user", return_value=_connected()),
        patch(
            "src.agent.tools.rouvy.rouvy_create",
            return_value={"id": 7, "workout_url": "u/7"},
        ) as mock_create,
    ):
        out = json.loads(
            rouvy_workout.invoke({"action": "create", "content": "<x/>", "name": "Ride"})
        )
    assert out["success"] is True and out["workout_url"] == "u/7"
    mock_create.assert_called_once()


def test_create_missing_args():
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_connected()):
        out = json.loads(rouvy_workout.invoke({"action": "create", "name": "Ride"}))
    assert out["success"] is False


def test_update_notes_url_change():
    with (
        patch("src.agent.tools.rouvy._resolve_user", return_value=_connected()),
        patch(
            "src.agent.tools.rouvy.rouvy_update",
            return_value={"id": 9, "workout_url": "u/9"},
        ),
    ):
        out = json.loads(
            rouvy_workout.invoke(
                {"action": "update", "workout_id": 4, "content": "<x/>", "name": "n"}
            )
        )
    assert out["success"] is True
    assert "changed" in out["note"].lower()


def test_unknown_action():
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_connected()):
        out = json.loads(rouvy_workout.invoke({"action": "frobnicate"}))
    assert out["success"] is False


def test_rouvy_workout_not_in_sports_excluded():
    from src.agent.tools import _SPORTS_EXCLUDED_TOOLS

    assert "rouvy_workout" not in _SPORTS_EXCLUDED_TOOLS


def test_rouvy_workout_in_tool_map():
    from src.agent.tools import _TOOL_MAP

    assert _TOOL_MAP["rouvy_workout"] is rouvy_workout
