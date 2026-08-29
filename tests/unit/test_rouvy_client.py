"""Tests for the Rouvy httpx CRUD client (httpx + auth mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import rouvy as rc


class FakeUser:
    id = "u1"
    rouvy_email = "e@x.com"
    rouvy_password = "pw"
    rouvy_session = json.dumps([{"name": "s", "value": "v", "domain": ".rouvy.com"}])


def _resp(status=200, text='[{"_1":2}]', ctype="text/x-script"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = {"content-type": ctype}
    r.raise_for_status = MagicMock()
    return r


def test_not_connected_raises():
    u = FakeUser()
    u.rouvy_session = None
    with pytest.raises(rc.RouvyNotConnected):
        rc.rouvy_list(u)


@patch("src.agent.tools.rouvy._client_request")
def test_create_posts_multipart_field_file(mock_req):
    mock_req.return_value = _resp(text='[{"_1":2},"data",{"_3":-5},"error","workoutId",123]')
    out = rc.rouvy_create(FakeUser(), "<workout_file/>", "My Ride", "desc")
    method, url, kwargs, jar = mock_req.call_args[0]
    assert method == "POST"
    assert url.endswith("/resources/workout-upload.data")
    assert "file" in kwargs["files"]  # field name is `file`, not `workout`
    assert out["id"] == 123
    assert out["workout_url"].endswith("/workouts/123")


@patch("src.agent.tools.rouvy._client_request")
def test_delete_posts_id_body(mock_req):
    mock_req.return_value = _resp()
    out = rc.rouvy_delete(FakeUser(), 4183941)
    method, url, kwargs, jar = mock_req.call_args[0]
    assert method == "POST"
    assert url.endswith("/workouts/4183941.data")
    assert kwargs["data"] == {"id": "4183941"}
    assert out == {"deleted": True, "id": 4183941}


@patch("src.agent.tools.rouvy._client_request")
def test_list_parses_created_collection(mock_req):
    mock_req.return_value = _resp(text='x,"4183941","ZZ Ride",6,"4084106","Sweet Spot",9')
    out = rc.rouvy_list(FakeUser())
    assert {"id": 4183941, "name": "ZZ Ride"} in out
    assert {"id": 4084106, "name": "Sweet Spot"} in out


@patch("src.agent.tools.rouvy._client_request")
def test_expired_triggers_refresh_and_retry(mock_req):
    mock_req.side_effect = [
        _resp(status=200, text="<!doctype html><title>Sign In</title>", ctype="text/html"),
        _resp(text='"error","workoutId",9'),
    ]
    with (
        patch("src.agent.tools.rouvy.rouvy_auth.login", return_value="[]") as login,
        patch("src.agent.tools.rouvy.db.update_user_rouvy_session") as save,
    ):
        out = rc.rouvy_create(FakeUser(), "<x/>", "n")
    assert login.called and save.called
    assert out["id"] == 9


@patch("src.agent.tools.rouvy._client_request")
def test_refresh_failure_raises_reconnect(mock_req):
    mock_req.return_value = _resp(status=401, text="unauthorized")
    with patch(
        "src.agent.tools.rouvy.rouvy_auth.login",
        side_effect=rc.rouvy_auth.RouvyAuthError("captcha"),
    ):
        with pytest.raises(rc.RouvySessionExpired):
            rc.rouvy_create(FakeUser(), "<x/>", "n")


@patch("src.agent.tools.rouvy.rouvy_delete")
@patch("src.agent.tools.rouvy.rouvy_create")
def test_update_is_delete_then_create(mock_create, mock_delete):
    mock_create.return_value = {"id": 5, "workout_url": ".../workouts/5"}
    out = rc.rouvy_update(FakeUser(), 4, "<x/>", "n")
    mock_delete.assert_called_once()
    mock_create.assert_called_once()
    assert out["id"] == 5
