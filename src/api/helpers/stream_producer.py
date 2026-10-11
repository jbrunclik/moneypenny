"""Producer side of a chat stream: the agent thread and the cleanup thread.

stream_events() runs the agent in a background thread and feeds its events
into a queue (journaling them for resume); cleanup_and_save() saves the turn
when the client-facing generator could not (client disconnected).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from src.agent.cancellation import (
    CancelToken,
    clear_finish_request,
    clear_stop_request,
    finish_now_requested,
    register_token,
    run_poller,
    stop_requested,
    unregister_token,
)
from src.agent.deep_research.briefs import recent_turns_text
from src.agent.deep_research.pipeline import run_deep_research
from src.agent.interjection import clear_interjection, pop_interjection
from src.agent.tools.request_approval import (
    ApprovalRequestedException,
    build_approval_message,
)
from src.api.helpers.stream_resume import _JOURNALED_EVENT_TYPES, _StreamJournal
from src.api.helpers.turn_steering import defer_unanswered_steering
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.push import send_push_to_user

if TYPE_CHECKING:
    from src.agent.agent import ChatAgent
    from src.api.helpers.chat_save import SaveResult
    from src.api.helpers.chat_turn import TurnContext

logger = get_logger(__name__)


def _notify_response_ready(
    user_id: str, conv_id: str, content: str, title: str = "Your answer is ready"
) -> None:
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
        title,
        body,
        url=f"/#/conversations/{conv_id}",
        tag=tag,
    )


def push_title(usage_info: dict[str, Any]) -> str:
    """The push title: a report, a run that found nothing, or a chat answer."""
    if usage_info.get("research_failed"):
        return "Your research could not finish"
    return "Your research is ready" if usage_info.get("research_run") else "Your answer is ready"


def _turn_events(agent: ChatAgent, turn: TurnContext, stop_key: str) -> Generator[dict[str, Any]]:
    """The agent's events, or a deep-research run's for a turn that starts one."""
    plan = turn.deep_research
    if plan is None:
        return agent.stream_chat_events(**turn.agent_call_kwargs())
    user_id, conv_id = turn.user_id, turn.conv_id
    return run_deep_research(
        plan,
        recent_turns_text(turn.history),
        turn.request_id,
        finish_requested=lambda: finish_now_requested(user_id, conv_id, stop_key),
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


def _poll_stop_flag(
    token: CancelToken, user_id: str, conv_id: str, message_id: str, done: threading.Event
) -> None:
    """Poller thread: cancel the turn's token once POST /chat/stop named this turn."""
    try:
        run_poller(
            token,
            lambda: stop_requested(user_id, conv_id, message_id),
            done,
            Config.CANCEL_POLL_INTERVAL_SECONDS,
        )
    finally:
        _close_thread_db_connections()


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
    # Server-side Stop: a token for this request, flipped by a poller when
    # the stop route's kv flag appears (the route may run on another worker)
    stop_key = journal_message_id or turn.request_id  # the turn's assistant message id
    turn_done = threading.Event()
    try:
        token = register_token(turn.request_id)

        # Tell the client at once that the Stop landed: no events flow while
        # a tool runs, and its grace abort must not fire during long tools.
        # Journaled too, so a reader resumed after a reload learns it as well
        def _ack_stop() -> None:
            event: dict[str, Any] = {"type": "stopping"}
            if journal:
                journal.record(event)
            event_queue.put(event)

        token.add_callback(_ack_stop)
        threading.Thread(
            target=_poll_stop_flag,
            args=(token, user_id, conv_id, stop_key, turn_done),
            daemon=True,
            name="stop-poller",
        ).start()
        logger.debug(
            "Stream thread started", extra={"user_id": user_id, "conversation_id": conv_id}
        )
        event_count = 0
        deadline = time.monotonic() + turn.timeout_seconds
        timed_out = False
        gen = _turn_events(agent, turn, stop_key)
        try:
            for event in gen:
                event_count += 1
                if event.get("type") == "final":
                    # Store final results for cleanup thread
                    final_results["clean_content"] = event.get("content", "")
                    final_results["result_messages"] = event.get("result_messages", [])
                    final_results["tool_results"] = event.get("tool_results", [])
                    final_results["usage_info"] = event.get("usage_info", {})
                    final_results["stop_reason"] = event.get("stop_reason")
                    final_results["ready"] = True
                if journal and event.get("type") in _JOURNALED_EVENT_TYPES:
                    journal.record(event)
                event_queue.put(event)
                if not final_results["ready"] and time.monotonic() > deadline:
                    timed_out = True
                    logger.warning(
                        "Chat stream exceeded its timeout; stopping agent",
                        extra={
                            "user_id": user_id,
                            "conversation_id": conv_id,
                            "timeout_seconds": turn.timeout_seconds,
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

        # Steering sent while the final answer wrote was never read: the
        # save moves it after the reply and the done event flags it
        final_results["unanswered_steering"] = pop_interjection(user_id, conv_id)
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
        turn_done.set()
        unregister_token(turn.request_id)
        clear_stop_request(user_id, conv_id, stop_key)
        clear_finish_request(user_id, conv_id, stop_key)
        # Steering that arrived after the last tool round was never popped
        clear_interjection(user_id, conv_id)
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
                saved = save_func()
                final_results["saved"] = True
                if saved is not None:
                    defer_final_steering(final_results, conv_id, saved.message_id)
                # The turn finished but no client was connected to see it
                # (typically mobile screen lock) - nudge the user's devices.
                # Not after Stop: the user was there and ended it themselves
                if not final_results.get("stop_reason"):
                    _notify_response_ready(
                        user_id,
                        conv_id,
                        str(final_results.get("clean_content") or ""),
                        push_title(final_results.get("usage_info") or {}),
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


def defer_final_steering(final_results: dict[str, Any], conv_id: str, reply_id: str) -> None:
    """Order the turn's unread steering after its saved reply (once)."""
    text = final_results.pop("unanswered_steering", None)
    if text:
        final_results["unanswered_steering_id"] = defer_unanswered_steering(conv_id, reply_id, text)
