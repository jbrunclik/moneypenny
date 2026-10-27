"""Opt-in tracemalloc profiling of a long-lived worker.

With MEMORY_PROFILE_ENABLED each gunicorn worker traces allocations from
startup; `kill -USR2 <worker pid>` writes a snapshot and logs traced bytes
next to the worker's PSS. Diff two snapshots of the same worker with
`scripts/memory_profile_diff.py`. If PSS grows much faster than the traced
total, the growth is outside the Python allocator (C extensions,
fragmentation) and tracemalloc will not show it.
"""

import os
import signal
import threading
import tracemalloc
from pathlib import Path
from types import FrameType

from src.config import Config
from src.utils.clock import to_local, utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

SMAPS_ROLLUP_PATH = Path("/proc/self/smaps_rollup")
SNAPSHOT_SUFFIX = ".tracemalloc"


def install_memory_profiler() -> bool:
    """Start tracing and bind SIGUSR2 to a snapshot dump; True when installed.

    Must run in the worker's main thread (signal handlers can only be set
    there) and after gunicorn's init_signals, which resets SIGUSR2 - the app
    factory runs after it.
    """
    if not Config.MEMORY_PROFILE_ENABLED:
        return False
    if threading.current_thread() is not threading.main_thread():
        logger.warning("Memory profiler not installed: not in the main thread")
        return False
    tracemalloc.start(Config.MEMORY_PROFILE_FRAMES)
    signal.signal(signal.SIGUSR2, _handle_dump_signal)
    logger.info(
        "Memory profiler installed",
        extra={"pid": os.getpid(), "frames": Config.MEMORY_PROFILE_FRAMES},
    )
    return True


def _handle_dump_signal(_signum: int, _frame: FrameType | None) -> None:
    try:
        write_snapshot(Config.MEMORY_PROFILE_DIR)
    except Exception:  # a failed dump must never take the worker down
        logger.exception("Memory snapshot failed")


def write_snapshot(directory: Path) -> Path:
    """Dump the current tracemalloc snapshot to `<pid>-<timestamp>.tracemalloc`.

    Snapshots are pickles (loading one runs its code), so the directory and
    files are private to the service user: nobody else can plant one.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)  # also tightens a directory that already existed
    stamp = to_local(utc_now()).strftime("%Y%m%d-%H%M%S")
    path = directory / f"{os.getpid()}-{stamp}{SNAPSHOT_SUFFIX}"
    tracemalloc.take_snapshot().dump(str(path))
    path.chmod(0o600)
    traced_bytes, peak_bytes = tracemalloc.get_traced_memory()
    logger.info(
        "Memory snapshot written",
        extra={
            "path": str(path),
            "pid": os.getpid(),
            "traced_bytes": traced_bytes,
            "traced_peak_bytes": peak_bytes,
            "pss_bytes": read_pss_bytes(),
        },
    )
    return path


def read_pss_bytes(rollup: Path = SMAPS_ROLLUP_PATH) -> int | None:
    """This process's proportional set size, or None where /proc is absent."""
    try:
        for line in rollup.read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def top_growth(old: Path, new: Path, *, group_by: str, limit: int) -> list[str]:
    """The `limit` largest allocation increases from `old` to `new`, formatted."""
    stats = tracemalloc.Snapshot.load(str(new)).compare_to(
        tracemalloc.Snapshot.load(str(old)), group_by
    )
    lines: list[str] = []
    for stat in stats[:limit]:
        lines.append(
            f"{stat.size_diff / 1024:+10.1f} KiB {stat.count_diff:+8d} blocks"
            f"  (now {stat.size / 1024:.1f} KiB)"
        )
        lines.extend(f"    {frame}" for frame in stat.traceback.format())
    return lines
