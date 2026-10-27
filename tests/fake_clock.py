"""A stand-in for `src.utils.clock._now` used by the test suite and the E2E server.

It never repeats: each reading is at least 1 µs after the previous one and
never behind the real clock. Rows written back to back then get distinct,
ordered timestamps, so nothing has to sleep to make them differ.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


def strictly_increasing_now() -> Callable[[], datetime]:
    """A fresh clock function (its own sequence, safe across threads)."""
    last = datetime.min.replace(tzinfo=UTC)
    lock = threading.Lock()

    def now() -> datetime:
        nonlocal last
        with lock:
            last = max(datetime.now(UTC), last + timedelta(microseconds=1))
            return last

    return now
