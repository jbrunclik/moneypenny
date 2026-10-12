"""Unit tests for the opt-in tracemalloc worker profiler."""

import signal
import tracemalloc
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils import memory_profile


@pytest.fixture(autouse=True)
def _restore_profiler_state() -> Generator[None]:
    """Each test starts untraced and leaves SIGUSR2 as it found it."""
    previous = signal.getsignal(signal.SIGUSR2)
    tracemalloc.stop()
    yield
    tracemalloc.stop()
    signal.signal(signal.SIGUSR2, previous)


def test_disabled_profiler_installs_nothing() -> None:
    previous = signal.getsignal(signal.SIGUSR2)
    with patch.object(memory_profile.Config, "MEMORY_PROFILE_ENABLED", False):
        assert memory_profile.install_memory_profiler() is False
    assert tracemalloc.is_tracing() is False
    assert signal.getsignal(signal.SIGUSR2) is previous


def test_enabled_profiler_traces_and_dumps_on_sigusr2(tmp_path: Path) -> None:
    with (
        patch.object(memory_profile.Config, "MEMORY_PROFILE_ENABLED", True),
        patch.object(memory_profile.Config, "MEMORY_PROFILE_FRAMES", 3),
        patch.object(memory_profile.Config, "MEMORY_PROFILE_DIR", tmp_path),
    ):
        assert memory_profile.install_memory_profiler() is True
        assert tracemalloc.is_tracing() is True
        assert tracemalloc.get_traceback_limit() == 3
        handler = signal.getsignal(signal.SIGUSR2)
        assert callable(handler)
        handler(signal.SIGUSR2, None)

    dumps = list(tmp_path.glob("*.tracemalloc"))
    assert len(dumps) == 1
    assert tracemalloc.Snapshot.load(str(dumps[0])).traces


def test_snapshot_file_is_named_by_worker_pid(tmp_path: Path) -> None:
    tracemalloc.start()
    path = memory_profile.write_snapshot(tmp_path / "nested")
    assert path.parent == tmp_path / "nested"
    assert path.name.startswith(f"{memory_profile.os.getpid()}-")


def test_top_growth_reports_memory_allocated_between_snapshots(tmp_path: Path) -> None:
    tracemalloc.start()
    old = memory_profile.write_snapshot(tmp_path)
    kept = [bytes(1024) for _ in range(2000)]  # ~2 MB that the diff must surface
    new = memory_profile.write_snapshot(tmp_path)

    lines = memory_profile.top_growth(old, new, group_by="lineno", limit=5)

    assert any("test_memory_profile.py" in line for line in lines)
    assert kept


def test_pss_is_read_from_smaps_rollup(tmp_path: Path) -> None:
    rollup = tmp_path / "smaps_rollup"
    rollup.write_text("Rss:              500000 kB\nPss:              437323 kB\n")
    assert memory_profile.read_pss_bytes(rollup) == 437323 * 1024


def test_pss_is_none_without_proc(tmp_path: Path) -> None:
    assert memory_profile.read_pss_bytes(tmp_path / "missing") is None
