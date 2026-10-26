"""Relaying a chat stream's queued events to the client as SSE.

The producer (stream_producer.py) fills the event queue; relay_events turns
it into SSE frames with keepalives, a backstop deadline and partial-content
saving on a timeout or a producer crash, and handle_generator_error is the
generator's last-resort error event (see chat_streaming.py).
"""

from __future__ import annotations

import contextlib
import json
import queue
import time
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.api.helpers.chat_streaming import StreamContext

logger = get_logger(__name__)

# Appended to partial content when an interactive chat turn hits CHAT_TIMEOUT_SECONDS.
STREAM_TIMEOUT_MARKER = "\n\n_…(response timed out)_"

# Appended to partial content when the producer crashes mid-stream (X1):
# losing the whole answer to a late crash threw away everything streamed
STREAM_ERROR_MARKER = "\n\n_…(response interrupted by an error)_"


# Agent events forwarded to the client as-is. "retry" (a transient model error
# being retried) and "stopping" (server-side Stop acknowledged) are momentary;
# "grounding_started" and the research_* events are journaled for resume
# (stream_resume.JOURNALED_EVENT_TYPES).
FORWARDED_EVENT_TYPES = (
    "thinking",
    "tool_start",
    "tool_end",
    "token",
    "retry",
    "stopping",
    "grounding_started",
    "model_fallback",
    "research_plan",
    "research_item",
    "research_finding",
    "research_sources",
    "research_writing",
    "research_tick",
    # An artifact version is ready under the reply (journaled for resume)
    "artifact",
)


def _handle_stream_timeout(context: StreamContext) -> Generator[str]:
    """Persist partial streamed content and emit a timeout event to the client.

    Populates both the generator-side (context.*) and cleanup-thread-side
    (final_results[*]) save inputs so whichever path saves keeps the partial
    text. If no content streamed yet, saves nothing (placeholder is deleted by
    generate()'s finally).
    """
    logger.warning(
        "Chat stream timed out",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "timeout_seconds": context.turn.timeout_seconds,
            "partial_chars": len(context.partial_content),
        },
    )
    if context.partial_content:
        context.clean_content = context.partial_content + STREAM_TIMEOUT_MARKER
        context.final_results["clean_content"] = context.clean_content
        context.final_results["ready"] = True

    event_data = {"type": "timeout", "message": "Response timed out before completing."}
    try:
        yield f"data: {json.dumps(event_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        context.mark_disconnected(e, "streaming (timeout)")


def relay_events(context: StreamContext) -> Generator[str]:
    """Process events from the queue and yield SSE data.

    Enforces a backstop deadline (CHAT_TIMEOUT_SECONDS + one keepalive interval of grace
    so the producer's own deadline normally fires first). The grace ensures the
    worker thread is freed and partial content saved even if the producer is
    wedged inside a single non-yielding call.
    """
    deadline = (
        time.monotonic() + context.turn.timeout_seconds + Config.SSE_KEEPALIVE_INTERVAL_SECONDS
    )
    while True:
        if time.monotonic() > deadline:
            yield from _handle_stream_timeout(context)
            break
        try:
            item = context.event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL_SECONDS)

            if item is None:
                break
            elif isinstance(item, Exception):
                yield from _handle_queue_error(context, item)
                return
            elif isinstance(item, dict):
                if item.get("type") == "timeout":
                    yield from _handle_stream_timeout(context)
                    break
                yield from relay_event(context, item)

        except queue.Empty:
            yield from _send_keepalive(context)


def _handle_queue_error(context: StreamContext, error: Exception) -> Generator[str]:
    """Handle an error from the event queue.

    Persists any partial streamed content first (X1): a crash after most of
    the answer streamed previously deleted the placeholder and lost
    everything - the timeout path already kept partials, the crash path
    did not.
    """
    if context.partial_content:
        context.clean_content = context.partial_content + STREAM_ERROR_MARKER
        context.final_results["clean_content"] = context.clean_content
        context.final_results["ready"] = True
        logger.info(
            "Stream crashed mid-answer - keeping partial content",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "partial_chars": len(context.partial_content),
            },
        )

    context.producer_failed = True
    error_data = _build_error_data(error)
    with contextlib.suppress(BrokenPipeError, ConnectionError, OSError):
        yield f"data: {json.dumps(error_data)}\n\n"


def _build_error_data(error: Exception) -> dict[str, Any]:
    """Build structured error data for SSE response."""
    error_str = str(error).lower()
    if "timeout" in error_str or "timed out" in error_str:
        return {
            "type": "error",
            "code": "TIMEOUT",
            "message": "Request timed out. Please try again.",
            "retryable": True,
        }
    if "rate limit" in error_str or "quota" in error_str:
        return {
            "type": "error",
            "code": "RATE_LIMITED",
            "message": "AI service is busy. Please try again in a moment.",
            "retryable": True,
        }
    return {
        "type": "error",
        "code": "SERVER_ERROR",
        "message": "Failed to generate response. Please try again.",
        "retryable": True,
    }


def relay_event(context: StreamContext, item: dict[str, Any]) -> Generator[str]:
    """Handle a single event from the queue."""
    event_type = item.get("type")

    if event_type == "final":
        context.clean_content = item.get("content", "")
        context.result_messages = item.get("result_messages", [])
        context.tool_results = item.get("tool_results", [])
        context.usage_info = item.get("usage_info", {})
        context.stop_reason = item.get("stop_reason")
    elif event_type == "approval_required":
        # Store approval info in context for finalization
        context.approval_info = {
            "approval_id": item.get("approval_id"),
            "description": item.get("description"),
            "tool_name": item.get("tool_name", ""),
            "sibling_results": item.get("sibling_results", []),
        }
        # Send the approval event to the client
        try:
            yield f"data: {json.dumps(item)}\n\n"
        except (BrokenPipeError, ConnectionError, OSError) as e:
            context.mark_disconnected(e, "streaming (approval_required)")
    elif event_type in FORWARDED_EVENT_TYPES:
        if event_type == "token":
            context.partial_content += item.get("text", "")
        try:
            yield f"data: {json.dumps(item)}\n\n"
        except (BrokenPipeError, ConnectionError, OSError) as e:
            context.mark_disconnected(e, f"streaming ({event_type})")


def _send_keepalive(context: StreamContext) -> Generator[str]:
    """Send a keepalive comment to prevent proxy timeout."""
    try:
        yield ": keepalive\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        context.mark_disconnected(e, "keepalive")


def handle_generator_error(context: StreamContext, error: Exception) -> Generator[str]:
    """Handle an error in the generator."""
    logger.error(
        "Error in stream generator",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "error": str(error),
        },
        exc_info=error,
    )

    # Delete placeholder if no useful content was generated AND nothing was
    # saved - a post-save exception (e.g. in done-event construction) must not
    # delete the message that was just successfully persisted
    if (
        context.placeholder_saved
        and not context.clean_content.strip()
        and not context.final_results["saved"]
    ):
        try:
            db.delete_message_by_id(context.expected_assistant_msg_id)
        except Exception:  # cleanup must not mask the original error
            logger.warning(
                "Failed to clean up placeholder message after error",
                extra={
                    "user_id": context.user_id,
                    "conversation_id": context.conv_id,
                    "message_id": context.expected_assistant_msg_id,
                },
                exc_info=True,
            )

    error_data = {
        "type": "error",
        "code": "SERVER_ERROR",
        "message": "An error occurred while generating the response. Please try again.",
        "retryable": True,
    }

    try:
        yield f"data: {json.dumps(error_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        logger.debug(
            "Client disconnected before error event",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "error": str(e),
            },
        )
