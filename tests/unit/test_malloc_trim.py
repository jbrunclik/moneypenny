"""Unit tests for the periodic glibc heap trim in each worker."""

import threading
from collections.abc import Generator
from unittest.mock import patch

import pytest

from src.utils import malloc_trim


@pytest.fixture(autouse=True)
def _stop_trimmer() -> Generator[None]:
    """Each test starts with no trim thread and leaves none behind."""
    malloc_trim.stop_malloc_trimmer()
    yield
    malloc_trim.stop_malloc_trimmer()


class _FakeLibc:
    def __init__(self) -> None:
        self.pads: list[int] = []
        self.called = threading.Event()

    def malloc_trim(self, pad: int) -> int:
        self.pads.append(pad)
        self.called.set()
        return 1


def test_zero_interval_starts_nothing() -> None:
    with (
        patch.object(malloc_trim.Config, "MALLOC_TRIM_INTERVAL_SECONDS", 0),
        patch.object(malloc_trim, "_load_libc", return_value=_FakeLibc()),
    ):
        assert malloc_trim.start_malloc_trimmer() is False


def test_libc_without_malloc_trim_starts_nothing() -> None:
    # macOS and musl have no malloc_trim
    with (
        patch.object(malloc_trim.Config, "MALLOC_TRIM_INTERVAL_SECONDS", 300),
        patch.object(malloc_trim, "_load_libc", return_value=object()),
    ):
        assert malloc_trim.start_malloc_trimmer() is False


def test_trims_the_whole_heap_every_interval() -> None:
    libc = _FakeLibc()
    with (
        patch.object(malloc_trim.Config, "MALLOC_TRIM_INTERVAL_SECONDS", 0.01),
        patch.object(malloc_trim, "_load_libc", return_value=libc),
    ):
        assert malloc_trim.start_malloc_trimmer() is True
        assert libc.called.wait(timeout=5)
    assert libc.pads[0] == 0  # pad 0: release every free page, not just the top


def test_second_start_keeps_the_running_thread() -> None:
    libc = _FakeLibc()
    with (
        patch.object(malloc_trim.Config, "MALLOC_TRIM_INTERVAL_SECONDS", 300),
        patch.object(malloc_trim, "_load_libc", return_value=libc),
    ):
        assert malloc_trim.start_malloc_trimmer() is True
        assert malloc_trim.start_malloc_trimmer() is True
    names = [t.name for t in threading.enumerate()]
    assert names.count(malloc_trim.THREAD_NAME) == 1
