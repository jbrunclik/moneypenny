"""Chat streaming helper functions.

This module contains helper functions extracted from the chat_stream route
for managing streaming message save operations and background threads.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from src.agent.agent import ChatAgent, generate_title
from src.agent.content import (
    detect_response_language,
    extract_image_prompts_from_messages,
    extract_metadata_tool_args,
    extract_sources_fallback_from_tool_results,
)

# Agent context imports for interactive agent conversations
from src.agent.executor import AgentContext, clear_agent_context, set_agent_context
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import set_conversation_context, set_current_message_files
from src.agent.tools.request_approval import (
    ApprovalRequestedException,
    build_approval_message,
)
from src.api.schemas import MessageRole
from src.api.utils import (
    build_stream_done_event,
    calculate_and_save_message_cost,
    process_memory_operations,
    validate_memory_operations,
)
from src.config import Config
from src.db.models import db
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Conversation, Message, User

logger = get_logger(__name__)

# Appended to partial content when an interactive chat turn hits CHAT_TIMEOUT.
STREAM_TIMEOUT_MARKER = "\n\n_…(response timed out)_"

# Appended to partial content when the producer crashes mid-stream (X1):
# losing the whole answer to a late crash threw away everything streamed
STREAM_ERROR_MARKER = "\n\n_…(response interrupted by an error)_"


def load_sports_context(user_id: str, program_id: str) -> dict[str, Any] | None:
    """Load sports program context from K/V store for the system prompt.

    Loads the program metadata AND any existing KV data (goals, preferences,
    routine, progress, last_session) so the agent can see what's stored.

    Args:
        user_id: The user's ID
        program_id: The sports program ID

    Returns:
        Sports context dict with program info and stored KV data, or None
    """
    raw = db.kv_get(user_id, "sports", "programs")
    if not raw:
        return None
    try:
        programs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    program = next((p for p in programs if p.get("id") == program_id), None)
    if not program:
        return None

    # Load existing KV data for this program (single query with prefix)
    items = db.kv_list(user_id, "sports", prefix=f"{program_id}:")
    kv_data = {k.split(":", 1)[1]: v for k, v in items}

    return {
        "program_name": program.get("name", "Training"),
        "program_id": program_id,
        "kv_data": kv_data,
    }


def load_language_context(user_id: str, program_id: str) -> dict[str, Any] | None:
    """Load language program context from K/V store for the system prompt.

    Loads the program metadata AND any existing KV data (profile, assessment,
    vocabulary, grammar, etc.) so the agent can see what's stored.

    Args:
        user_id: The user's ID
        program_id: The language program ID

    Returns:
        Language context dict with program info and stored KV data, or None
    """
    raw = db.kv_get(user_id, "language", "programs")
    if not raw:
        return None
    try:
        programs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    program = next((p for p in programs if p.get("id") == program_id), None)
    if not program:
        return None

    # Load existing KV data for this program (single query with prefix)
    items = db.kv_list(user_id, "language", prefix=f"{program_id}:")
    kv_data = {k.split(":", 1)[1]: v for k, v in items}

    return {
        "program_name": program.get("name", "Language"),
        "program_id": program_id,
        "kv_data": kv_data,
    }


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


class SaveResult:
    """Result from save_message_to_db with extracted data for done event."""

    def __init__(
        self,
        message_id: str,
        sources: list[dict[str, str]],
        generated_images_meta: list[dict[str, str]],
        all_generated_files: list[dict[str, Any]],
        generated_title: str | None,
        language: str | None,
    ) -> None:
        self.message_id = message_id
        self.sources = sources
        self.generated_images_meta = generated_images_meta
        self.all_generated_files = all_generated_files
        self.generated_title = generated_title
        self.language = language


def _extract_stream_metadata(
    content: str,
    result_messages: list[Any],
    tools: list[dict[str, Any]],
    user_id: str,
    conv_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None, list[dict[str, Any]]]:
    """Extract sources, image prompts, language and memory ops from the turn."""
    sources, memory_ops = extract_metadata_tool_args(result_messages)
    generated_images_meta = extract_image_prompts_from_messages(result_messages)
    language = detect_response_language(content)

    # Fallback: if web_search was used but no cite_sources, extract from tool results
    if not sources and tools:
        sources = extract_sources_fallback_from_tool_results(tools)

    logger.debug(
        "Extracted metadata from stream",
        extra={
            "user_id": user_id,
            "conversation_id": conv_id,
            "sources_count": len(sources) if sources else 0,
            "generated_images_count": len(generated_images_meta) if generated_images_meta else 0,
            "language": language,
        },
    )
    return sources, generated_images_meta, language, memory_ops


def _apply_memory_operations(
    memory_ops: list[dict[str, Any]],
    stream_user_id: str,
    conv_id: str,
    anonymous_mode: bool,
) -> None:
    """Validate and persist manage_memory operations (skipped in anonymous mode)."""
    if anonymous_mode:
        return
    memory_ops = validate_memory_operations(memory_ops)
    if memory_ops:
        logger.debug(
            "Processing memory operations from stream",
            extra={
                "user_id": stream_user_id,
                "conversation_id": conv_id,
                "operation_count": len(memory_ops),
            },
        )
        process_memory_operations(stream_user_id, memory_ops)


def _collect_generated_files(
    stream_request_id: str, user_id: str, conv_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pop the full tool results, clean up request context, extract files.

    Returns (all_generated_files, full_tool_results). NOTE:
    get_full_tool_results() POPS the results - callable only once per request.
    """
    full_tool_results = get_full_tool_results(stream_request_id)
    set_current_request_id(None)  # Clean up
    set_current_message_files(None)  # Clean up
    set_conversation_context(None, None)  # Clean up

    # Extract generated files from FULL tool results (before stripping)
    gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
    code_output_files = extract_code_output_files_from_tool_results(full_tool_results)

    all_generated_files = gen_image_files + code_output_files
    if all_generated_files:
        logger.info(
            "Generated files extracted from stream",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "image_count": len(gen_image_files),
                "code_output_count": len(code_output_files),
            },
        )
    return all_generated_files, full_tool_results


