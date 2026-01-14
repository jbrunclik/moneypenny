"""Chat routes: Batch and streaming chat endpoints.

This module handles chat interactions with the AI agent, supporting both
batch (complete response) and streaming (SSE) modes.
"""

import json
import queue
import threading
import uuid
from collections.abc import Generator
from typing import Any

from apiflask import APIBlueprint
from flask import Response

from src.agent.chat_agent import (
    ChatAgent,
    extract_metadata_from_response,
    generate_title,
    get_full_tool_results,
    set_current_request_id,
)
from src.agent.tools import set_conversation_context, set_current_message_files
from src.api.errors import (
    raise_llm_error,
    raise_not_found_error,
    raise_server_error,
    raise_validation_error,
)
from src.api.helpers.chat_streaming import (
    cleanup_and_save,
    save_message_to_db,
    stream_events,
)
from src.api.rate_limiting import rate_limit_chat
from src.api.routes.calendar import _get_valid_calendar_access_token
from src.api.schemas import ChatBatchResponse, ChatRequest, MessageRole
from src.api.utils import (
    build_chat_response,
    build_stream_done_event,
    calculate_and_save_message_cost,
    extract_language_from_metadata,
    extract_memory_operations,
    extract_metadata_fields,
    process_memory_operations,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.background_thumbnails import (
    mark_files_for_thumbnail_generation,
    queue_pending_thumbnails,
)
from src.utils.files import validate_files
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
)
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

api = APIBlueprint("chat", __name__, url_prefix="/api", tag="Chat")


# ============================================================================
# Chat Routes
# ============================================================================


