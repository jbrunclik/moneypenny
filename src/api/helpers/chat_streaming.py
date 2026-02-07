"""Chat streaming helper functions.

This module contains helper functions extracted from the chat_stream route
for managing streaming message save operations and background threads.
"""

from __future__ import annotations

import json
import queue
import threading
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


def _close_thread_db_connections() -> None:
    """Close DB pool connections for the current thread.

    Called when a short-lived background thread is about to exit so the
    ConnectionPool doesn't keep a reference to the connection forever.
    """
    try:
        db._pool.close_thread_connection()
    except Exception:
        pass
    try:
        from src.db.blob_store import get_blob_store

        get_blob_store()._pool.close_thread_connection()
    except Exception:
        pass


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
        # Extract metadata from tool calls and deterministic analysis
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
                "generated_images_count": len(generated_images_meta)
                if generated_images_meta
                else 0,
                "language": language,
            },
        )

        # Process memory operations (skip in anonymous mode)
        if not anonymous_mode:
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

        # Get the FULL tool results (with _full_result) captured before stripping
        # This is needed for extracting generated images and code output files
        # NOTE: get_full_tool_results() POPS the results, so we can only call it once!
        full_tool_results = get_full_tool_results(stream_request_id)
        set_current_request_id(None)  # Clean up
        set_current_message_files(None)  # Clean up
        set_conversation_context(None, None)  # Clean up

        # Extract generated files from FULL tool results (before stripping)
        gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
        code_output_files = extract_code_output_files_from_tool_results(full_tool_results)

        # Combine all generated files
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

        # Save complete response to DB
        logger.debug(
            "Saving assistant message from stream",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
        assistant_msg = db.add_message(
            conv_id,
            MessageRole.ASSISTANT,
            content,
            files=all_generated_files if all_generated_files else None,
            sources=sources if sources else None,
            generated_images=generated_images_meta if generated_images_meta else None,
            language=language,
            message_id=assistant_message_id,
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

        # Auto-generate title from first message if still default
        conv = db.get_conversation(conv_id, user_id)
        generated_title: str | None = None
        if conv and conv.title == "New Conversation":
            logger.debug(
                "Auto-generating conversation title from stream",
                extra={"user_id": user_id, "conversation_id": conv_id},
            )
            generated_title = generate_title(message_text, content)
            db.update_conversation(conv_id, user_id, title=generated_title)
            logger.debug(
                "Conversation title generated from stream",
                extra={
                    "user_id": user_id,
                    "conversation_id": conv_id,
                    "title": generated_title,
                },
            )

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
    """
    # Copy context from parent thread so contextvars are accessible
    set_current_request_id(stream_request_id)
    set_current_message_files(files if files else None)
    set_conversation_context(conv_id, user_id)
    try:
        logger.debug(
            "Stream thread started", extra={"user_id": user_id, "conversation_id": conv_id}
        )
        event_count = 0
        for event in agent.stream_chat_events(
            message_text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
            is_planning=is_planning,
            dashboard_data=dashboard_data,
        ):
            event_count += 1
            if event.get("type") == "final":
                # Store final results for cleanup thread
                final_results["clean_content"] = event.get("content", "")
                final_results["result_messages"] = event.get("result_messages", [])
                final_results["tool_results"] = event.get("tool_results", [])
                final_results["usage_info"] = event.get("usage_info", {})
                final_results["ready"] = True
            event_queue.put(event)
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
        event_queue.put(
            {
                "type": "approval_required",
                "approval_id": e.approval_id,
                "description": e.description,
                "tool_name": e.tool_name,
            }
        )
    except Exception as e:
        logger.error(
            "Stream thread error",
            extra={"user_id": user_id, "conversation_id": conv_id, "error": str(e)},
            exc_info=True,
        )
        event_queue.put(e)  # Signal error
    finally:
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
            # 3. There's actual content to save (don't save empty messages)
            clean_content = final_results.get("clean_content", "")
            if final_results["ready"] and not final_results["saved"] and clean_content:
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
                        "has_content": bool(clean_content),
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
        self.result_messages: list[Any] = []
        self.tool_results: list[dict[str, Any]] = []
        self.usage_info: dict[str, Any] = {}
        self.client_connected = True

        # Pre-generate assistant message ID for streaming recovery
        # This allows the frontend to fetch the specific message if the stream fails
        self.expected_assistant_msg_id = str(uuid.uuid4())

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

        # Set up agent context if this is an agent conversation
        if self.conv.is_agent and self.conv.agent_id:
            self._setup_agent_context()

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
            user_id=self.user_id,
            force_refresh=False,
            db=db,
        )
        self.dashboard_data = asdict(dashboard_obj)
        _planner_dashboard_context.set(self.dashboard_data)

    def _setup_agent_context(self) -> None:
        """Set up agent context if this is an interactive agent conversation."""
        # Type narrowing: agent_id is checked in setup_context before calling this
        assert self.conv.agent_id is not None
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
        """Clean up agent context if this was an agent conversation."""
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
            ),
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

    Includes the expected assistant message ID so the frontend can recover
    the message if the stream fails (e.g., connection drops mid-stream).
    """
    try:
        event_data = {
            "type": "user_message_saved",
            "user_message_id": context.user_msg.id,
            "expected_assistant_message_id": context.expected_assistant_msg_id,
        }
        yield f"data: {json.dumps(event_data)}\n\n"
    except (BrokenPipeError, ConnectionError, OSError):
        pass


def _process_event_queue(context: _StreamContext) -> Generator[str]:
    """Process events from the queue and yield SSE data."""
    while True:
        try:
            item = context.event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL)

            if item is None:
                break
            elif isinstance(item, Exception):
                yield from _handle_queue_error(context, item)
                return
            elif isinstance(item, dict):
                yield from _handle_queue_event(context, item)

        except queue.Empty:
            yield from _send_keepalive(context)


def _handle_queue_error(context: _StreamContext, error: Exception) -> Generator[str]:
    """Handle an error from the event queue."""
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
        }
        # Send the approval event to the client
        try:
            yield f"data: {json.dumps(item)}\n\n"
        except (BrokenPipeError, ConnectionError, OSError) as e:
            context.mark_disconnected(e, "streaming (approval_required)")
    elif event_type in ("thinking", "tool_start", "tool_end", "token"):
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

    # Skip done event if no content or save failed (nothing to finalize)
    if not context.clean_content or not save_result:
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

    # Build and save the approval message
    approval_message = build_approval_message(approval_id, description, tool_name)

    logger.debug(
        "Saving approval message from stream",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "approval_id": approval_id,
        },
    )

    assistant_msg = db.add_message(
        context.conv_id,
        MessageRole.ASSISTANT,
        approval_message,
    )

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
