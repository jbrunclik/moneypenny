"""Tests for replaying a Rouvy request as an in-page fetch() (no browser launched)."""

from unittest.mock import patch

import pytest

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


def test_a_compressed_reply_is_not_decompressed_twice():
    """fetch() hands back the decoded body; keeping its content-encoding made
    httpx inflate it again ("Error -3 while decompressing data", Nov 15 2026)."""
    resp = rb.to_response(
        "GET",
        URL,
        200,
        {"content-encoding": "gzip", "content-length": "12", "content-type": "text/x-script"},
        '[{"_1":2},"workoutId","4904792"]',
        {},
        {},
    )
    assert resp.text == '[{"_1":2},"workoutId","4904792"]'


def test_a_busy_browser_pool_fails_fast_instead_of_launching_more():
    with (
        patch.object(rb, "_SLOTS") as slots,
        patch.object(rb, "_fetch_sync") as launch,
        pytest.raises(rb.RouvyBrowserError),
    ):
        slots.acquire.return_value = False
        rb.fetch("GET", URL, {}, {}, "UA")
    assert not launch.called


def test_the_slot_is_freed_when_the_request_fails():
    with (
        patch.object(rb, "_SLOTS") as slots,
        patch.object(rb, "_fetch_sync", side_effect=RuntimeError("boom")),
        pytest.raises(rb.RouvyBrowserError),
    ):
        slots.acquire.return_value = True
        rb.fetch("GET", URL, {}, {}, "UA")
    slots.release.assert_called_once()
