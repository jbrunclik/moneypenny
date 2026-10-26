"""Consumer side of a chat stream: the SSE generator the client reads.

create_stream_generator() starts the producer (stream_producer.py), relays
queued events as SSE with keepalives, and finalizes the turn
(stream_finalize.py).
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from src.api.helpers.chat_save import save_message_to_db
from src.api.helpers.stream_consumer import handle_generator_error, relay_events
from src.api.helpers.stream_finalize import finalize_stream
from src.api.helpers.stream_producer import cleanup_and_save, stream_events
from src.db.models import db
from src.enums import MessageRole
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.api.helpers.chat_turn import PreparedTurn, TurnContext
    from src.db.models import Conversation, Message, User

logger = get_logger(__name__)

# ============================================================================
# Stream Generator Creation
# ============================================================================


def create_stream_generator(user: User, turn: PreparedTurn, ctx: TurnContext) -> Generator[str]:
    """Create the SSE stream generator for chat streaming.

    The generator sets up the turn's context, starts the producer and cleanup
    threads, relays events to the client and saves the message.
    """

    def generate() -> Generator[str]:
        """Generator that streams tokens as SSE events with keepalive support."""
        # Initialize context
        context = StreamContext(user=user, conv=turn.conv, user_msg=turn.user_msg, turn=ctx)
        ctx.apply()

        # Start background threads
        context.start_threads()

        # Send initial user_message_saved event
        yield from _yield_user_message_saved(context)

        # Process events from queue
        try:
            yield from relay_events(context)

            # Save message and send done event - unless the model failed
            # before any text: that saved an EMPTY reply (the client already
            # got the error), the chat ended on it and Regenerate was refused.
            # A failure with partial text is "ready" and is kept.
            if not (context.producer_failed and not context.final_results["ready"]):
                yield from finalize_stream(context)

        except Exception as e:  # noqa: BLE001 - reaches the client as an error event; logged there
            yield from handle_generator_error(context, e)

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
            # A producer that reported a failure is finishing its own cleanup
            # (token, stop flags, journal) - still alive for a moment, which
            # kept the empty placeholder: the chat then ended on an empty
            # assistant row and Regenerate was refused
            if context.producer_failed and context.stream_thread is not None:
                context.stream_thread.join(timeout=_PRODUCER_EXIT_WAIT_SECONDS)
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


# How long the stream waits for a failed producer thread to exit
_PRODUCER_EXIT_WAIT_SECONDS = 2.0


class StreamContext:
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
        # The producer thread reported an exception (it exits right after)
        self.producer_failed = False

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
        self.event_queue: queue.Queue[dict[str, Any] | Exception | None] = queue.Queue()
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
                "Client disconnected",
                extra={
                    "context": context,
                    "user_id": self.user_id,
                    "conversation_id": self.conv_id,
                    "error": str(error),
                },
            )
            self.client_connected = False


def _yield_user_message_saved(context: StreamContext) -> Generator[str]:
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
    except Exception:  # the final save falls back to INSERT-at-end
        logger.warning(
            "Failed to save placeholder message, falling back to INSERT-at-end",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "message_id": context.expected_assistant_msg_id,
            },
            exc_info=True,
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
