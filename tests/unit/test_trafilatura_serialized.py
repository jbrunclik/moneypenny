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
