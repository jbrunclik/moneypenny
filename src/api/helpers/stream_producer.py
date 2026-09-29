"""Producer side of a chat stream: the agent thread and the cleanup thread.

stream_events() runs the agent in a background thread and feeds its events
into a queue (journaling them for resume); cleanup_and_save() saves the turn
when the client-facing generator could not (client disconnected).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.agent.tools.request_approval import (
    ApprovalRequestedException,
    build_approval_message,
)
from src.api.helpers.stream_resume import _JOURNALED_EVENT_TYPES, _StreamJournal
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.push import send_push_to_user

if TYPE_CHECKING:
    from src.agent.agent import ChatAgent
    from src.api.helpers.chat_save import SaveResult
    from src.api.helpers.chat_turn import TurnContext

logger = get_logger(__name__)


def _notify_response_ready(user_id: str, conv_id: str, content: str) -> None:
    """Web-push "answer ready" for a finished turn no connected client saw.

    Fire-and-forget (no-op without VAPID keys). The service worker
    suppresses the notification when a focused window is already viewing
    the conversation, so a quick foreground+resume doesn't also show a
    stray banner.
    """
    # Agent conversations share the executor's tag so an agent-finished
    # push and a turn-finished push about the same agent replace each
    # other instead of stacking as two notifications
    tag = f"turn-{conv_id}"
    try:
        conv = db.get_conversation(conv_id, user_id)
        if conv and conv.agent_id:
            tag = f"agent-{conv.agent_id}"
    except Exception:  # noqa: BLE001 - tag fallback must never block the push
        logger.debug("Conversation lookup for push tag failed", exc_info=True)

    body = content.strip().split("\n", 1)[0][:160] or "Open the app to view it."
    send_push_to_user(
        user_id,
        "Your answer is ready",
        body,
        url=f"/#/conversations/{conv_id}",
        tag=tag,
    )


def _close_thread_db_connections() -> None:
    """Close DB pool connections for the current thread.

    Called when a short-lived background thread is about to exit so the
    ConnectionPool doesn't keep a reference to the connection forever.
    """
    try:
        db._pool.close_thread_connection()
    except Exception:
        logger.debug("Closing thread-local db connection failed", exc_info=True)
    try:
        from src.db.blob_store import get_blob_store

        get_blob_store()._pool.close_thread_connection()
    except Exception:
        logger.debug("Closing thread-local blob connection failed", exc_info=True)


def stream_events(
    agent: ChatAgent,
    event_queue: queue.Queue[dict[str, Any] | None | Exception],
    final_results: dict[str, Any],
    turn: TurnContext,
    journal_message_id: str | None = None,
) -> None:
    """Background thread that streams events into the queue.

    Args:
        agent: ChatAgent instance
        event_queue: Queue to push events into
        final_results: Shared dict to store final results
        turn: The turn's inputs and context
        journal_message_id: Assistant message id for the resumable-stream
            journal (None disables journaling)
    """
    user_id, conv_id = turn.user_id, turn.conv_id
    journal: _StreamJournal | None = None
    if journal_message_id and Config.STREAM_JOURNAL_ENABLED:
        journal = _StreamJournal(journal_message_id)
    # Contextvars don't cross threads: re-set the turn's (agent context for
    # kv_store and permission checks, request id for tool results, ...)
    turn.apply()
    try:
        logger.debug(
            "Stream thread started", extra={"user_id": user_id, "conversation_id": conv_id}
        )
        event_count = 0
        deadline = time.monotonic() + Config.CHAT_TIMEOUT
        timed_out = False
        gen = agent.stream_chat_events(**turn.agent_call_kwargs())
        try:
            for event in gen:
                event_count += 1
                if event.get("type") == "final":
                    # Store final results for cleanup thread
                    final_results["clean_content"] = event.get("content", "")
                    final_results["result_messages"] = event.get("result_messages", [])
                    final_results["tool_results"] = event.get("tool_results", [])
                    final_results["usage_info"] = event.get("usage_info", {})
                    final_results["ready"] = True
                if journal and event.get("type") in _JOURNALED_EVENT_TYPES:
                    journal.record(event)
                event_queue.put(event)
                if not final_results["ready"] and time.monotonic() > deadline:
                    timed_out = True
                    logger.warning(
                        "Chat stream exceeded CHAT_TIMEOUT; stopping agent",
                        extra={
                            "user_id": user_id,
                            "conversation_id": conv_id,
                            "timeout_seconds": Config.CHAT_TIMEOUT,
                            "event_count": event_count,
                        },
                    )
                    break
        finally:
            # Cooperatively stop the agent generator (raises GeneratorExit at its
            # current yield point). Idempotent / safe after normal exhaustion.
            gen.close()

        if timed_out:
            timeout_event: dict[str, Any] = {"type": "timeout"}
            if journal:
                journal.record(timeout_event)
            event_queue.put(timeout_event)

        logger.debug(
            "Stream thread completed",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "event_count": event_count,
            },
        )

        event_queue.put(None)  # Signal completion
    except ApprovalRequestedException as e:
        # Special handling for approval requests - send approval event instead of error
        logger.info(
            "Stream thread: approval requested",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "approval_id": e.approval_id,
                "description": e.description,
            },
        )
        approval_event: dict[str, Any] = {
            "type": "approval_required",
            "approval_id": e.approval_id,
            "description": e.description,
            "tool_name": e.tool_name,
            # (tool_name, result) pairs from batch siblings that executed
            # before the pause - recorded in the approval message (R3)
            "sibling_results": e.sibling_results,
        }
        # Persist the approval message HERE (producer thread): if the client
        # disconnects before the consumer processes this event, the consumer's
        # finally would otherwise delete the unused placeholder and the
        # approval message would never reach the conversation. The consumer's
        # _finalize_approval_stream re-writes the same content (idempotent).
        if journal_message_id:
            try:
                approval_message = build_approval_message(
                    e.approval_id, e.description, e.tool_name, sibling_results=e.sibling_results
                )
                if db.update_message_content(journal_message_id, approval_message):
                    final_results["saved"] = True
            except Exception:
                logger.warning("Producer-side approval save failed", exc_info=True)
        if journal:
            journal.record(approval_event)
        event_queue.put(approval_event)
        # Approval is terminal for this stream: signal completion so the
        # consumer finalizes promptly instead of sending keepalives until the
        # backstop deadline (~CHAT_TIMEOUT later) and emitting a bogus timeout.
        event_queue.put(None)
    except Exception as e:
        logger.error(
            "Stream thread error",
            extra={"user_id": user_id, "conversation_id": conv_id, "error": str(e)},
            exc_info=True,
        )
        event_queue.put(e)  # Signal error
    except BaseException as e:
        # SystemExit & co. (e.g. interpreter/worker shutdown) must still
        # signal the consumer - otherwise it idles until the backstop
        # deadline and any partial content is lost with it (X1)
        logger.error(
            "Stream thread killed",
            extra={"user_id": user_id, "conversation_id": conv_id, "error": repr(e)},
        )
        event_queue.put(RuntimeError(f"stream producer killed: {e!r}"))
        raise
    finally:
        if journal:
            journal.finish()
        # Close thread-local DB connections so the pool doesn't leak them
        _close_thread_db_connections()


def cleanup_and_save(
    stream_thread: threading.Thread,
    final_results: dict[str, Any],
    save_lock: threading.Lock,
    generator_done_event: threading.Event,
    conv_id: str,
    user_id: str,
    save_func: Callable[[], SaveResult | None],
) -> None:
    """Wait for stream thread to complete, then save message if generator stopped early.

    This is a fallback mechanism - the generator path is preferred because it can
    send the done event to the client. The cleanup thread only saves if the generator
    didn't (e.g., because the client disconnected before the generator could save).

    The cleanup thread waits for the generator to signal completion via an Event.
    This ensures the generator always has priority over the cleanup thread.

    Args:
        stream_thread: Threading thread to wait for
        final_results: Shared dict with final results (includes "ready" and "saved" flags)
        save_lock: Lock to prevent race condition with generator's save
        generator_done_event: Event that generator sets when done with save attempt
        conv_id: Conversation ID
        user_id: User ID
        save_func: Function to call to save the message (no args, uses final_results)
    """
    try:
        # Wait for stream thread to complete (with timeout to prevent hanging forever)
        stream_thread.join(timeout=Config.STREAM_CLEANUP_THREAD_TIMEOUT)
        if stream_thread.is_alive():
            logger.error(
                "Stream thread did not complete within timeout",
                extra={"user_id": user_id, "conversation_id": conv_id},
            )
            return

        # Wait for generator to signal it's done with its save attempt
        # This gives the generator priority - it can send the done event to the client
        # Timeout ensures we still save if generator gets stuck or client disconnects early
        generator_finished = generator_done_event.wait(timeout=Config.STREAM_CLEANUP_WAIT_DELAY)

        # Use lock to prevent race condition with generator's save
        # NOTE: We must check saved status even if generator_finished is True, because
        # GeneratorExit (raised when client disconnects) can kill the generator before
        # it reaches _finalize_stream. The finally block sets generator_done_event, but
        # the save never happened. This commonly occurs on mobile when the screen locks.
        with save_lock:
            # Only save if:
            # 1. Final results are ready (stream completed successfully)
            # 2. Message hasn't been saved yet (generator didn't save)
            if final_results["ready"] and not final_results["saved"]:
                if generator_finished:
                    logger.info(
                        "Generator exited without saving (likely GeneratorExit from client disconnect), "
                        "saving message in cleanup thread",
                        extra={"user_id": user_id, "conversation_id": conv_id},
                    )
                else:
                    logger.info(
                        "Generator stopped early (client disconnected), saving message in cleanup thread",
                        extra={"user_id": user_id, "conversation_id": conv_id},
                    )
                # Save the message and mark as saved
                save_func()
                final_results["saved"] = True
                # The turn finished but no client was connected to see it
                # (typically mobile screen lock) - nudge the user's devices
                _notify_response_ready(
                    user_id, conv_id, str(final_results.get("clean_content") or "")
                )
            elif generator_finished:
                logger.debug(
                    "Generator completed, cleanup thread not needed",
                    extra={
                        "user_id": user_id,
                        "conversation_id": conv_id,
                        "ready": final_results["ready"],
                        "saved": final_results["saved"],
                    },
                )
    except Exception as e:
        logger.error(
            "Error in cleanup thread",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "error": str(e),
            },
            exc_info=True,
        )
    finally:
        # Close thread-local DB connections so the pool doesn't leak them
        _close_thread_db_connections()
