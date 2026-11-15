"""Tests for replaying a Rouvy request as an in-page fetch() (no browser launched)."""

from src.auth import rouvy_browser as rb

URL = "https://riders.rouvy.com/workouts/1.data"


def test_a_get_sends_no_body():
    assert rb.fetch_spec("GET", {"headers": {"User-Agent": "UA"}}) == {
        "method": "GET",
        "body": None,
    }


def test_form_data_goes_urlencoded():
    spec = rb.fetch_spec("POST", {"data": {"id": "4183941"}})
    assert spec == {"method": "POST", "body": {"kind": "form", "fields": {"id": "4183941"}}}


def test_an_upload_goes_multipart_with_its_filename_and_type():
    spec = rb.fetch_spec("POST", {"files": {"file": ("Ride.zwo", "<x/>", "application/xml")}})
    assert spec["body"] == {
        "kind": "multipart",
        "files": {"file": {"filename": "Ride.zwo", "content": "<x/>", "type": "application/xml"}},
    }


def test_the_reply_keeps_status_headers_and_body():
    resp = rb.to_response(
        "GET", URL, 202, {"content-type": "text/x-script"}, '[{"_1":2}]', {"s": "v"}, {"s": "v"}
    )
    assert resp.status_code == 202
    assert resp.headers["content-type"] == "text/x-script"
    assert resp.text == '[{"_1":2}]'
    assert dict(resp.cookies) == {}


def test_cookies_the_browser_rotated_come_back_as_set_cookie():
    """fetch() never exposes Set-Cookie: the rotation is read off the context."""
    resp = rb.to_response(
        "GET",
        URL,
        200,
        {},
        "",
        {"rouvy_session": "old", "keep": "same"},
        {"rouvy_session": "new", "keep": "same", "__cf_bm": "bm"},
    )
    assert resp.cookies.get("rouvy_session") == "new"
    assert resp.cookies.get("__cf_bm") == "bm"
    assert resp.cookies.get("keep") is None


def test_a_redirect_fetch_could_not_follow_reads_as_a_302():
    resp = rb.to_response("GET", URL, 0, {}, "", {}, {})
    assert resp.status_code == 302
