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


def _resp(status=200, text='[{"_1":2}]', ctype="text/x-script", cookies=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = {"content-type": ctype}
    r.cookies = cookies or {}
    r.raise_for_status = MagicMock()
    return r


# What Rouvy returns when the Firebase id token inside rouvy_session has expired:
# it refreshes the token, sets a new cookie and redirects to the SAME url
# instead of running the loader/action (React Router single-fetch redirect).
_REFRESH_REDIRECT = (
    '[{"_1":2,"_3":4,"_5":6,"_7":8,"_9":8},"redirect",'
    '"https://riders.rouvy.com/resources/workout-upload","status",302,'
    '"revalidate",true,"reload",false,"replace"]'
)


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


@patch("src.agent.tools.rouvy._client_request")
def test_refresh_redirect_retries_with_rotated_cookie_and_persists(mock_req):
    mock_req.side_effect = [
        _resp(status=202, text=_REFRESH_REDIRECT, cookies={"rouvy_session": "fresh"}),
        _resp(text='"error","workoutId",77'),
    ]
    user = FakeUser()
    user.rouvy_session = json.dumps(
        [{"name": "rouvy_session", "value": "stale", "domain": ".rouvy.com"}]
    )
    with (
        patch("src.agent.tools.rouvy.rouvy_auth.login") as login,
        patch("src.agent.tools.rouvy.db.update_user_rouvy_session") as save,
    ):
        out = rc.rouvy_create(user, "<x/>", "n")
    assert out["id"] == 77
    assert not login.called  # a token refresh is not a dead session
    assert mock_req.call_count == 2
    retry_jar = mock_req.call_args_list[1][0][3]
    assert retry_jar["rouvy_session"] == "fresh"
    save.assert_called_once()
    saved_user_id, saved_session = save.call_args[0]
    assert saved_user_id == "u1"
    assert rc.rouvy_auth.cookies_to_jar(saved_session)["rouvy_session"] == "fresh"
    assert rc.rouvy_auth.cookies_to_jar(user.rouvy_session)["rouvy_session"] == "fresh"


@patch("src.agent.tools.rouvy._client_request")
def test_refresh_redirect_on_list_retries(mock_req):
    mock_req.side_effect = [
        _resp(status=202, text=_REFRESH_REDIRECT, cookies={"rouvy_session": "fresh"}),
        _resp(text='x,"4183941","ZZ Ride",6'),
    ]
    with patch("src.agent.tools.rouvy.db.update_user_rouvy_session"):
        out = rc.rouvy_list(FakeUser())
    assert out == [{"id": 4183941, "name": "ZZ Ride"}]


@patch("src.agent.tools.rouvy._client_request")
def test_plain_turbo_redirect_without_cookie_is_not_retried(mock_req):
    # A successful delete answers with a redirect too, but rotates no cookie.
    mock_req.return_value = _resp(
        status=202, text='[{"_1":2},"redirect","/workouts","status",302,"replace"]'
    )
    with patch("src.agent.tools.rouvy.db.update_user_rouvy_session") as save:
        out = rc.rouvy_delete(FakeUser(), 5)
    assert out == {"deleted": True, "id": 5}
    assert mock_req.call_count == 1
    assert not save.called
