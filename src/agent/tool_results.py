"""Tool result capture and management for the chat agent.

This module handles capturing full tool results (before stripping large data like images)
and provides cleanup mechanisms to prevent memory leaks.
"""

import atexit
import contextvars
import threading
import time
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ============ Request ID Context ============

# Contextvar to hold the current request ID for tool result capture
# This allows us to capture full results per-request without passing request_id through the graph
_current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_request_id", default=None
)


def set_current_request_id(request_id: str | None) -> None:
    """Set the current request ID for tool result capture."""
    _current_request_id.set(request_id)
    # Start cleanup thread when we start capturing results
    if request_id is not None:
        _start_cleanup_thread()


def get_current_request_id() -> str | None:
    """Get the current request ID from context."""
    return _current_request_id.get()


# ============ Full Tool Results Storage ============

# Global storage for full tool results before stripping (keyed by thread/request)
# This allows us to capture the full results for server-side extraction while
# still stripping them before sending to the LLM
# Format: {request_id: {"results": [...], "created_at": timestamp}}
_full_tool_results: dict[str, dict[str, Any]] = {}
_full_tool_results_lock = threading.Lock()


def store_tool_result(request_id: str, content: str) -> None:
    """Store a tool result for later retrieval.

    Args:
        request_id: The request ID to associate with this result
        content: The full tool result content (before stripping)
    """
    with _full_tool_results_lock:
        if request_id not in _full_tool_results:
            _full_tool_results[request_id] = {
                "results": [],
                "created_at": time.time(),
            }
        _full_tool_results[request_id]["results"].append({"type": "tool", "content": content})


def get_full_tool_results(request_id: str) -> list[dict[str, Any]]:
    """Get and clear full tool results for a request.

    Args:
        request_id: The request ID to retrieve results for

    Returns:
        List of tool result dicts, or empty list if none found
    """
    with _full_tool_results_lock:
        entry = _full_tool_results.pop(request_id, None)
        if entry is not None:
            results: list[dict[str, Any]] = entry.get("results", [])
            return results
        return []


# ============ Cleanup Thread ============

# Cleanup thread state
_cleanup_thread: threading.Thread | None = None
_cleanup_thread_stop_event = threading.Event()


def _cleanup_stale_tool_results() -> None:
    """Background thread that periodically cleans up stale tool results.

    Runs every TOOL_RESULTS_CLEANUP_INTERVAL_SECONDS and removes entries older than
    TOOL_RESULTS_TTL_SECONDS. This prevents memory leaks when get_full_tool_results()
    is not called (e.g., error paths, client disconnects before completion).
    """
    while not _cleanup_thread_stop_event.is_set():
        # Wait for cleanup interval or until stop event is set
        if _cleanup_thread_stop_event.wait(timeout=Config.TOOL_RESULTS_CLEANUP_INTERVAL_SECONDS):
            # Stop event was set, exit
            break

        current_time = time.time()
        stale_keys: list[str] = []

        with _full_tool_results_lock:
            for request_id, entry in _full_tool_results.items():
                created_at = entry.get("created_at", 0)
                if current_time - created_at > Config.TOOL_RESULTS_TTL_SECONDS:
                    stale_keys.append(request_id)

            if stale_keys:
                for key in stale_keys:
                    del _full_tool_results[key]
                logger.debug(
                    "Cleaned up stale tool results",
                    extra={"count": len(stale_keys), "remaining": len(_full_tool_results)},
                )


def _start_cleanup_thread() -> None:
    """Start the background cleanup thread if not already running."""
    global _cleanup_thread
    if _cleanup_thread is None or not _cleanup_thread.is_alive():
        _cleanup_thread_stop_event.clear()
        _cleanup_thread = threading.Thread(
            target=_cleanup_stale_tool_results,
            daemon=True,
            name="tool-results-cleanup",
        )
        _cleanup_thread.start()
        logger.debug("Started tool results cleanup thread")


def _stop_cleanup_thread() -> None:
    """Stop the background cleanup thread gracefully."""
    global _cleanup_thread
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        _cleanup_thread_stop_event.set()
        _cleanup_thread.join(timeout=5)
        # Note: We don't log here because during Python shutdown (atexit),
        # logging streams may already be closed, causing "I/O operation on
        # closed file" errors that can't be caught (logging handles them internally)


# Register cleanup on module exit
atexit.register(_stop_cleanup_thread)
