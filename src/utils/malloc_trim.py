"""Hand glibc's freed-but-kept heap pages back to the OS, periodically.

Workers allocate large short-lived buffers (page HTML, LLM payloads, TLS and
gRPC buffers). glibc keeps their memory after free, and its fragmented heap
can only shrink from the top, so a worker's PSS ratchets up to its high-water
mark. Oct 15 2026: one `malloc_trim(0)` took two 13h workers from 296/387 MB
to 246/299 MB. Each gunicorn worker runs its own trim thread (no --preload).
"""

import ctypes
import ctypes.util
import threading
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

THREAD_NAME = "malloc-trim"

# per-worker: trims this process's own heap
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_start_lock = threading.Lock()


def _load_libc() -> Any:
    return ctypes.CDLL(ctypes.util.find_library("c"))


def start_malloc_trimmer() -> bool:
    """Start the trim thread unless disabled or not on glibc; True when running."""
    global _thread
    interval = Config.MALLOC_TRIM_INTERVAL_SECONDS
    if interval <= 0:
        return False
    trim = getattr(_load_libc(), "malloc_trim", None)  # glibc only
    if trim is None:
        return False
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop_event.clear()
        _thread = threading.Thread(
            target=_trim_loop, args=(trim, interval), daemon=True, name=THREAD_NAME
        )
        _thread.start()
    return True


def stop_malloc_trimmer() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        _stop_event.set()
        _thread.join(timeout=5)
    _thread = None


def _trim_loop(trim: Any, interval: float) -> None:
    while not _stop_event.wait(timeout=interval):
        try:
            # pad 0: release every whole free page, not only the heap top
            trim(0)
        except Exception:  # a failed trim must never take the worker down
            logger.exception("malloc_trim failed")
