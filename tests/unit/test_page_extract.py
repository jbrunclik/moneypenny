"""Reading a page through Exa when the direct fetch is refused (403/429).

Measured Nov 15 2026: Exa /contents read 9 of 10 pages that 403 the
production host, for $0.009 (docs/superpowers/specs/2026-11-15-web-reading-design.md).
Its spend is billed into Exa's search usage counter ($0.007 a unit) by cost.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.config import Config
from src.services import page_extract
from src.services.search_provider import _breaker_tripped, get_monthly_usage, usage_key


@pytest.fixture
def store() -> dict[str, str]:
    return {}


@pytest.fixture(autouse=True)
def _kv(store: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    db = MagicMock()
    db.kv_get.side_effect = lambda _u, _ns, key: store.get(key)
    db.kv_set.side_effect = lambda _u, _ns, key, value: store.__setitem__(key, value)
    db.kv_delete.side_effect = lambda _u, _ns, key: store.pop(key, None)

    def _incr(_u: str, _ns: str, key: str, delta: int = 1) -> int:
        store[key] = str(int(store.get(key, "0")) + delta)
        return int(store[key])

    db.kv_increment.side_effect = _incr
    monkeypatch.setattr("src.services.search_provider.db", db)
    monkeypatch.setattr(Config, "EXA_API_KEY", "test-key")
    return db


def _reply(status: int = 200, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", "https://x"))


def _ok(text: str = "Page text", cost: float = 0.001) -> httpx.Response:
    return _reply(
        body={
            "results": [{"url": "https://shop.example/p", "text": text}],
            "statuses": [{"id": "https://shop.example/p", "status": "success"}],
            "costDollars": {"total": cost},
        }
    )


def test_a_page_is_read_through_exa() -> None:
    with patch("src.services.page_extract.httpx.post", return_value=_ok("Hello")) as post:
        assert page_extract.extract_page("https://shop.example/p", 6000) == ("Hello", None)
    kwargs = post.call_args.kwargs
    assert post.call_args.args[0] == "https://api.exa.ai/contents"
    assert kwargs["json"] == {
        "urls": ["https://shop.example/p"],
        "text": {"maxCharacters": 6000},
    }
    assert kwargs["timeout"] == Config.WEB_EXTRACT_TIMEOUT_SECONDS == 15


def test_text_is_cut_at_the_limit() -> None:
    with patch("src.services.page_extract.httpx.post", return_value=_ok("x" * 50)):
        text, _ = page_extract.extract_page("https://shop.example/p", 10)
    assert text == "x" * 10


def test_a_page_exa_cannot_read_is_an_error() -> None:
    refused = _reply(
        body={
            "results": [],
            "statuses": [
                {
                    "id": "https://shop.example/p",
                    "status": "error",
                    "error": {"httpStatusCode": 403, "tag": "SOURCE_NOT_AVAILABLE"},
                }
            ],
            "costDollars": {"total": 0},
        }
    )
    with patch("src.services.page_extract.httpx.post", return_value=refused):
        text, error = page_extract.extract_page("https://shop.example/p", 6000)
    assert text is None and error


def test_a_timeout_is_an_error_and_leaves_search_alone() -> None:
    with patch("src.services.page_extract.httpx.post", side_effect=httpx.ReadTimeout("slow")):
        text, error = page_extract.extract_page("https://shop.example/p", 6000)
    assert text is None and error
    assert not _breaker_tripped("exa")


def test_a_server_error_leaves_search_alone() -> None:
    with patch("src.services.page_extract.httpx.post", return_value=_reply(500)):
        assert page_extract.extract_page("https://shop.example/p", 6000)[0] is None
    assert not _breaker_tripped("exa")


def test_out_of_credit_benches_exa_for_search_too() -> None:
    with patch("src.services.page_extract.httpx.post", return_value=_reply(402)):
        text, error = page_extract.extract_page("https://shop.example/p", 6000)
    assert text is None and error
    assert _breaker_tripped("exa")
    assert page_extract.extract_available() is False


def test_available_with_a_key_and_headroom() -> None:
    assert page_extract.extract_available() is True


def test_not_available_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "EXA_API_KEY", "")
    assert page_extract.extract_available() is False


def test_the_last_tenth_of_exa_stays_for_search(
    store: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "SEARCH_QUOTA_EXA_MONTHLY", 100)
    store[usage_key("exa")] = "89"
    assert page_extract.extract_available() is True
    store[usage_key("exa")] = "90"
    assert page_extract.extract_available() is False
    assert Config.WEB_EXTRACT_QUOTA_SHARE == 0.9


def test_pages_are_billed_by_cost_not_one_unit_each() -> None:
    for _ in range(7):
        page_extract.record_extract_cost(0.001)
    assert get_monthly_usage("exa") == 1


def test_fractions_add_up_across_pages() -> None:
    page_extract.record_extract_cost(0.003)
    assert get_monthly_usage("exa") == 0
    page_extract.record_extract_cost(0.005)
    assert get_monthly_usage("exa") == 1


def test_a_read_bills_its_cost() -> None:
    with patch("src.services.page_extract.httpx.post", return_value=_ok(cost=0.007)):
        page_extract.extract_page("https://shop.example/p", 6000)
    assert get_monthly_usage("exa") == 1


def test_each_read_is_logged_with_its_outcome_and_cost() -> None:
    with (
        patch("src.services.page_extract.httpx.post", return_value=_ok(cost=0.001)),
        patch.object(page_extract.logger, "info") as info,
    ):
        page_extract.extract_page("https://shop.example/p", 6000, direct_status=403)
    [extra] = [
        c.kwargs["extra"] for c in info.call_args_list if c.args[0] == "Page read via fallback"
    ]
    assert extra["host"] == "shop.example"
    assert (extra["via"], extra["status"], extra["direct_status"]) == ("exa", "ok", 403)
    assert extra["cost_usd"] == 0.001
    assert isinstance(extra["elapsed_ms"], int)
