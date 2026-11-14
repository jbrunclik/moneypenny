"""Every trafilatura call goes through run_trafilatura: one at a time, bounded.

trafilatura and htmldate parse with module-level lxml parsers
(`trafilatura.utils.HTML_PARSER`, `htmldate.utils.HTML_PARSER`), and an lxml
parser must not be used by two threads at once. research fetches its pages in
a thread pool, so two pages could be parsed together - production workers
died with `free(): invalid pointer` (SIGABRT) seconds into a research call on
Oct 28, Nov 11 and Nov 14 2026. Fetching stays parallel; only parsing (tens of
milliseconds per page) is serialized. A huge page, or a parse that holds the
lock too long, sends the caller to its non-trafilatura fallback instead of
stalling every other turn's parsing in the worker.
"""

import threading
from collections.abc import Callable

from src.constants import TRAFILATURA_LOCK_WAIT_SECONDS, TRAFILATURA_MAX_HTML_CHARS
from src.utils.logging import get_logger

logger = get_logger(__name__)

TRAFILATURA_LOCK = threading.Lock()


def run_trafilatura[T](parse: Callable[[], T], html: str | bytes, fallback: T) -> T:
    """`parse()` under the lock, or `fallback` for an oversized page or a long wait."""
    if len(html) > TRAFILATURA_MAX_HTML_CHARS:
        logger.info("Page parse skipped", extra={"reason": "size", "chars": len(html)})
        return fallback
    if not TRAFILATURA_LOCK.acquire(timeout=TRAFILATURA_LOCK_WAIT_SECONDS):
        logger.warning("Page parse skipped", extra={"reason": "lock_wait", "chars": len(html)})
        return fallback
    try:
        return parse()
    finally:
        TRAFILATURA_LOCK.release()
