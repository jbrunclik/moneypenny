"""trafilatura parses with module-level lxml parsers (trafilatura.utils and
htmldate.utils HTML_PARSER) that must not run in two threads at once: the
research fetch pool did, and production workers died with
`free(): invalid pointer` / SIGABRT seconds into a research call (Oct 28,
Nov 11, Nov 14 2026). Every call goes through one lock."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import patch

from src.agent.tools.page_date import page_date_line
from src.agent.tools.web_content import extract_main_content


def _overlap_probe() -> tuple[Callable[..., Any], list[int]]:
    active = [0]
    peak = [0]
    lock = threading.Lock()

    def fake(*_args: Any, **_kwargs: Any) -> None:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.01)  # hold the "parse" open so a second thread inside would overlap
        with lock:
            active[0] -= 1

    return fake, peak


def test_extraction_and_metadata_never_run_concurrently() -> None:
    fake, peak = _overlap_probe()
    with (
        patch("trafilatura.extract", side_effect=fake),
        patch("trafilatura.extract_metadata", side_effect=fake),
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        calls = [extract_main_content, page_date_line] * 8
        list(pool.map(lambda f: f("<html><body><p>x</p></body></html>"), calls))
    assert peak[0] == 1


def test_a_held_lock_falls_back_instead_of_blocking(monkeypatch: Any) -> None:
    """One slow page must not stall every turn's parsing in the worker."""
    from src.agent.tools import trafilatura_lock

    monkeypatch.setattr(trafilatura_lock, "TRAFILATURA_LOCK_WAIT_SECONDS", 0.05)
    with patch("trafilatura.extract") as extract:
        trafilatura_lock.TRAFILATURA_LOCK.acquire()
        try:
            started = time.monotonic()
            assert extract_main_content("<html><body><p>x</p></body></html>") == ""
            assert page_date_line("<html></html>") == ""
            assert time.monotonic() - started < 1
        finally:
            trafilatura_lock.TRAFILATURA_LOCK.release()
    extract.assert_not_called()


def test_oversized_html_skips_trafilatura(monkeypatch: Any) -> None:
    from src.agent.tools import trafilatura_lock

    monkeypatch.setattr(trafilatura_lock, "TRAFILATURA_MAX_HTML_CHARS", 100)
    with patch("trafilatura.extract") as extract, patch("trafilatura.extract_metadata") as meta:
        big = "<html><body>" + "<p>x</p>" * 50 + "</body></html>"
        assert extract_main_content(big) == ""
        assert page_date_line(big) == ""
    extract.assert_not_called()
    meta.assert_not_called()
