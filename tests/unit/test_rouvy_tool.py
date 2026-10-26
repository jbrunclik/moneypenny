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


def _invoke_connected(args: dict, **patches) -> dict:
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_connected()):
        if not patches:
            return json.loads(rouvy_workout.invoke(args))
        (name, value), *_ = patches.items()
        with patch(f"src.agent.tools.rouvy.{name}", **value):
            return json.loads(rouvy_workout.invoke(args))


def test_list_and_get_dispatch():
    listed = _invoke_connected({"action": "list"}, rouvy_list={"return_value": [{"id": 1}]})
    got = _invoke_connected(
        {"action": "get", "workout_id": 3}, rouvy_get={"return_value": {"id": 3}}
    )
    assert listed == {"success": True, "workouts": [{"id": 1}]}
    assert got == {"success": True, "workout": {"id": 3}}


def test_get_update_and_delete_need_their_args():
    get = _invoke_connected({"action": "get"})
    update = _invoke_connected({"action": "update", "content": "<x/>", "name": "n"})
    delete = _invoke_connected({"action": "delete"})
    assert get["error"] == "get needs workout_id."
    assert update["error"] == "update needs workout_id, content, name."
    assert delete["error"] == "delete needs workout_id."


def test_delete_dispatch():
    out = _invoke_connected(
        {"action": "delete", "workout_id": 5}, rouvy_delete={"return_value": {"deleted": 5}}
    )
    assert out == {"success": True, "deleted": 5}


def test_rouvy_errors_become_results():
    from src.agent.tools.rouvy import RouvyNotConnectedError, RouvySessionExpiredError

    not_connected = _invoke_connected(
        {"action": "list"}, rouvy_list={"side_effect": RouvyNotConnectedError()}
    )
    expired = _invoke_connected(
        {"action": "list"}, rouvy_list={"side_effect": RouvySessionExpiredError()}
    )
    failed = _invoke_connected({"action": "list"}, rouvy_list={"side_effect": Exception("503")})
    assert not_connected["success"] is False and "connect" in not_connected["error"].lower()
    assert expired["success"] is False and expired != not_connected
    assert failed["error"] == "Rouvy request failed: 503"


def test_rouvy_workout_is_registered():
    from src.agent.tools import get_all_tool_names

    assert "rouvy_workout" in get_all_tool_names()