@api.route("/conversations/<conv_id>/chat/batch", methods=["POST"])
@api.output(ChatBatchResponse)
@api.doc(responses=[400, 404, 429, 500])
@rate_limit_chat
@require_auth
@validate_request(ChatRequest)
def chat_batch(user: User, data: ChatRequest, conv_id: str) -> tuple[dict[str, str], int]:
    """Send a message and get a complete response (non-streaming).

    Accepts JSON body with:
    - message: str (optional if files present) - the text message
    - files: list[dict] (optional if message present) - array of {name, type, data} file objects
    - force_tools: list[str] (optional) - list of tool names to force (e.g. ["web_search"])
    """
    logger.info("Batch chat request", extra={"user_id": user.id, "conversation_id": conv_id})
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for chat",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    message_text = data.message.strip()
    files = [f.model_dump() for f in data.files]  # Convert Pydantic models to dicts
    force_tools = data.force_tools
    anonymous_mode = data.anonymous_mode
    log_payload_snippet(
        logger,
        {
            "message_length": len(message_text),
            "file_count": len(files),
            "force_tools": force_tools,
            "anonymous_mode": anonymous_mode,
        },
    )

    # Content validation for files (base64 decoding, size) - structure already validated by Pydantic
    if files:
        logger.debug(
            "Validating files",
            extra={"user_id": user.id, "conversation_id": conv_id, "file_count": len(files)},
        )
        is_valid, error = validate_files(files)
        if not is_valid:
            logger.warning(
                "File validation failed",
                extra={
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "error": error,
                    "file_count": len(files),
                },
            )
            raise_validation_error(error or "File validation failed", field="files")
        # Mark images for background thumbnail generation
        logger.debug(
            "Marking image files for thumbnail generation",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        files = mark_files_for_thumbnail_generation(files)

    # Save user message with separate content and files
    logger.debug(
        "Saving user message",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_length": len(message_text),
            "file_count": len(files) if files else 0,
        },
    )
    user_msg = db.add_message(
        conv_id, MessageRole.USER, message_text, files=files if files else None
    )

    # Queue background thumbnail generation for pending files
    if files:
        queue_pending_thumbnails(user_msg.id, files)

    # Get conversation history (excluding files from previous messages to save tokens)
    messages = db.get_messages(conv_id)
    history = [
        {"role": m.role.value, "content": m.content} for m in messages[:-1]
    ]  # Exclude the just-added message
    logger.debug(
        "Starting chat agent",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "model": conv.model,
            "history_length": len(history),
            "force_tools": force_tools,
        },
    )

    # Create agent and get response
    try:
        # Generate a unique request ID for capturing full tool results
        request_id = str(uuid.uuid4())
        set_current_request_id(request_id)
        # Set current message files for tools (like generate_image) to access
        set_current_message_files(files if files else None)
        # Set conversation context for tools (like retrieve_file) to access history
        set_conversation_context(conv_id, user.id)

        # If this is a planner conversation, fetch dashboard data for context
        dashboard_data = None
        if conv.is_planning:
            from dataclasses import asdict

            from src.agent.chat_agent import _planner_dashboard_context
            from src.utils.planner_data import build_planner_dashboard

            # Refresh calendar token if needed (expires hourly)
            calendar_token = _get_valid_calendar_access_token(user)

            dashboard_obj = build_planner_dashboard(
                todoist_token=user.todoist_access_token,
                calendar_token=calendar_token,
                user_id=user.id,
                force_refresh=False,
                db=db,
            )
            dashboard_data = asdict(dashboard_obj)
            # Set initial dashboard context for potential refresh_planner_dashboard tool calls
            _planner_dashboard_context.set(dashboard_data)

        agent = ChatAgent(
            model_name=conv.model, anonymous_mode=anonymous_mode, is_planning=conv.is_planning
        )
        raw_response, tool_results, usage_info = agent.chat_batch(
            message_text,
            files,
            history,
            force_tools=force_tools,
            user_name=user.name,
            user_id=user.id,
            custom_instructions=user.custom_instructions,
            is_planning=conv.is_planning,
            dashboard_data=dashboard_data,
        )

        # Get the FULL tool results (with _full_result) captured before stripping
        # This is needed for extracting generated images, as the tool_results from
        # chat_batch have already been stripped
        full_tool_results = get_full_tool_results(request_id)
        set_current_request_id(None)  # Clean up
        set_current_message_files(None)  # Clean up
        set_conversation_context(None, None)  # Clean up

        logger.debug(
            "Chat agent completed",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "response_length": len(raw_response),
                "tool_results_count": len(tool_results),
                "full_tool_results_count": len(full_tool_results),
                "input_tokens": usage_info.get("input_tokens", 0),
                "output_tokens": usage_info.get("output_tokens", 0),
                "usage_info": str(usage_info),
            },
        )

        # Extract metadata from response
        clean_response, metadata = extract_metadata_from_response(raw_response)
        sources, generated_images_meta = extract_metadata_fields(metadata)
        language = extract_language_from_metadata(metadata)
        logger.debug(
            "Extracted metadata",
            extra={
                "user_id": user.id,
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
            memory_ops = extract_memory_operations(metadata)
            if memory_ops:
                logger.debug(
                    "Processing memory operations",
                    extra={
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "operation_count": len(memory_ops),
                    },
                )
                process_memory_operations(user.id, memory_ops)

        # Extract generated files from FULL tool results (before stripping)
        # We need the full results because they contain the _full_result data
        gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
        code_output_files = extract_code_output_files_from_tool_results(full_tool_results)

        # Combine all generated files
        all_generated_files = gen_image_files + code_output_files
        if all_generated_files:
            logger.info(
                "Generated files extracted",
                extra={
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "image_count": len(gen_image_files),
                    "code_output_count": len(code_output_files),
                },
            )

        # Ensure we have at least some content or files to save
        # If response is empty but we have generated files, use a default message
        if not clean_response and all_generated_files:
            clean_response = Config.DEFAULT_IMAGE_GENERATION_MESSAGE

        # Save assistant message (with clean content, files, and metadata)
        logger.debug(
            "Saving assistant message",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        assistant_msg = db.add_message(
            conv_id,
            MessageRole.ASSISTANT,
            clean_response,
            files=all_generated_files if all_generated_files else None,
            sources=sources if sources else None,
            generated_images=generated_images_meta if generated_images_meta else None,
            language=language,
        )

        # Calculate and save cost (use full_tool_results for image generation cost)
        calculate_and_save_message_cost(
            assistant_msg.id,
            conv_id,
            user.id,
            conv.model,
            usage_info,
            full_tool_results,
            len(clean_response),
            mode="batch",
        )

        logger.info(
            "Batch chat completed",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "message_id": assistant_msg.id,
                "response_length": len(clean_response),
            },
        )
    except TimeoutError:
        logger.error(
            "Timeout in chat_batch",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
            },
            exc_info=True,
        )
        raise_llm_error("Request timed out. The AI took too long to respond. Please try again.")
    except Exception as e:
        # Log the error but don't expose internal details to users
        import traceback

        logger.error(
            "Error in chat_batch",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            exc_info=True,
        )
        # Check for common recoverable errors
        error_str = str(e).lower()
        if "timeout" in error_str or "timed out" in error_str:
            raise_llm_error("Request timed out. Please try again.")
        if "rate limit" in error_str or "quota" in error_str:
            raise_llm_error("AI service is busy. Please try again in a moment.")
        # Generic server error (don't expose internal details)
        raise_server_error("Failed to generate response. Please try again.")

    # Auto-generate title from first message if still default
    generated_title: str | None = None
    if conv.title == "New Conversation":
        logger.debug(
            "Auto-generating conversation title",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        generated_title = generate_title(message_text, clean_response)
        db.update_conversation(conv_id, user.id, title=generated_title)
        logger.debug(
            "Conversation title generated",
            extra={"user_id": user.id, "conversation_id": conv_id, "title": generated_title},
        )

    # Build response (include title if it was just generated, and user message ID for UI update)
    response_data = build_chat_response(
        assistant_msg,
        clean_response,
        gen_image_files,
        sources,
        generated_images_meta,
        conversation_title=generated_title,
        user_message_id=user_msg.id,
        language=language,
    )

    return response_data, 200


@api.route("/conversations/<conv_id>/chat/stream", methods=["POST"])
@api.doc(
    summary="Stream chat response via SSE",
    description="""Send a message and stream the response via Server-Sent Events.

Returns text/event-stream with the following event types:
- `thinking`: LLM thinking text (if enabled) - `{"type": "thinking", "text": "..."}`
- `tool_start`: Tool starting - `{"type": "tool_start", "tool": "web_search", "detail": "..."}`
- `tool_end`: Tool completed - `{"type": "tool_end", "tool": "web_search"}`
- `token`: Content token - `{"type": "token", "text": "..."}`
- `error`: Error occurred - `{"type": "error", "message": "...", "code": "...", "retryable": bool}`
- `done`: Stream complete with metadata - `{"type": "done", "id": "...", "created_at": "...", ...}`

Uses SSE keepalive heartbeats (`: keepalive` comments) to prevent proxy timeouts.
""",
    responses=[429],
)
@rate_limit_chat
@require_auth
@validate_request(ChatRequest)
def chat_stream(
    user: User, data: ChatRequest, conv_id: str
) -> Response | tuple[dict[str, str], int]:
    """Send a message and stream the response via Server-Sent Events.

    Accepts JSON body with:
    - message: str (optional if files present) - the text message
    - files: list[dict] (optional if message present) - array of {name, type, data} file objects
    - force_tools: list[str] (optional) - list of tool names to force (e.g. ["web_search"])

    Uses SSE keepalive heartbeats to prevent proxy timeouts during long LLM thinking phases.
    Keepalives are sent as SSE comments (: keepalive) which clients ignore but proxies see as activity.
    """
    logger.info("Stream chat request", extra={"user_id": user.id, "conversation_id": conv_id})
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for stream chat",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    message_text = data.message.strip()
    files = [f.model_dump() for f in data.files]  # Convert Pydantic models to dicts
    force_tools = data.force_tools
    anonymous_mode = data.anonymous_mode
    log_payload_snippet(
        logger,
        {
            "message_length": len(message_text),
            "file_count": len(files),
            "force_tools": force_tools,
            "anonymous_mode": anonymous_mode,
        },
    )

    # Content validation for files (base64 decoding, size) - structure already validated by Pydantic
    if files:
        logger.debug(
            "Validating files for stream",
            extra={"user_id": user.id, "conversation_id": conv_id, "file_count": len(files)},
        )
        is_valid, error = validate_files(files)
        if not is_valid:
            logger.warning(
                "File validation failed in stream",
                extra={
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "error": error,
                    "file_count": len(files),
                },
            )
            raise_validation_error(error or "File validation failed", field="files")
        # Mark images for background thumbnail generation
        logger.debug(
            "Marking image files for thumbnail generation in stream",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        files = mark_files_for_thumbnail_generation(files)

    # Save user message with separate content and files
    logger.debug(
        "Saving user message for stream",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_length": len(message_text),
            "file_count": len(files) if files else 0,
        },
    )
    user_msg = db.add_message(
        conv_id, MessageRole.USER, message_text, files=files if files else None
    )

    # Queue background thumbnail generation for pending files
    if files:
        queue_pending_thumbnails(user_msg.id, files)

    # Get conversation history for context
    # NOTE: We exclude files from history to avoid re-sending large base64 data for every message.
    # Only the current message files are sent to the LLM. Historical images are not needed
    # since the LLM has seen them before and they're stored in the conversation context.
    messages = db.get_messages(conv_id)
    history = [
        {"role": m.role.value, "content": m.content} for m in messages[:-1]
    ]  # Exclude the just-added message, exclude files from history
    logger.debug(
        "Starting stream chat agent",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "model": conv.model,
            "history_length": len(history),
            "force_tools": force_tools,
        },
    )

    # Generate a unique request ID for capturing full tool results
    stream_request_id = str(uuid.uuid4())

    def generate() -> Generator[str]:
        """Generator that streams tokens as SSE events with keepalive support.

        Uses a separate thread to stream LLM tokens into a queue, while the main
        generator loop sends keepalives when no tokens are available. This prevents
        proxy timeouts during the LLM's "thinking" phase before tokens start flowing.

        The stream_chat generator yields:
        - str: individual text tokens
        - tuple[str, dict, list]: final (clean_content, metadata, tool_results) after all tokens
        """
        # Set request ID for this streaming request to capture full tool results
        set_current_request_id(stream_request_id)
        # Set current message files for tools (like generate_image) to access
        set_current_message_files(files if files else None)
        # Set conversation context for tools (like retrieve_file) to access history
        set_conversation_context(conv_id, user.id)

        # If this is a planner conversation, fetch dashboard data for context
        dashboard_data = None
        if conv.is_planning:
            from dataclasses import asdict

            from src.agent.chat_agent import _planner_dashboard_context
            from src.utils.planner_data import build_planner_dashboard

            # Refresh calendar token if needed (expires hourly)
            calendar_token = _get_valid_calendar_access_token(user)

            dashboard_obj = build_planner_dashboard(
                todoist_token=user.todoist_access_token,
                calendar_token=calendar_token,
                user_id=user.id,
                force_refresh=False,
                db=db,
            )
            dashboard_data = asdict(dashboard_obj)
            # Set initial dashboard context for potential refresh_planner_dashboard tool calls
            _planner_dashboard_context.set(dashboard_data)

        # Use stream_chat_events for structured events including thinking/tool status
        agent = ChatAgent(
            model_name=conv.model,
            include_thoughts=True,
            anonymous_mode=anonymous_mode,
            is_planning=conv.is_planning,
        )
        event_queue: queue.Queue[dict[str, Any] | None | Exception] = queue.Queue()
        # Store user_id for use in nested functions
        stream_user_id = user.id

        # Shared state for final results (accessible from both threads)
        final_results: dict[str, Any] = {"ready": False}

        # Start streaming in background thread
        # Note: The thread sets its own request_id via set_current_request_id()
        stream_thread = threading.Thread(
            target=stream_events,
            args=(
                agent,
                event_queue,
                final_results,
                message_text,
                files,
                history,
                force_tools,
                user.name,
                user.id,
                user.custom_instructions,
                conv.is_planning,
                dashboard_data,
                conv_id,
                stream_request_id,
            ),
            daemon=False,
        )  # Non-daemon to ensure completion
        stream_thread.start()

        # Variables to capture final content, metadata, tool results, and usage info
        # (Defined here so they're in scope for both cleanup_and_save and save_message_to_db)
        clean_content = ""
        metadata: dict[str, Any] = {}
        tool_results: list[dict[str, Any]] = []
        usage_info: dict[str, Any] = {}
        client_connected = True  # Track if client is still connected

        # Start cleanup thread to ensure message is saved even if client disconnects
        # This thread waits for stream_thread to complete, then saves the message if generator didn't
        cleanup_thread = threading.Thread(
            target=cleanup_and_save,
            args=(
                stream_thread,
                final_results,
                conv_id,
                user.id,
                # Lambda to capture all the variables needed for save_message_to_db
                lambda: save_message_to_db(
                    final_results["clean_content"],
                    final_results["metadata"],
                    final_results["tool_results"],
                    final_results["usage_info"],
                    conv_id,
                    user.id,
                    stream_user_id,
                    conv.model,
                    message_text,
                    stream_request_id,
                    anonymous_mode,
                    client_connected,
                ),
            ),
            daemon=True,
        )
        cleanup_thread.start()

        # Send user_message_saved event FIRST so frontend can update temp ID immediately
        # This ensures image clicks work during streaming (before done event)
        try:
            yield f"data: {json.dumps({'type': 'user_message_saved', 'user_message_id': user_msg.id})}\n\n"
        except (BrokenPipeError, ConnectionError, OSError):
            # Client disconnected immediately - streaming will handle this
            pass

        try:
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    item = event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL)

                    if item is None:
                        # Stream completed successfully
                        break
                    elif isinstance(item, Exception):
                        # Error occurred - send structured error for frontend handling
                        error_str = str(item).lower()
                        if "timeout" in error_str or "timed out" in error_str:
                            error_data = {
                                "type": "error",
                                "code": "TIMEOUT",
                                "message": "Request timed out. Please try again.",
                                "retryable": True,
                            }
                        elif "rate limit" in error_str or "quota" in error_str:
                            error_data = {
                                "type": "error",
                                "code": "RATE_LIMITED",
                                "message": "AI service is busy. Please try again in a moment.",
                                "retryable": True,
                            }
                        else:
                            error_data = {
                                "type": "error",
                                "code": "SERVER_ERROR",
                                "message": "Failed to generate response. Please try again.",
                                "retryable": True,
                            }
                        # Try to send error event, but continue processing if client disconnected
                        try:
                            yield f"data: {json.dumps(error_data)}\n\n"
                        except (BrokenPipeError, ConnectionError, OSError):
                            # Client disconnected - error already logged in stream_thread
                            pass
                        return
                    elif isinstance(item, dict):
                        event_type = item.get("type")

                        if event_type == "final":
                            # Store final values for saving to DB
                            clean_content = item.get("content", "")
                            metadata = item.get("metadata", {})
                            tool_results = item.get("tool_results", [])
                            usage_info = item.get("usage_info", {})
                            # Don't yield final event - we handle done event separately below
                        elif event_type in (
                            "thinking",
                            "tool_start",
                            "tool_end",
                            "token",
                        ):
                            # Forward event to frontend
                            # Catch client disconnection errors but continue processing
                            try:
                                yield f"data: {json.dumps(item)}\n\n"
                            except (BrokenPipeError, ConnectionError, OSError) as e:
                                if client_connected:
                                    logger.warning(
                                        "Client disconnected during streaming",
                                        extra={
                                            "user_id": user.id,
                                            "conversation_id": conv_id,
                                            "event_type": event_type,
                                            "error": str(e),
                                        },
                                    )
                                    client_connected = False

                except queue.Empty:
                    # No event available, send keepalive comment
                    # SSE comments start with ":" and are ignored by clients
                    # Catch client disconnection errors but continue processing
                    try:
                        yield ": keepalive\n\n"
                    except (BrokenPipeError, ConnectionError, OSError) as e:
                        # Client disconnected - log but continue processing in background
                        if client_connected:
                            logger.warning(
                                "Client disconnected during keepalive",
                                extra={
                                    "user_id": user.id,
                                    "conversation_id": conv_id,
                                    "error": str(e),
                                },
                            )
                            client_connected = False
                        # Continue processing - background thread will complete and save to DB

            # Save message to DB (this will complete even if client disconnected)
            # Use try/finally to ensure this runs even if generator stops early
            try:
                # save_message_to_db returns extracted data for building the done event
                # This is important because get_full_tool_results() POPS the results,
                # so we can only retrieve them once (inside save_message_to_db)
                save_result = save_message_to_db(
                    clean_content,
                    metadata,
                    tool_results,
                    usage_info,
                    conv_id,
                    user.id,
                    stream_user_id,
                    conv.model,
                    message_text,
                    stream_request_id,
                    anonymous_mode,
                    client_connected,
                )

                # Build done event if we have the message (for client that's still connected)
                if client_connected and clean_content and save_result:
                    # Get the saved message from DB to get the ID
                    messages = db.get_messages(conv_id)
                    if messages and messages[-1].role == MessageRole.ASSISTANT:
                        assistant_msg = messages[-1]

                        # Use the extracted data from save_result instead of calling
                        # get_full_tool_results again (which would return empty list)
                        done_data = build_stream_done_event(
                            assistant_msg,
                            save_result.all_generated_files,
                            save_result.sources,
                            save_result.generated_images_meta,
                            conversation_title=save_result.generated_title,
                            user_message_id=user_msg.id,
                            language=save_result.language,
                        )

                        # Try to send done event, but continue even if client disconnected
                        try:
                            yield f"data: {json.dumps(done_data)}\n\n"
                        except (BrokenPipeError, ConnectionError, OSError) as e:
                            # Client disconnected - message is already saved to DB
                            logger.info(
                                "Client disconnected before done event, but message saved",
                                extra={
                                    "user_id": user.id,
                                    "conversation_id": conv_id,
                                    "message_id": assistant_msg.id,
                                    "error": str(e),
                                },
                            )
            finally:
                # Ensure stream thread completes (it's non-daemon so it will keep process alive)
                # But we don't want to block here if client disconnected
                pass

        except Exception as e:
            logger.error(
                "Error in stream generator",
                extra={
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            # Send structured error (don't expose internal details)
            # Try to send error event, but continue even if client disconnected
            error_data = {
                "type": "error",
                "code": "SERVER_ERROR",
                "message": "An error occurred while generating the response. Please try again.",
                "retryable": True,
            }
            try:
                yield f"data: {json.dumps(error_data)}\n\n"
            except (BrokenPipeError, ConnectionError, OSError) as e:
                # Client disconnected - error already logged
                logger.debug(
                    "Client disconnected before error event",
                    extra={
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "error": str(e),
                    },
                )

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
