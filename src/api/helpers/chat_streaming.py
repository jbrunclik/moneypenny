"""Chat streaming helper functions.

This module contains helper functions extracted from the chat_stream route
for managing streaming message save operations and background threads.
"""

import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from src.agent.agent import ChatAgent, generate_title
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import set_conversation_context, set_current_message_files
from src.api.schemas import MessageRole
from src.api.utils import (
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