def _persist_assistant_message(
    conv_id: str,
    user_id: str,
    content: str,
    assistant_message_id: str | None,
    all_generated_files: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    generated_images_meta: list[dict[str, Any]],
    language: str | None,
) -> Any:
    """UPDATE the stream-start placeholder, or INSERT when it is gone/absent."""
    logger.debug(
        "Saving assistant message from stream",
        extra={"user_id": user_id, "conversation_id": conv_id},
    )
    kwargs: dict[str, Any] = {
        "files": all_generated_files if all_generated_files else None,
        "sources": sources if sources else None,
        "generated_images": generated_images_meta if generated_images_meta else None,
        "language": language,
    }
    if assistant_message_id:
        assistant_msg = db.update_message_content(assistant_message_id, content, **kwargs)
        if assistant_msg:
            return assistant_msg
        # Placeholder was deleted (user deleted while processing) — fall back to INSERT
        logger.info(
            "Placeholder message deleted during processing, falling back to INSERT",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
    return db.add_message(conv_id, MessageRole.ASSISTANT, content, **kwargs)


def _maybe_generate_title(
    conv_id: str, user_id: str, message_text: str, content: str
) -> str | None:
    """Auto-generate the conversation title from the first exchange.

    Wrapped in its own try/except so a title-generation failure can never
    abort the message save (which already succeeded). On failure the default
    title stays; the next user message retries.
    """
    conv = db.get_conversation(conv_id, user_id)
    if not conv or conv.title != Config.DEFAULT_CONVERSATION_TITLE:
        return None

    logger.debug(
        "Auto-generating conversation title from stream",
        extra={"user_id": user_id, "conversation_id": conv_id},
    )
    try:
        generated_title = generate_title(message_text, content)
        if generated_title is not None:
            db.update_conversation(conv_id, user_id, title=generated_title)
            logger.debug(
                "Conversation title generated from stream",
                extra={
                    "user_id": user_id,
                    "conversation_id": conv_id,
                    "title": generated_title,
                },
            )
        return generated_title
    except Exception:
        logger.exception(
            "Title generation/update failed (continuing without title)",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
        return None


def save_message_to_db(
    content: str,
    result_messages: list[Any],
    tools: list[dict[str, Any]],
    usage: dict[str, Any],
    conv_id: str,
    user_id: str,
    stream_user_id: str,
    model: str,
    message_text: str,
    stream_request_id: str,
    anonymous_mode: bool,
    client_connected: bool,
    assistant_message_id: str | None = None,
) -> SaveResult | None:
    """Save message to database. Called from both generator and cleanup thread.

    Orchestrates the sub-steps: metadata extraction, memory operations,
    generated-file collection, message persistence, cost accounting and
    title generation.

    Args:
        content: Message content to save
        result_messages: All messages from the graph for metadata extraction
        tools: Tool results list
        usage: Usage info dictionary
        conv_id: Conversation ID
        user_id: User ID string (for logging)
        stream_user_id: Streaming user ID string (for memory operations)
        model: Model name
        message_text: Original user message text (for title generation)
        stream_request_id: Streaming request ID (for full tool results)
        anonymous_mode: Whether anonymous mode is enabled
        client_connected: Whether client is still connected (for logging)
        assistant_message_id: Pre-generated message ID for streaming recovery

    Returns:
        SaveResult with extracted data for building done event, or None on error.
    """
    try:
        sources, generated_images_meta, language, memory_ops = _extract_stream_metadata(
            content, result_messages, tools, user_id, conv_id
        )
        _apply_memory_operations(memory_ops, stream_user_id, conv_id, anonymous_mode)
        all_generated_files, full_tool_results = _collect_generated_files(
            stream_request_id, user_id, conv_id
        )
        assistant_msg = _persist_assistant_message(
            conv_id,
            user_id,
            content,
            assistant_message_id,
            all_generated_files,
            sources,
            generated_images_meta,
            language,
        )

        # Calculate and save cost for streaming (use full_tool_results for image cost)
        calculate_and_save_message_cost(
            assistant_msg.id,
            conv_id,
            user_id,
            model,
            usage,
            full_tool_results,
            len(content),
            mode="stream",
        )

        generated_title = _maybe_generate_title(conv_id, user_id, message_text, content)

        logger.info(
            "Stream chat completed and saved",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "message_id": assistant_msg.id,
                "response_length": len(content),
                "client_connected": client_connected,
            },
        )

        # Return extracted data for building done event
        return SaveResult(
            message_id=assistant_msg.id,
            sources=sources,
            generated_images_meta=generated_images_meta,
            all_generated_files=all_generated_files,
            generated_title=generated_title,
            language=language,
        )
    except Exception as e:
        logger.error(
            "Error saving stream message to DB",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "error": str(e),
            },
            exc_info=True,
        )
        return None


