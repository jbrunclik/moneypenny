"""Chat routes: Batch and streaming chat endpoints.

This module handles chat interactions with the AI agent, supporting both
batch (complete response) and streaming (SSE) modes.
"""

import base64
import re
import uuid

from apiflask import APIBlueprint
from flask import Response

from src.agent.agent import ChatAgent, generate_title
from src.agent.content import (
    extract_canvas_documents,
    extract_canvas_metadata,
    extract_metadata_from_response,
)
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import set_conversation_context, set_current_message_files
from src.api.errors import (
    raise_llm_error,
    raise_not_found_error,
    raise_server_error,
    raise_validation_error,
)
from src.api.rate_limiting import rate_limit_chat
from src.api.routes.calendar import _get_valid_calendar_access_token
from src.api.schemas import (
    CanvasDocument,
    CanvasListResponse,
    ChatBatchResponse,
    ChatRequest,
    MessageRole,
    UpdateCanvasRequest,
)
from src.api.utils import (
    build_chat_response,
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
from src.db.models.helpers import get_blob_store
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

            from src.agent.agent import _planner_dashboard_context
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

        # Extract canvas documents from response
        canvas_docs = extract_canvas_documents(raw_response)
        canvas_meta = extract_canvas_metadata(metadata)
        canvas_files = []

        # Create canvas files from extracted documents and metadata
        for idx, (doc, meta) in enumerate(zip(canvas_docs, canvas_meta)):
            title = meta.get("title", f"Document {idx+1}")
            canvas_file = {
                "name": f"{title}.md",
                "type": "text/canvas",
                "data": base64.b64encode(doc["content"].encode("utf-8")).decode("ascii"),
            }
            canvas_files.append(canvas_file)

        if canvas_files:
            logger.debug(
                "Canvas documents extracted",
                extra={
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "canvas_count": len(canvas_files),
                },
            )
            # Remove canvas blocks from response to keep chat clean
            clean_response = re.sub(r"```canvas\n.*?\n```\n*", "", clean_response, flags=re.DOTALL).strip()

        # Combine all generated files
        all_generated_files = gen_image_files + code_output_files + canvas_files
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
    from src.api.helpers.chat_streaming import create_stream_generator

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

    # Create the stream generator with all necessary context
    generator = create_stream_generator(
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

    return Response(
        generator,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@api.route("/messages/<message_id>/files/<int:file_index>", methods=["PUT"])
@require_auth
@validate_request(UpdateCanvasRequest)
def update_message_file(user: User, message_id: str, file_index: int, body: UpdateCanvasRequest):
    """Update canvas file content.

    Only allows editing text/canvas files. Verifies message ownership before update.

    Args:
        user: Authenticated user
        message_id: Message ID containing the file
        file_index: Index of file in message.files array
        body: Request body with new content

    Returns:
        Success message

    Raises:
        NotFoundError: If message not found
        ForbiddenError: If user doesn't own the message
        ValidationError: If file is not a canvas or index out of range
    """
    # Get message and verify existence
    message = db.get_message_by_id(message_id)
    if not message:
        raise_not_found_error("Message")

    # Verify ownership via conversation
    conversation = db.get_conversation(message.conversation_id)
    if not conversation or conversation.user_id != user.id:
        logger.warning(
            "Unauthorized canvas update attempt",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
            },
        )
        raise_forbidden_error("Not authorized to edit this message")

    # Verify file exists
    if not message.files or file_index >= len(message.files):
        raise_validation_error("File index out of range")

    # Verify file is canvas
    file_meta = message.files[file_index]
    if not file_meta.get("type", "").startswith("text/canvas"):
        raise_validation_error("Can only edit canvas files")

    # Update blob store
    try:
        blob_store = get_blob_store()
        blob_key = f"{message_id}/{file_index}"
        blob_store.save(
            blob_key,
            body.content.encode("utf-8"),
            mime_type="text/canvas",
        )
        logger.info(
            "Canvas file updated",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "file_index": file_index,
                "content_length": len(body.content),
            },
        )
    except Exception as e:
        logger.error(
            "Failed to update canvas file",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "file_index": file_index,
                "error": str(e),
            },
        )
        raise_server_error("Failed to update canvas file")

    return {"message": "Canvas updated successfully"}, 200


@api.route("/canvas", methods=["GET"])
@require_auth
def list_canvas_documents(user: User):
    """Get list of all canvas documents for the current user.

    Returns canvas documents across all conversations, sorted by most recent first.

    Args:
        user: Authenticated user

    Returns:
        List of canvas documents with metadata
    """
    # Get all user's conversations
    conversations = db.get_conversations_for_user(user.id)
    conv_map = {conv.id: conv.title for conv in conversations}

    canvas_list = []

    # Iterate through all conversations to find canvas files
    for conv in conversations:
        # Get all messages in conversation
        messages = db.get_messages(conv.id)

        for message in messages:
            if not message.files:
                continue

            # Check each file for canvas type
            for file_idx, file_meta in enumerate(message.files):
                file_type = file_meta.get("type", "")
                if file_type.startswith("text/canvas"):
                    # Extract title from filename
                    title = file_meta.get("name", f"Canvas {file_idx}").replace(".md", "")

                    canvas_list.append(
                        {
                            "message_id": message.id,
                            "file_index": file_idx,
                            "title": title,
                            "conversation_id": conv.id,
                            "conversation_title": conv.title,
                            "created_at": message.created_at.isoformat(),
                            "updated_at": message.created_at.isoformat(),  # TODO: Track actual updates
                        }
                    )

    # Sort by creation date (most recent first)
    canvas_list.sort(key=lambda x: x["created_at"], reverse=True)

    logger.info(
        "Canvas list retrieved",
        extra={
            "user_id": user.id,
            "canvas_count": len(canvas_list),
        },
    )

    return {"canvases": canvas_list, "total": len(canvas_list)}, 200
