"""Chat streaming helper functions.

This module contains helper functions extracted from the chat_stream route
for managing streaming message save operations and background threads.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from src.agent.agent import ChatAgent, generate_title
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import set_conversation_context, set_current_message_files
from src.api.schemas import MessageRole
from src.api.utils import (
    build_stream_done_event,
    calculate_and_save_message_cost,
    extract_language_from_metadata,
    extract_memory_operations,
    extract_metadata_fields,
    process_memory_operations,
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
    meta: dict[str, Any],
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
) -> SaveResult | None:
    """Save message to database. Called from both generator and cleanup thread.

    Args:
        content: Message content to save
        meta: Metadata dictionary
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

    Returns:
        SaveResult with extracted data for building done event, or None on error.
    """
    try:
        # Extract metadata fields
        sources, generated_images_meta = extract_metadata_fields(meta)
        language = extract_language_from_metadata(meta)
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

        # Process memory operations from metadata (skip in anonymous mode)
        if not anonymous_mode:
            memory_ops = extract_memory_operations(meta)
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
                final_results["metadata"] = event.get("metadata", {})
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
    except Exception as e:
        logger.error(
            "Stream thread error",
            extra={"user_id": user_id, "conversation_id": conv_id, "error": str(e)},
            exc_info=True,
        )
        event_queue.put(e)  # Signal error


def cleanup_and_save(
    stream_thread: threading.Thread,
    final_results: dict[str, Any],
    conv_id: str,
    user_id: str,
    save_func: Callable[[], SaveResult | None],
) -> None:
    """Wait for stream thread to complete, then save message if generator stopped early.

    Args:
        stream_thread: Threading thread to wait for
        final_results: Shared dict with final results
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

        # Wait a bit for generator to process final tuple (if client still connected)
        time.sleep(Config.STREAM_CLEANUP_WAIT_DELAY)

        # If final results are ready, save the message (generator may have stopped early)
        # We check if message was already saved by trying to get the last message
        # If it's the user message we just added, then assistant message wasn't saved yet
        if final_results["ready"]:
            messages = db.get_messages(conv_id)
            # Check if last message is assistant (meaning it was already saved by generator)
            if not messages or messages[-1].role != MessageRole.ASSISTANT:
                logger.info(
                    "Generator stopped early (client disconnected), saving message in cleanup thread",
                    extra={"user_id": user_id, "conversation_id": conv_id},
                )
                # Save the message using final results
                save_func()
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
        self.metadata: dict[str, Any] = {}
        self.tool_results: list[dict[str, Any]] = []
        self.usage_info: dict[str, Any] = {}
        self.client_connected = True

        # Threading
        self.event_queue: queue.Queue[dict[str, Any] | None | Exception] = queue.Queue()
        self.final_results: dict[str, Any] = {"ready": False}
        self.stream_thread: threading.Thread | None = None
        self.cleanup_thread: threading.Thread | None = None
        self.dashboard_data: dict[str, Any] | None = None

    def setup_context(self) -> None:
        """Set up request context variables."""
        set_current_request_id(self.stream_request_id)
        set_current_message_files(self.files if self.files else None)
        set_conversation_context(self.conv_id, self.user_id)

        # Fetch planner dashboard if needed
        if self.conv.is_planning:
            self._setup_planner_context()

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

    def start_threads(self) -> None:
        """Start the streaming and cleanup background threads."""
        agent = ChatAgent(
            model_name=self.conv.model,
            include_thoughts=True,
            anonymous_mode=self.anonymous_mode,
            is_planning=self.conv.is_planning,
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
                self.conv_id,
                self.user_id,
                lambda: save_message_to_db(
                    self.final_results["clean_content"],
                    self.final_results["metadata"],
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
    """Yield the user_message_saved event."""
    try:
        yield f"data: {json.dumps({'type': 'user_message_saved', 'user_message_id': context.user_msg.id})}\n\n"
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
        context.metadata = item.get("metadata", {})
        context.tool_results = item.get("tool_results", [])
        context.usage_info = item.get("usage_info", {})
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
    save_result = save_message_to_db(
        context.clean_content,
        context.metadata,
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
    )

    if not (context.client_connected and context.clean_content and save_result):
        return

    messages = db.get_messages(context.conv_id)
    if not messages or messages[-1].role != MessageRole.ASSISTANT:
        return

    assistant_msg = messages[-1]
    done_data = build_stream_done_event(
        assistant_msg,
        save_result.all_generated_files,
        save_result.sources,
        save_result.generated_images_meta,
        conversation_title=save_result.generated_title,
        user_message_id=context.user_msg.id,
        language=save_result.language,
    )

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