_JOURNALED_EVENT_TYPES = {
    "token",
    "thinking",
    "tool_start",
    "tool_end",
    "approval_required",
    "timeout",
}


class _StreamJournal:
    """Batched journal of stream events, keyed by assistant message id.

    Enables resume-after-disconnect: the producer journals every client-facing
    event with a monotonic seq; the resume endpoint replays rows after the
    client's last seen seq and continues live. Persistence is best-effort -
    journal failures never break the live stream.
    """

    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self._seq = 0
        self._buffer: list[tuple[int, str]] = []
        self._last_flush = time.monotonic()
        try:
            db.journal_cleanup(Config.STREAM_JOURNAL_TTL_SECONDS)
        except Exception:
            logger.warning("Stream journal cleanup failed", exc_info=True)

    def record(self, event: dict[str, Any]) -> None:
        """Assign a seq to the event, buffer it, flush opportunistically."""
        self._seq += 1
        event["seq"] = self._seq
        try:
            serialized = json.dumps(event)
        except (TypeError, ValueError):
            serialized = json.dumps({"type": event.get("type", "unknown"), "seq": self._seq})
        self._buffer.append((self._seq, serialized))
        if (
            len(self._buffer) >= Config.STREAM_JOURNAL_FLUSH_EVENTS
            or time.monotonic() - self._last_flush >= Config.STREAM_JOURNAL_FLUSH_INTERVAL_SECONDS
        ):
            self.flush()

    def flush(self) -> None:
        buffer, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        if not buffer:
            return
        try:
            db.journal_append_events(self.message_id, buffer)
        except Exception:
            logger.warning("Stream journal flush failed", exc_info=True)

    def finish(self) -> None:
        """Mark the stream as over (resume endpoint stops tailing on this)."""
        self._seq += 1
        self._buffer.append((self._seq, json.dumps({"type": "stream_end", "seq": self._seq})))
        self.flush()


