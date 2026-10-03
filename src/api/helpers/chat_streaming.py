"""Consumer side of a chat stream: the SSE generator the client reads.

create_stream_generator() starts the producer (stream_producer.py), relays
queued events as SSE with keepalives, and finalizes the turn
(stream_finalize.py).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from src.api.helpers.chat_save import save_message_to_db
from src.api.helpers.stream_finalize import _finalize_stream
from src.api.helpers.stream_producer import cleanup_and_save, stream_events
from src.api.schemas.common import MessageRole
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.api.helpers.chat_turn import PreparedTurn, TurnContext
    from src.db.models import Conversation, Message, User

logger = get_logger(__name__)

# Appended to partial content when an interactive chat turn hits CHAT_TIMEOUT.
STREAM_TIMEOUT_MARKER = "\n\n_…(response timed out)_"

# Appended to partial content when the producer crashes mid-stream (X1):
# losing the whole answer to a late crash threw away everything streamed
STREAM_ERROR_MARKER = "\n\n_…(response interrupted by an error)_"


# ============================================================================
# Stream Generator Creation
# ============================================================================


# Agent events forwarded to the client as-is. "retry" (a transient model error
# being retried) and "stopping" (server-side Stop acknowledged) are momentary;
# "grounding_started" and the research_* events are journaled for resume
# (stream_resume._JOURNALED_EVENT_TYPES).
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
)


def create_stream_generator(user: User, turn: PreparedTurn, ctx: TurnContext) -> Generator[str]:
    """Create the SSE stream generator for chat streaming.

    The generator sets up the turn's context, starts the producer and cleanup
    threads, relays events to the client and saves the message.
    """

    def generate() -> Generator[str]:
        """Generator that streams tokens as SSE events with keepalive support."""
        # Initialize context
        context = _StreamContext(user=user, conv=turn.conv, user_msg=turn.user_msg, turn=ctx)
        ctx.apply()

        # Start background threads
        context.start_threads()

        # Send initial user_message_saved event
        yield from _yield_user_message_saved(context)

        # Process events from queue
        try:
            yield from _process_event_queue(context)

            # Save message and send done event
            yield from _finalize_stream(context)

        except Exception as e:
            yield from _handle_generator_error(context, e)

        finally:
            ctx.clear()
            # Delete placeholder ONLY if the turn truly died: producer thread
            # finished without results. While the producer is still generating
            # (client disconnect mid-stream), the placeholder must survive so
            # the cleanup thread saves into the SAME id - that id is what the
            # resume endpoint and poll recovery look up. Deleting it here made
            # the cleanup save fall back to an INSERT under a NEW id, which
            # stranded every recovery keyed to the original one (X1).
            # The approval path never sets "ready" - its save happens in
            # _finalize_approval_stream / the producer, so it is excluded too.
            if (
                context.placeholder_saved
                and not context.final_results["ready"]
                and not context.final_results["saved"]
                and context.approval_info is None
                and (context.stream_thread is None or not context.stream_thread.is_alive())
            ):
                try:
                    db.delete_message_by_id(context.expected_assistant_msg_id)
                except Exception:
                    logger.warning(
                        "Failed to delete unused placeholder message",
                        extra={"message_id": context.expected_assistant_msg_id},
                        exc_info=True,
                    )
            # Signal that generator is done with its save attempt
            # This allows cleanup thread to proceed (or skip if we already saved)
            context.generator_done_event.set()

    return generate()


class _StreamContext:
    """Encapsulates all state for a streaming request."""

    def __init__(
        self, user: User, conv: Conversation, user_msg: Message, turn: TurnContext
    ) -> None:
        self.user = user
        self.conv = conv
        self.user_msg = user_msg
        self.turn = turn
        self.message_text = turn.message_text
        self.stream_request_id = turn.request_id

        # Derived values
        self.conv_id = conv.id
        self.user_id = user.id

        # State
        self.clean_content = ""
        # Streamed token text accumulated for partial-save on timeout.
        self.partial_content = ""
        self.result_messages: list[Any] = []
        self.tool_results: list[dict[str, Any]] = []
        self.usage_info: dict[str, Any] = {}
        # "user" when the turn was stopped server-side (partial reply kept)
        self.stop_reason: str | None = None
        self.client_connected = True

        # Pre-generate assistant message ID for streaming recovery
        # This allows the frontend to fetch the specific message if the stream fails
        self.expected_assistant_msg_id = str(uuid.uuid4())

        # Whether a placeholder message was saved to DB at stream start
        self.placeholder_saved: bool = False

        # Threading
        self.event_queue: queue.Queue[dict[str, Any] | None | Exception] = queue.Queue()
        # final_results is shared between generator and cleanup thread:
        # - "ready": True when stream completed and results are available
        # - "saved": True when message has been saved (prevents duplicate saves)
        self.final_results: dict[str, Any] = {"ready": False, "saved": False, "stop_reason": None}
        # Lock to prevent race condition between generator and cleanup thread saves
        self.save_lock = threading.Lock()
        # Event that generator sets when it has finished its save attempt (or decided not to save)
        # Cleanup thread waits on this to give generator priority
        self.generator_done_event = threading.Event()
        self.stream_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        # Approval request info (set when ApprovalRequestedException is caught)
        self.approval_info: dict[str, Any] | None = None

    def start_threads(self) -> None:
        """Start the streaming and cleanup background threads."""
        self.stream_thread = threading.Thread(
            target=stream_events,
            args=(
                self.turn.create_agent(include_thoughts=True),
                self.event_queue,
                self.final_results,
                self.turn,
            ),
            kwargs={"journal_message_id": self.expected_assistant_msg_id},
            daemon=False,
        )
        self.stream_thread.start()

        self.cleanup_thread = threading.Thread(
            target=cleanup_and_save,
            args=(
                self.stream_thread,
                self.final_results,
                self.save_lock,
                self.generator_done_event,
                self.conv_id,
                self.user_id,
                lambda: save_message_to_db(
                    self.final_results["clean_content"],
                    self.final_results["result_messages"],
                    self.final_results["tool_results"],
                    self.final_results["usage_info"],
                    self.conv_id,
                    self.user_id,
                    self.conv.model,
                    self.message_text,
                    self.stream_request_id,
                    self.client_connected,
                    self.expected_assistant_msg_id,
                    stop_reason=self.final_results.get("stop_reason"),
                ),
            ),
            daemon=True,
        )
        self.cleanup_thread.start()

    def mark_disconnected(self, error: Exception, context: str) -> None:
        """Mark the client as disconnected and log the event."""
        if self.client_connected:
            logger.warning(
                f"Client disconnected during {context}",
                extra={
                    "user_id": self.user_id,
                    "conversation_id": self.conv_id,
                    "error": str(error),
                },
            )
            self.client_connected = False


def _yield_user_message_saved(context: _StreamContext) -> Generator[str]:
    """Yield the user_message_saved event.

    Saves an empty placeholder assistant message to DB first so that
    GET /api/messages/{id} returns 200 during stream recovery (instead of 404).
    Then includes the expected assistant message ID so the frontend can recover
    the message if the stream fails (e.g., connection drops mid-stream).
    """
    # Save empty placeholder so GET /api/messages/{id} returns 200 during recovery
    try:
        db.add_message(
            context.conv_id,
            MessageRole.ASSISTANT,
            "",
            message_id=context.expected_assistant_msg_id,
        )
        context.placeholder_saved = True
    except Exception:
        logger.warning(
            "Failed to save placeholder message, falling back to INSERT-at-end",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "message_id": context.expected_assistant_msg_id,
            },
        )

    try:
        event_data = {
            "type": "user_message_saved",
            "user_message_id": context.user_msg.id,
            "expected_assistant_message_id": context.expected_assistant_msg_id,
        }
        yield f"data: {json.dumps(event_data)}\n\n"
    except BrokenPipeError, ConnectionError, OSError:
        pass


def _handle_stream_timeout(context: _StreamContext) -> Generator[str]:
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


def _process_event_queue(context: _StreamContext) -> Generator[str]:
    """Process events from the queue and yield SSE data.

    Enforces a backstop deadline (CHAT_TIMEOUT + one keepalive interval of grace
    so the producer's own deadline normally fires first). The grace ensures the
    worker thread is freed and partial content saved even if the producer is
    wedged inside a single non-yielding call.
    """
    deadline = time.monotonic() + context.turn.timeout_seconds + Config.SSE_KEEPALIVE_INTERVAL
    while True:
        if time.monotonic() > deadline:
            yield from _handle_stream_timeout(context)
            break
        try:
            item = context.event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL)

            if item is None:
                break
            elif isinstance(item, Exception):
                yield from _handle_queue_error(context, item)
                return
            elif isinstance(item, dict):
                if item.get("type") == "timeout":
                    yield from _handle_stream_timeout(context)
                    break
                yield from _handle_queue_event(context, item)

        except queue.Empty:
            yield from _send_keepalive(context)


def _handle_queue_error(context: _StreamContext, error: Exception) -> Generator[str]:
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

    error_data = _build_error_data(error)
    try:
        yield f"data: {json.dumps(error_data)}\n\n"
    except BrokenPipeError, ConnectionError, OSError:
        pass


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
    elif "rate limit" in error_str or "quota" in error_str:
        return {
            "type": "error",
            "code": "RATE_LIMITED",
            "message": "AI service is busy. Please try again in a moment.",
            "retryable": True,
        }
    else:
        return {
            "type": "error",
            "code": "SERVER_ERROR",
            "message": "Failed to generate response. Please try again.",
            "retryable": True,
        }


def _handle_queue_event(context: _StreamContext, item: dict[str, Any]) -> Generator[str]:
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


def _send_keepalive(context: _StreamContext) -> Generator[str]:
    """Send a keepalive comment to prevent proxy timeout."""
    try:
        yield ": keepalive\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        context.mark_disconnected(e, "keepalive")


def _handle_generator_error(context: _StreamContext, error: Exception) -> Generator[str]:
    """Handle an error in the generator."""
    logger.error(
        "Error in stream generator",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "error": str(error),
        },
        exc_info=True,
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
        except Exception:
            logger.warning(
                "Failed to clean up placeholder message after error",
                extra={
                    "user_id": context.user_id,
                    "conversation_id": context.conv_id,
                    "message_id": context.expected_assistant_msg_id,
                },
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
