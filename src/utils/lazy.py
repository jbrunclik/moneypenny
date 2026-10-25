"""A process-wide value built on first use.

gthread workers serve requests on several threads, so two of them can hit a
cold singleton at once; without the lock each builds its own copy (duplicate
thread pools, connection pools, cleanup threads). functools.cache does not
lock the call, so it only fits values that are harmless to build twice.
"""

import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager


class Lazy[T]:
    """Builds its value once, on the first get(), even when threads race."""

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._value: T | None = None
        self._lock = threading.Lock()

    def get(self) -> T:
        value = self._value
        if value is None:
            with self._lock:
                if self._value is None:
                    self._value = self._factory()
                value = self._value
        return value

    def peek(self) -> T | None:
        """The value if it was built, without building it."""
        return self._value

    def reset(self) -> None:
        """Forget the value; the next get() builds a new one."""
        with self._lock:
            self._value = None

    @contextmanager
    def override(self, value: T) -> Generator[T]:
        """Serve `value` instead for the duration (tests, the E2E server)."""
        with self._lock:
            previous, self._value = self._value, value
        try:
            yield value
        finally:
            with self._lock:
                self._value = previous
