"""The browser tool's press, select and download actions (worker mocked).

The Playwright side is covered live in tests/integration/test_browser_actions.py.
"""

import base64
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.browser import browser


@pytest.fixture
def worker() -> Iterator[MagicMock]:
    mock = MagicMock(unhealthy=False)
    with (
        patch("src.agent.tools.browser.Config.BROWSER_ENABLED", True),
        patch("src.agent.tools.browser.is_browser_available", return_value=True),
        patch("src.agent.tools.browser.start_cleanup_thread"),
        patch("src.agent.tools.browser.get_worker", return_value=mock),
    ):
        yield mock


def _run(**args: Any) -> dict[str, Any]:
    result = browser.invoke(args)
    assert isinstance(result, str)
    parsed: dict[str, Any] = json.loads(result)
    return parsed


@pytest.mark.parametrize("key", ["Enter", "Escape", "ArrowDown", "Control+A", "Shift+Tab", "a"])
def test_press_passes_the_key(worker: MagicMock, key: str) -> None:
    worker.execute.return_value = {"success": True}
    _run(action="press", text=key, selector="#q")
    worker.execute.assert_called_once_with(
        "press", conversation_id="__default__", key=key, selector="#q"
    )


@pytest.mark.parametrize("key", [None, "", "Enter; rm", "x" * 40])
def test_press_rejects_a_missing_or_odd_key(worker: MagicMock, key: str | None) -> None:
    assert "key" in _run(action="press", text=key)["error"].lower()
    worker.execute.assert_not_called()


def test_select_needs_selector_and_option(worker: MagicMock) -> None:
    assert "selector" in _run(action="select", text="Large")["error"]
    assert "text" in _run(action="select", selector="#size")["error"]
    worker.execute.assert_not_called()


def test_press_and_select_batch(worker: MagicMock) -> None:
    worker.execute.return_value = {"success": True, "title": "t", "url": "u"}
    result = browser.invoke(
        {
            "actions": [
                {"action": "select", "selector": "#size", "text": "Large"},
                {"action": "press", "text": "Enter"},
            ]
        }
    )
    assert "error" not in json.loads(str(result))
    assert [c.args[0] for c in worker.execute.call_args_list] == ["select", "press"]


def test_download_is_not_batchable(worker: MagicMock) -> None:
    result = json.loads(
        str(browser.invoke({"actions": [{"action": "download", "selector": "#a"}]}))
    )
    assert "error" in result
    worker.execute.assert_not_called()


def test_download_attaches_the_file_and_shows_a_text_excerpt(worker: MagicMock) -> None:
    worker.execute.return_value = {
        "success": True,
        "name": "kids.csv",
        "size": 14,
        "data": base64.b64encode(b"name,age\nana,9").decode(),
    }
    with (
        patch("src.agent.tools.browser.get_current_request_id", return_value="req"),
        patch("src.agent.tools.browser.store_tool_result") as store,
    ):
        result = _run(action="download", selector="#csv")
    files = json.loads(store.call_args.args[1])["_full_result"]["files"]
    assert files[0]["name"] == "kids.csv" and files[0]["mime_type"] == "text/csv"
    assert result["downloaded"] == "kids.csv" and result["attached"] is True
    assert "ana,9" in result["excerpt"]


def test_download_of_a_binary_file_has_no_excerpt(worker: MagicMock) -> None:
    worker.execute.return_value = {
        "success": True,
        "name": "ticket.pdf",
        "size": 4,
        "data": base64.b64encode(b"%PDF").decode(),
    }
    with (
        patch("src.agent.tools.browser.get_current_request_id", return_value="req"),
        patch("src.agent.tools.browser.store_tool_result"),
    ):
        result = _run(action="download", selector="#pdf")
    assert result["mime_type"] == "application/pdf"
    assert "excerpt" not in result


def test_download_needs_a_selector(worker: MagicMock) -> None:
    assert "selector" in _run(action="download")["error"]


@pytest.mark.parametrize(
    ("page_name", "stored_name", "stored_type"),
    [
        ("page.html", "page.html", "application/octet-stream"),
        ("logo.svg", "logo.svg", "application/octet-stream"),
        ("app.js", "app.js", "application/octet-stream"),
        ("../../a<b>.pdf", "a_b_.pdf", "application/pdf"),
        ("..\\..\\a<b>.pdf", "a_b_.pdf", "application/pdf"),
        ("trasa.gpx", "trasa.gpx", "application/gpx+xml"),
        ("jízdenka.pdf", "jízdenka.pdf", "application/pdf"),
    ],
)
def test_a_download_keeps_only_safe_names_and_types(
    worker: MagicMock, page_name: str, stored_name: str, stored_type: str
) -> None:
    """Files are served from our origin with their stored type: a page must not
    get HTML, SVG or script stored as such."""
    worker.execute.return_value = {"success": True, "name": page_name, "size": 1, "data": "eA=="}
    with (
        patch("src.agent.tools.browser.get_current_request_id", return_value="req"),
        patch("src.agent.tools.browser.store_tool_result") as store,
    ):
        result = _run(action="download", selector="#a")
    stored = json.loads(store.call_args.args[1])["_full_result"]["files"][0]
    assert (stored["name"], stored["mime_type"]) == (stored_name, stored_type)
    assert result["downloaded"] == stored_name