def stream_events(
    agent: ChatAgent,
    event_queue: queue.Queue[dict[str, Any] | None | Exception],
    final_results: dict[str, Any],
    message_text: str,
    files: list[dict[str, Any]] | None,
    history: list[dict[str, Any]],
    force_tools: list[str] | None,
    user_name: str,
    user_id: str,
    custom_instructions: str | None,
    is_planning: bool,
    dashboard_data: dict[str, Any] | None,
    conv_id: str,
    stream_request_id: str,
    conversation_id: str | None = None,
    is_sports: bool = False,
    sports_context: dict[str, Any] | None = None,
    is_language: bool = False,
    language_context: dict[str, Any] | None = None,
    journal_message_id: str | None = None,
) -> None:
    """Background thread that streams events into the queue.

    Args:
        agent: ChatAgent instance
        event_queue: Queue to push events into
        final_results: Shared dict to store final results
        message_text: User message text
        files: Optional file attachments
        history: Message history
        force_tools: Optional list of forced tools
        user_name: User's name
        user_id: User ID
        custom_instructions: Optional custom instructions
        is_planning: Whether this is a planning conversation
        dashboard_data: Optional planner dashboard data
        conv_id: Conversation ID (for logging)
        stream_request_id: Stream request ID (for context)
        journal_message_id: Assistant message id for the resumable-stream
            journal (None disables journaling)
    """
    journal: _StreamJournal | None = None
    if journal_message_id and Config.STREAM_JOURNAL_ENABLED:
        journal = _StreamJournal(journal_message_id)
    # Copy context from parent thread so contextvars are accessible
    set_current_request_id(stream_request_id)
    set_current_message_files(files if files else None)
    set_conversation_context(conv_id, user_id)
    if is_sports and sports_context:
        from src.agent.tools.context import set_sports_context

        set_sports_context(sports_context.get("program_id"))
    if is_language and language_context:
        from src.agent.tools.context import set_language_context

        set_language_context(language_context.get("program_id"))
    try:
        logger.debug(
            "Stream thread started", extra={"user_id": user_id, "conversation_id": conv_id}
        )
        event_count = 0
        deadline = time.monotonic() + Config.CHAT_TIMEOUT
        timed_out = False
        gen = agent.stream_chat_events(
            message_text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
            conversation_id=conversation_id,
            is_sports=is_sports,
            sports_context=sports_context,
            is_language=is_language,
            language_context=language_context,
        )
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


def stream_resume_events(message_id: str, after_seq: int) -> Generator[str]:
    """Resume an interrupted chat stream from the event journal.

    Replays journaled events with seq > after_seq, then tails the journal
    until the producer's stream_end marker. After stream_end, waits for the
    saved message (the save happens in the consumer/cleanup thread shortly
    after the producer finishes) and emits a done event built from it.

    Works cross-worker: the journal is DB-backed, so the resume request may
    land on a different gunicorn worker than the one still generating.
    """
    deadline = time.monotonic() + Config.CHAT_TIMEOUT
    last_keepalive = time.monotonic()
    stream_ended = False
    save_grace_deadline: float | None = None
    # No new journal rows for this long (before stream_end) = the producer is
    # dead (e.g. process killed mid-turn left no terminal marker). Without
    # this bound a resume of a dead turn would hold a worker thread and send
    # keepalives until CHAT_TIMEOUT.
    stall_deadline = time.monotonic() + Config.STREAM_RESUME_STALL_SECONDS

    def _done_event_from_message(msg: Any) -> dict[str, Any]:
        done: dict[str, Any] = {
            "type": "done",
            "id": msg.id,
            "created_at": msg.created_at.isoformat(),
            "content": msg.content or "",
        }
        if msg.files:
            done["files"] = msg.files
        if msg.sources:
            done["sources"] = msg.sources
        if msg.generated_images:
            done["generated_images"] = msg.generated_images
        if msg.language:
            done["language"] = msg.language
        return done

    while time.monotonic() < deadline:
        events = db.journal_get_events(message_id, after_seq)
        if events:
            stall_deadline = time.monotonic() + Config.STREAM_RESUME_STALL_SECONDS
        for seq, event_json in events:
            after_seq = seq
            try:
                parsed = json.loads(event_json)
            except ValueError:
                continue
            if parsed.get("type") == "stream_end":
                stream_ended = True
                continue
            yield f"data: {event_json}\n\n"

        # A saved message (non-empty placeholder) means the turn is complete -
        # this also covers resume-after-completion when the journal was swept
        msg = db.get_message_by_id(message_id)
        if msg and (msg.content or msg.files):
            yield f"data: {json.dumps(_done_event_from_message(msg))}\n\n"
            return

        if stream_ended:
            if save_grace_deadline is None:
                save_grace_deadline = time.monotonic() + Config.STREAM_RESUME_SAVE_GRACE_SECONDS
            if msg is None or time.monotonic() > save_grace_deadline:
                # Placeholder deleted (failed turn) or the save never landed
                error_data = {
                    "type": "error",
                    "code": "RESUME_FAILED",
                    "message": "The response could not be recovered.",
                    "retryable": False,
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                return

        if not stream_ended and time.monotonic() > stall_deadline:
            error_data = {
                "type": "error",
                "code": "RESUME_FAILED",
                "message": "The stream made no progress and appears to be dead.",
                "retryable": False,
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            return

        if not events:
            time.sleep(0.4)
            if time.monotonic() - last_keepalive >= Config.SSE_KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()

    yield f"data: {json.dumps({'type': 'timeout'})}\n\n"


# ============================================================================
# Stream Generator Creation
# ============================================================================


def create_stream_generator(
    user: User,
    conv: Conversation,
    user_msg: Message,
    message_text: str,
    files: list[dict[str, Any]],
    history: list[dict[str, Any]],
    force_tools: list[str] | None,
    anonymous_mode: bool,
    stream_request_id: str,
) -> Generator[str]:
    """Create the SSE stream generator for chat streaming.

    This factory function creates and returns the generator that handles:
    - Setting up agent and threading context
    - Processing events from the background thread
    - Sending SSE events to the client
    - Saving the message to the database

    Args:
        user: The authenticated user
        conv: The conversation object
        user_msg: The saved user message
        message_text: The user's message text
        files: List of file attachments
        history: Conversation history
        force_tools: Optional list of tools to force
        anonymous_mode: Whether anonymous mode is enabled
        stream_request_id: Unique request ID for tool result capture

    Returns:
        Generator that yields SSE-formatted strings
    """

    def generate() -> Generator[str]:
        """Generator that streams tokens as SSE events with keepalive support."""
        # Initialize context
        context = _StreamContext(
            user=user,
            conv=conv,
            user_msg=user_msg,
            message_text=message_text,
            files=files,
            history=history,
            force_tools=force_tools,
            anonymous_mode=anonymous_mode,
            stream_request_id=stream_request_id,
        )

        # Set up threading context
        context.setup_context()

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
            # Clean up agent context if this was an agent conversation
            context.cleanup_agent_context()
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
        self,
        user: User,
        conv: Conversation,
        user_msg: Message,
        message_text: str,
        files: list[dict[str, Any]],
        history: list[dict[str, Any]],
        force_tools: list[str] | None,
        anonymous_mode: bool,
        stream_request_id: str,
    ) -> None:
        self.user = user
        self.conv = conv
        self.user_msg = user_msg
        self.message_text = message_text
        self.files = files
        self.history = history
        self.force_tools = force_tools
        self.anonymous_mode = anonymous_mode
        self.stream_request_id = stream_request_id

        # Derived values
        self.conv_id = conv.id
        self.user_id = user.id
        self.stream_user_id = user.id

        # State
        self.clean_content = ""
        # Streamed token text accumulated for partial-save on timeout.
        self.partial_content = ""
        self.result_messages: list[Any] = []
        self.tool_results: list[dict[str, Any]] = []
        self.usage_info: dict[str, Any] = {}
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
        self.final_results: dict[str, Any] = {"ready": False, "saved": False}
        # Lock to prevent race condition between generator and cleanup thread saves
        self.save_lock = threading.Lock()
        # Event that generator sets when it has finished its save attempt (or decided not to save)
        # Cleanup thread waits on this to give generator priority
        self.generator_done_event = threading.Event()
        self.stream_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        self.dashboard_data: dict[str, Any] | None = None

        # Sports context for sports conversations
        self.sports_context: dict[str, Any] | None = None

        # Language context for language learning conversations
        self.language_context: dict[str, Any] | None = None

        # Agent context for interactive agent conversations
        self.is_autonomous = False
        self.agent_context: dict[str, Any] | None = None

        # Approval request info (set when ApprovalRequestedException is caught)
        self.approval_info: dict[str, Any] | None = None

    def setup_context(self) -> None:
        """Set up request context variables."""
        set_current_request_id(self.stream_request_id)
        set_current_message_files(self.files if self.files else None)
        set_conversation_context(self.conv_id, self.user_id)

        # Fetch planner dashboard if needed
        if self.conv.is_planning:
            self._setup_planner_context()

        # Set up sports context if this is a sports conversation
        if self.conv.is_sports and self.conv.sports_program:
            self._setup_sports_context()

        # Set up language context if this is a language learning conversation
        if self.conv.is_language and self.conv.language_program:
            self._setup_language_context()

        # Set up agent context if this is an agent conversation
        if self.conv.is_agent and self.conv.agent_id:
            self._setup_agent_context()

        # Compact long histories for regular (non-agent) conversations to bound
        # per-turn input cost. Agent conversations use their own destructive
        # compaction, so they are left untouched.
        if not self.is_autonomous:
            from src.agent.conversation_compaction import build_compacted_history

            self.history = build_compacted_history(self.user_id, self.conv_id, self.history)

    def _setup_planner_context(self) -> None:
        """Set up planner dashboard context if this is a planning conversation."""
        from dataclasses import asdict

        from src.agent.agent import _planner_dashboard_context
        from src.api.routes.calendar import _get_valid_calendar_access_token
        from src.utils.planner_data import build_planner_dashboard

        calendar_token = _get_valid_calendar_access_token(self.user)
        dashboard_obj = build_planner_dashboard(
            todoist_token=self.user.todoist_access_token,
            calendar_token=calendar_token,
            garmin_token=self.user.garmin_token,
            user_id=self.user_id,
            force_refresh=False,
            db=db,
        )
        self.dashboard_data = asdict(dashboard_obj)
        _planner_dashboard_context.set(self.dashboard_data)

    def _setup_sports_context(self) -> None:
        """Set up sports program context for sports conversations."""
        from src.agent.tools import set_sports_context

        assert self.conv.sports_program is not None  # noqa: S101 - narrowing; checked by caller
        self.sports_context = load_sports_context(self.user_id, self.conv.sports_program)
        set_sports_context(self.conv.sports_program)

    def _setup_language_context(self) -> None:
        """Set up language program context for language learning conversations."""
        from src.agent.tools import set_language_context

        assert self.conv.language_program is not None  # noqa: S101 - narrowing; checked by caller
        self.language_context = load_language_context(self.user_id, self.conv.language_program)
        set_language_context(self.conv.language_program)

    def _setup_agent_context(self) -> None:
        """Set up agent context if this is an interactive agent conversation."""
        # Type narrowing: agent_id is checked in setup_context before calling this
        assert self.conv.agent_id is not None  # noqa: S101 - narrowing; checked by caller
        agent_record = db.get_agent(self.conv.agent_id, self.user_id)
        if agent_record:
            logger.debug(
                "Interactive agent conversation (streaming) - applying tool permissions",
                extra={
                    "user_id": self.user_id,
                    "conversation_id": self.conv_id,
                    "agent_id": agent_record.id,
                    "tool_permissions": agent_record.tool_permissions,
                },
            )
            # Set up agent execution context for permission checks
            agent_execution_context = AgentContext(
                agent=agent_record,
                user=self.user,
                trigger_chain=[agent_record.id],
            )
            set_agent_context(agent_execution_context)
            self.is_autonomous = True
            # Build agent context for the ChatAgent (for tool filtering)
            # Note: tool_permissions=None means all tools, [] means no tools
            self.agent_context = {
                "name": agent_record.name,
                "description": agent_record.description,
                "schedule": agent_record.schedule,
                "timezone": agent_record.timezone,
                "goals": agent_record.system_prompt,
                "tools": agent_record.tool_permissions,
                "trigger_type": "interactive",
            }

    def cleanup_agent_context(self) -> None:
        """Clean up agent, sports, and language context."""
        if self.conv.is_sports:
            from src.agent.tools import set_sports_context

            set_sports_context(None)
        if self.conv.is_language:
            from src.agent.tools import set_language_context

            set_language_context(None)
        if self.is_autonomous:
            clear_agent_context()

    def start_threads(self) -> None:
        """Start the streaming and cleanup background threads."""
        agent = ChatAgent(
            model_name=self.conv.model,
            include_thoughts=True,
            anonymous_mode=self.anonymous_mode,
            is_planning=self.conv.is_planning,
            is_autonomous=self.is_autonomous,
            agent_context=self.agent_context,
            is_sports=self.conv.is_sports,
            sports_context=self.sports_context,
            is_language=self.conv.is_language,
            language_context=self.language_context,
        )

        self.stream_thread = threading.Thread(
            target=stream_events,
            args=(
                agent,
                self.event_queue,
                self.final_results,
                self.message_text,
                self.files,
                self.history,
                self.force_tools,
                self.user.name,
                self.user_id,
                self.user.custom_instructions,
                self.conv.is_planning,
                self.dashboard_data,
                self.conv_id,
                self.stream_request_id,
                self.conv_id,  # conversation_id for checkpointing
                self.conv.is_sports,
                self.sports_context,
                self.conv.is_language,
                self.language_context,
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
                    self.stream_user_id,
                    self.conv.model,
                    self.message_text,
                    self.stream_request_id,
                    self.anonymous_mode,
                    self.client_connected,
                    self.expected_assistant_msg_id,
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
    except (BrokenPipeError, ConnectionError, OSError):
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
            "timeout_seconds": Config.CHAT_TIMEOUT,
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
    deadline = time.monotonic() + Config.CHAT_TIMEOUT + Config.SSE_KEEPALIVE_INTERVAL
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
    except (BrokenPipeError, ConnectionError, OSError):
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
    elif event_type in ("thinking", "tool_start", "tool_end", "token"):
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


def _finalize_stream(context: _StreamContext) -> Generator[str]:
    """Save message to DB and yield done event."""
    # Handle approval request if present
    if context.approval_info:
        yield from _finalize_approval_stream(context)
        return

    # Use lock to prevent race condition with cleanup thread's save
    # The lock ensures check-then-save is atomic
    with context.save_lock:
        # Check if cleanup thread already saved (shouldn't happen but be defensive)
        if context.final_results["saved"]:
            logger.debug(
                "Message already saved by cleanup thread, skipping generator save",
                extra={
                    "user_id": context.user_id,
                    "conversation_id": context.conv_id,
                },
            )
            # Fetch the message to build done event
            assistant_msg = db.get_message_by_id(context.expected_assistant_msg_id)
            if assistant_msg:
                done_data = build_stream_done_event(
                    assistant_msg,
                    assistant_msg.files or [],
                    assistant_msg.sources or [],
                    assistant_msg.generated_images or [],
                    conversation_title=None,
                    user_message_id=context.user_msg.id,
                    language=assistant_msg.language,
                )
                try:
                    yield f"data: {json.dumps(done_data)}\n\n"
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
            return

        save_result = save_message_to_db(
            context.clean_content,
            context.result_messages,
            context.tool_results,
            context.usage_info,
            context.conv_id,
            context.user_id,
            context.stream_user_id,
            context.conv.model,
            context.message_text,
            context.stream_request_id,
            context.anonymous_mode,
            context.client_connected,
            context.expected_assistant_msg_id,
        )

        # Mark as saved so cleanup thread knows not to save again
        if save_result:
            context.final_results["saved"] = True

    # Skip done event if save failed (nothing to finalize)
    if not save_result:
        return

    # Fetch the message by its known ID (more reliable than getting last message)
    assistant_msg = db.get_message_by_id(context.expected_assistant_msg_id)
    if not assistant_msg:
        return
    done_data = build_stream_done_event(
        assistant_msg,
        save_result.all_generated_files,
        save_result.sources,
        save_result.generated_images_meta,
        conversation_title=save_result.generated_title,
        user_message_id=context.user_msg.id,
        language=save_result.language,
    )

    # Try to send done event even if client may have disconnected.
    # This ensures the frontend can finalize the message if still connected.
    # If truly disconnected, the write will fail and be caught below.
    try:
        yield f"data: {json.dumps(done_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        logger.info(
            "Client disconnected before done event, but message saved",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "message_id": assistant_msg.id,
                "error": str(e),
            },
        )


def _finalize_approval_stream(context: _StreamContext) -> Generator[str]:
    """Handle finalization when an approval request was raised.

    Saves the approval message to the conversation and sends a done event.
    """
    approval_id: str = context.approval_info.get("approval_id", "")  # type: ignore[union-attr]
    description: str = context.approval_info.get("description", "")  # type: ignore[union-attr]
    tool_name: str = context.approval_info.get("tool_name", "")  # type: ignore[union-attr]
    sibling_results = context.approval_info.get("sibling_results", [])  # type: ignore[union-attr]

    # Build and save the approval message
    approval_message = build_approval_message(
        approval_id, description, tool_name, sibling_results=sibling_results
    )

    logger.debug(
        "Saving approval message from stream",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "approval_id": approval_id,
        },
    )

    if context.placeholder_saved:
        assistant_msg = db.update_message_content(
            context.expected_assistant_msg_id,
            approval_message,
        )
        if not assistant_msg:
            assistant_msg = db.add_message(context.conv_id, MessageRole.ASSISTANT, approval_message)
    else:
        assistant_msg = db.add_message(context.conv_id, MessageRole.ASSISTANT, approval_message)

    # Mark as saved so cleanup thread doesn't try to save again
    context.final_results["saved"] = True

    # Clean up context
    set_current_request_id(None)
    set_current_message_files(None)
    set_conversation_context(None, None)

    if not context.client_connected:
        return

    # Build done event with the approval message
    # Use same field names as build_stream_done_event for consistency
    done_data = {
        "type": "done",
        "id": assistant_msg.id,
        "created_at": assistant_msg.created_at.isoformat(),
        "user_message_id": context.user_msg.id,
        "approval_required": True,
        "approval_id": approval_id,
    }

    try:
        yield f"data: {json.dumps(done_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError) as e:
        logger.info(
            "Client disconnected before approval done event, but message saved",
            extra={
                "user_id": context.user_id,
                "conversation_id": context.conv_id,
                "message_id": assistant_msg.id,
                "error": str(e),
            },
        )


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
