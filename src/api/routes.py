import base64
import binascii
import json
import queue
import threading
import uuid
from collections.abc import Generator
from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import Response, request

from src.agent.chat_agent import (
    ChatAgent,
    extract_metadata_from_response,
    generate_title,
    get_full_tool_results,
    set_current_request_id,
)
from src.agent.tools import set_current_message_files
from src.api.errors import (
    raise_auth_forbidden_error,
    raise_auth_invalid_error,
    raise_llm_error,
    raise_not_found_error,
    raise_server_error,
    raise_validation_error,
)
from src.api.schemas import (
    # Response schemas
    AuthResponse,
    ChatBatchResponse,
    # Request schemas
    ChatRequest,
    ClientIdResponse,
    ConversationCostResponse,
    ConversationDetailPaginatedResponse,
    ConversationResponse,
    ConversationsListPaginatedResponse,
    CostHistoryResponse,
    CreateConversationRequest,
    GoogleAuthRequest,
    HealthResponse,
    MemoriesListResponse,
    MessageCostResponse,
    # Enums
    MessageRole,
    MessagesListResponse,
    ModelsListResponse,
    MonthlyCostResponse,
    PaginationDirection,
    ReadinessResponse,
    StatusResponse,
    SyncResponse,
    ThumbnailStatus,
    TokenRefreshResponse,
    UpdateConversationRequest,
    UpdateSettingsRequest,
    UploadConfigResponse,
    UserContainerResponse,
    UserSettingsResponse,
    VersionResponse,
)
from src.api.utils import (
    build_chat_response,
    build_stream_done_event,
    calculate_and_save_message_cost,
    extract_memory_operations,
    extract_metadata_fields,
    normalize_generated_images,
    process_memory_operations,
)
from src.api.validation import validate_request
from src.auth.google_auth import GoogleAuthError, is_email_allowed, verify_google_id_token
from src.auth.jwt_auth import create_token, require_auth
from src.config import Config
from src.db.blob_store import get_blob_store
from src.db.models import User, db, make_blob_key, make_thumbnail_key
from src.utils.background_thumbnails import (
    generate_and_save_thumbnail,
    mark_files_for_thumbnail_generation,
    queue_pending_thumbnails,
)
from src.utils.costs import convert_currency, format_cost
from src.utils.files import validate_files
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
)
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

api = APIBlueprint("api", __name__, url_prefix="/api", tag="API")
auth = APIBlueprint("auth", __name__, url_prefix="/auth", tag="Auth")


# ============================================================================
# Auth Routes
# ============================================================================


@auth.route("/google", methods=["POST"])
@auth.output(AuthResponse, status_code=200)
@auth.doc(responses=[400, 401, 403])
@validate_request(GoogleAuthRequest)
def google_auth(data: GoogleAuthRequest) -> tuple[dict[str, Any], int]:
    """Authenticate with Google ID token from Sign In with Google."""
    logger.info("Google authentication request")
    if Config.is_development():
        logger.warning("Authentication attempted in development mode")
        raise_validation_error("Authentication disabled in local mode")

    id_token = data.credential

    try:
        logger.debug("Verifying Google ID token")
        user_info = verify_google_id_token(id_token)
        email = user_info.get("email", "")
        logger.debug("Google token verified", extra={"email": email})
    except GoogleAuthError as e:
        logger.warning("Google token verification failed", extra={"error": str(e)})
        raise_auth_invalid_error(str(e))

    if not is_email_allowed(email):
        logger.warning("Email not in whitelist", extra={"email": email})
        raise_auth_forbidden_error("Email not authorized")

    # Create or get user
    logger.debug("Getting or creating user", extra={"email": email})
    user = db.get_or_create_user(
        email=email,
        name=user_info.get("name", email),
        picture=user_info.get("picture"),
    )

    # Generate JWT token
    token = create_token(user)
    logger.info("Google authentication successful", extra={"user_id": user.id, "email": email})

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
        },
    }, 200


@auth.route("/client-id", methods=["GET"])
@auth.output(ClientIdResponse)
def get_client_id() -> dict[str, str]:
    """Return Google Client ID for frontend initialization."""
    return {"client_id": Config.GOOGLE_CLIENT_ID}


@auth.route("/me")
@auth.output(UserContainerResponse)
@require_auth
def me(user: User) -> dict[str, dict[str, str | None]]:
    """Get current user info."""
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
        }
    }


@auth.route("/refresh", methods=["POST"])
@auth.output(TokenRefreshResponse)
@require_auth
def refresh_token(user: User) -> dict[str, str]:
    """Refresh the JWT token.

    Returns a new token with extended expiration.
    The old token remains valid until its original expiration.
    """
    logger.info("Token refresh requested", extra={"user_id": user.id})
    token = create_token(user)
    logger.info("Token refreshed successfully", extra={"user_id": user.id})

    return {"token": token}


# ============================================================================
# Conversation Routes
# ============================================================================


@api.route("/conversations", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@require_auth
def list_conversations(user: User) -> dict[str, Any]:
    """List conversations for the current user with pagination.

    Query parameters:
    - limit: Number of conversations to return (default: 30, max: 100)
    - cursor: Cursor from previous page for fetching next page

    Returns paginated conversations with message_count for proper sync initialization.
    """
    # Parse pagination parameters
    limit_param = request.args.get("limit")
    cursor_param = request.args.get("cursor")

    # Validate and clamp limit
    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.CONVERSATIONS_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE
    else:
        limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE

    logger.debug(
        "Listing conversations",
        extra={"user_id": user.id, "limit": limit, "cursor": cursor_param},
    )

    # Get paginated results
    conversations, next_cursor, has_more, total_count = db.list_conversations_paginated(
        user.id, limit=limit, cursor=cursor_param
    )

    # We need message counts for sync initialization
    # Note: Currently fetches counts for all conversations; see TODO.md for optimization ideas
    conv_with_counts = db.list_conversations_with_message_count(user.id)
    count_map = {c.id: count for c, count in conv_with_counts}

    logger.info(
        "Conversations listed",
        extra={
            "user_id": user.id,
            "returned": len(conversations),
            "total": total_count,
            "has_more": has_more,
        },
    )

    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": count_map.get(c.id, 0),
            }
            for c in conversations
        ],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/conversations", methods=["POST"])
@api.output(ConversationResponse, status_code=201)
@require_auth
@validate_request(CreateConversationRequest)
def create_conversation(user: User, data: CreateConversationRequest) -> tuple[dict[str, str], int]:
    """Create a new conversation."""
    model = data.model or Config.DEFAULT_MODEL
    log_payload_snippet(logger, {"model": model})

    logger.debug("Creating conversation", extra={"user_id": user.id, "model": model})
    conv = db.create_conversation(user.id, model=model)
    logger.info(
        "Conversation created",
        extra={"user_id": user.id, "conversation_id": conv.id, "model": model},
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }, 201


@api.route("/conversations/<conv_id>", methods=["GET"])
@api.output(ConversationDetailPaginatedResponse)
@api.doc(responses=[404])
@require_auth
def get_conversation(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
    """Get a conversation with its messages (paginated).

    Query parameters for message pagination:
    - message_limit: Number of messages to return (default: 50, max: 200)
    - message_cursor: Cursor for fetching older/newer messages
    - direction: "older" (default) or "newer" for pagination direction

    By default, returns the newest messages.

    Optimized: Only includes file metadata, not thumbnails or full file data.
    Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail.
    Full files can be fetched via /api/messages/<message_id>/files/<file_index>.
    """
    # Parse message pagination parameters
    limit_param = request.args.get("message_limit")
    cursor_param = request.args.get("message_cursor")
    direction_param = request.args.get("direction", PaginationDirection.OLDER.value)

    # Validate and clamp limit
    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.MESSAGES_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.MESSAGES_DEFAULT_PAGE_SIZE
    else:
        limit = Config.MESSAGES_DEFAULT_PAGE_SIZE

    # Validate direction
    try:
        direction = PaginationDirection(direction_param)
    except ValueError:
        direction = PaginationDirection.OLDER

    logger.debug(
        "Getting conversation",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_limit": limit,
            "message_cursor": cursor_param,
            "direction": direction.value,
        },
    )
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    # Get paginated messages
    messages, pagination = db.get_messages_paginated(
        conv_id, limit=limit, cursor=cursor_param, direction=direction
    )
    logger.info(
        "Conversation retrieved",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_count": len(messages),
            "total_messages": pagination.total_count,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
        },
    )

    # Optimize file data: only include metadata, not thumbnails or full file data
    # Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail
    optimized_messages = _optimize_messages_for_response(messages)

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": optimized_messages,
        "message_pagination": {
            "older_cursor": pagination.older_cursor,
            "newer_cursor": pagination.newer_cursor,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
            "total_count": pagination.total_count,
        },
    }, 200


def _optimize_messages_for_response(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Message objects to optimized response format.

    Only includes file metadata (name, type, messageId, fileIndex), not full data.
    """
    optimized_messages = []
    for m in messages:
        optimized_files = []
        if m.files:
            for idx, file in enumerate(m.files):
                optimized_file = {
                    "name": file.get("name", ""),
                    "type": file.get("type", ""),
                    "messageId": m.id,
                    "fileIndex": idx,
                }
                optimized_files.append(optimized_file)

        msg_data: dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "files": optimized_files,
            "created_at": m.created_at.isoformat(),
        }
        if m.sources:
            msg_data["sources"] = m.sources
        if m.generated_images:
            # Normalize generated_images to ensure proper structure
            # (LLM sometimes returns just strings instead of {"prompt": "..."} objects)
            msg_data["generated_images"] = normalize_generated_images(m.generated_images)

        optimized_messages.append(msg_data)
    return optimized_messages


@api.route("/conversations/<conv_id>", methods=["PATCH"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
@validate_request(UpdateConversationRequest)
def update_conversation(
    user: User, data: UpdateConversationRequest, conv_id: str
) -> tuple[dict[str, str], int]:
    """Update a conversation (title, model)."""
    title = data.title
    model = data.model
    log_payload_snippet(logger, {"title": title, "model": model})

    logger.debug(
        "Updating conversation",
        extra={"user_id": user.id, "conversation_id": conv_id, "title": title, "model": model},
    )
    if not db.update_conversation(conv_id, user.id, title=title, model=model):
        logger.warning(
            "Conversation not found for update",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation updated", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "updated"}, 200


@api.route("/conversations/<conv_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Delete a conversation."""
    logger.debug("Deleting conversation", extra={"user_id": user.id, "conversation_id": conv_id})
    if not db.delete_conversation(conv_id, user.id):
        logger.warning(
            "Conversation not found for deletion",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation deleted", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "deleted"}, 200


@api.route("/messages/<message_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_message(user: User, message_id: str) -> tuple[dict[str, str], int]:
    """Delete a message.

    Deletes a single message and its associated files/thumbnails.
    The message must belong to a conversation owned by the authenticated user.
    Cost data is intentionally preserved for accurate reporting.
    """
    logger.debug("Deleting message", extra={"user_id": user.id, "message_id": message_id})
    if not db.delete_message(message_id, user.id):
        logger.warning(
            "Message not found for deletion",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    logger.info("Message deleted", extra={"user_id": user.id, "message_id": message_id})
    return {"status": "deleted"}, 200


@api.route("/conversations/<conv_id>/messages", methods=["GET"])
@api.output(MessagesListResponse)
@api.doc(responses=[404])
@require_auth
def get_messages(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
    """Get paginated messages for a conversation.

    This is a dedicated endpoint for fetching message pages, more efficient
    than the full conversation endpoint when only messages are needed.

    Query parameters:
    - limit: Number of messages to return (default: 50, max: 200)
    - cursor: Cursor for fetching older/newer messages
    - direction: "older" (default) or "newer" for pagination direction

    By default, returns the newest messages.
    """
    # Parse pagination parameters
    limit_param = request.args.get("limit")
    cursor_param = request.args.get("cursor")
    direction_param = request.args.get("direction", PaginationDirection.OLDER.value)

    # Validate and clamp limit
    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.MESSAGES_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.MESSAGES_DEFAULT_PAGE_SIZE
    else:
        limit = Config.MESSAGES_DEFAULT_PAGE_SIZE

    # Validate direction
    try:
        direction = PaginationDirection(direction_param)
    except ValueError:
        direction = PaginationDirection.OLDER

    logger.debug(
        "Getting messages",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "limit": limit,
            "cursor": cursor_param,
            "direction": direction.value,
        },
    )

    # Verify conversation exists and belongs to user
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    # Get paginated messages
    messages, pagination = db.get_messages_paginated(
        conv_id, limit=limit, cursor=cursor_param, direction=direction
    )

    logger.info(
        "Messages retrieved",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_count": len(messages),
            "total_messages": pagination.total_count,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
        },
    )

    # Optimize file data
    optimized_messages = _optimize_messages_for_response(messages)

    return {
        "messages": optimized_messages,
        "pagination": {
            "older_cursor": pagination.older_cursor,
            "newer_cursor": pagination.newer_cursor,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
            "total_count": pagination.total_count,
        },
    }, 200


@api.route("/conversations/sync", methods=["GET"])
@api.output(SyncResponse)
@require_auth
def sync_conversations(user: User) -> dict[str, Any]:
    """Sync conversations - returns conversations updated since a given timestamp.

    Query parameters:
    - since: ISO timestamp to get conversations updated after this time (optional)
    - full: If "true", returns all conversations for delete detection (optional)

    Returns:
    - conversations: List of conversation objects with message_count
    - server_time: Current server timestamp to use for next sync
    - is_full_sync: Whether this was a full sync (all conversations returned)
    """
    since_param = request.args.get("since")
    full_param = request.args.get("full", "false").lower() == "true"

    logger.debug(
        "Sync conversations request",
        extra={"user_id": user.id, "since": since_param, "full": full_param},
    )

    # Determine if this is a full sync or incremental
    is_full_sync = full_param or since_param is None

    if is_full_sync:
        # Full sync: get all conversations with message counts
        conv_with_counts = db.list_conversations_with_message_count(user.id)
    else:
        # Incremental sync: only get conversations updated since timestamp
        try:
            since_dt = datetime.fromisoformat(since_param)  # type: ignore[arg-type]
        except ValueError:
            raise_validation_error(
                "Invalid timestamp format. Use ISO format (e.g., 2024-01-01T12:00:00)",
                field="since",
            )
        conv_with_counts = db.get_conversations_updated_since(user.id, since_dt)

    server_time = datetime.now()

    logger.info(
        "Sync conversations completed",
        extra={
            "user_id": user.id,
            "is_full_sync": is_full_sync,
            "conversation_count": len(conv_with_counts),
        },
    )

    return {
        "conversations": [
            {
                "id": conv.id,
                "title": conv.title,
                "model": conv.model,
                "updated_at": conv.updated_at.isoformat(),
                "message_count": message_count,
            }
            for conv, message_count in conv_with_counts
        ],
        "server_time": server_time.isoformat(),
        "is_full_sync": is_full_sync,
    }


# ============================================================================
# Chat Routes
# ============================================================================


@api.route("/conversations/<conv_id>/chat/batch", methods=["POST"])
@api.output(ChatBatchResponse)
@api.doc(responses=[400, 404, 500])
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
    log_payload_snippet(
        logger,
        {"message_length": len(message_text), "file_count": len(files), "force_tools": force_tools},
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

        agent = ChatAgent(model_name=conv.model)
        raw_response, tool_results, usage_info = agent.chat_batch(
            message_text,
            files,
            history,
            force_tools=force_tools,
            user_name=user.name,
            user_id=user.id,
            custom_instructions=user.custom_instructions,
        )

        # Get the FULL tool results (with _full_result) captured before stripping
        # This is needed for extracting generated images, as the tool_results from
        # chat_batch have already been stripped
        full_tool_results = get_full_tool_results(request_id)
        set_current_request_id(None)  # Clean up
        set_current_message_files(None)  # Clean up

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
        logger.debug(
            "Extracted metadata",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "sources_count": len(sources) if sources else 0,
                "generated_images_count": len(generated_images_meta)
                if generated_images_meta
                else 0,
            },
        )

        # Process memory operations from metadata
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
)
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
    log_payload_snippet(
        logger,
        {"message_length": len(message_text), "file_count": len(files), "force_tools": force_tools},
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

        # Use stream_chat_events for structured events including thinking/tool status
        agent = ChatAgent(model_name=conv.model, include_thoughts=True)
        event_queue: queue.Queue[dict[str, Any] | None | Exception] = queue.Queue()
        # Store user_id for use in nested functions
        stream_user_id = user.id

        # Shared state for final results (accessible from both threads)
        final_results: dict[str, Any] = {"ready": False}

        def stream_events() -> None:
            """Background thread that streams events into the queue."""
            # Copy context from parent thread so contextvars are accessible
            set_current_request_id(stream_request_id)
            set_current_message_files(files if files else None)
            try:
                logger.debug(
                    "Stream thread started", extra={"user_id": user.id, "conversation_id": conv_id}
                )
                event_count = 0
                for event in agent.stream_chat_events(
                    message_text,
                    files,
                    history,
                    force_tools=force_tools,
                    user_name=user.name,
                    user_id=stream_user_id,
                    custom_instructions=user.custom_instructions,
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
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "event_count": event_count,
                    },
                )

                event_queue.put(None)  # Signal completion
            except Exception as e:
                logger.error(
                    "Stream thread error",
                    extra={"user_id": user.id, "conversation_id": conv_id, "error": str(e)},
                    exc_info=True,
                )
                event_queue.put(e)  # Signal error

        # Start streaming in background thread
        # Note: The thread sets its own request_id via set_current_request_id()
        stream_thread = threading.Thread(
            target=stream_events, daemon=False
        )  # Non-daemon to ensure completion
        stream_thread.start()

        # Start cleanup thread to ensure message is saved even if client disconnects
        # This thread waits for stream_thread to complete, then saves the message if generator didn't
        def cleanup_and_save() -> None:
            """Wait for stream thread to complete, then save message if generator stopped early."""
            try:
                # Wait for stream thread to complete (with timeout to prevent hanging forever)
                stream_thread.join(timeout=Config.STREAM_CLEANUP_THREAD_TIMEOUT)
                if stream_thread.is_alive():
                    logger.error(
                        "Stream thread did not complete within timeout",
                        extra={"user_id": user.id, "conversation_id": conv_id},
                    )
                    return

                # Wait a bit for generator to process final tuple (if client still connected)
                import time

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
                            extra={"user_id": user.id, "conversation_id": conv_id},
                        )
                        # Save the message using final results
                        save_message_to_db(
                            final_results["clean_content"],
                            final_results["metadata"],
                            final_results["tool_results"],
                            final_results["usage_info"],
                        )
            except Exception as e:
                logger.error(
                    "Error in cleanup thread",
                    extra={
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )

        cleanup_thread = threading.Thread(target=cleanup_and_save, daemon=True)
        cleanup_thread.start()

        # Send user_message_saved event FIRST so frontend can update temp ID immediately
        # This ensures image clicks work during streaming (before done event)
        try:
            yield f"data: {json.dumps({'type': 'user_message_saved', 'user_message_id': user_msg.id})}\n\n"
        except (BrokenPipeError, ConnectionError, OSError):
            # Client disconnected immediately - streaming will handle this
            pass

        # Variables to capture final content, metadata, tool results, and usage info
        clean_content = ""
        metadata: dict[str, Any] = {}
        tool_results: list[dict[str, Any]] = []
        usage_info: dict[str, Any] = {}
        client_connected = True  # Track if client is still connected

        # Define a type for the save result to make it clearer
        class SaveResult:
            """Result from save_message_to_db with extracted data for done event."""

            def __init__(
                self,
                message_id: str,
                sources: list[dict[str, str]],
                generated_images_meta: list[dict[str, str]],
                all_generated_files: list[dict[str, Any]],
                generated_title: str | None,
            ) -> None:
                self.message_id = message_id
                self.sources = sources
                self.generated_images_meta = generated_images_meta
                self.all_generated_files = all_generated_files
                self.generated_title = generated_title

        def save_message_to_db(
            content: str,
            meta: dict[str, Any],
            tools: list[dict[str, Any]],
            usage: dict[str, Any],
        ) -> SaveResult | None:
            """Save message to database. Called from both generator and cleanup thread.

            Returns SaveResult with extracted data for building done event, or None on error.
            """
            try:
                # Extract metadata fields
                sources, generated_images_meta = extract_metadata_fields(meta)
                logger.debug(
                    "Extracted metadata from stream",
                    extra={
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "sources_count": len(sources) if sources else 0,
                        "generated_images_count": len(generated_images_meta)
                        if generated_images_meta
                        else 0,
                    },
                )

                # Process memory operations from metadata
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

                # Extract generated files from FULL tool results (before stripping)
                gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
                code_output_files = extract_code_output_files_from_tool_results(full_tool_results)

                # Combine all generated files
                all_generated_files = gen_image_files + code_output_files
                if all_generated_files:
                    logger.info(
                        "Generated files extracted from stream",
                        extra={
                            "user_id": user.id,
                            "conversation_id": conv_id,
                            "image_count": len(gen_image_files),
                            "code_output_count": len(code_output_files),
                        },
                    )

                # Save complete response to DB
                logger.debug(
                    "Saving assistant message from stream",
                    extra={"user_id": user.id, "conversation_id": conv_id},
                )
                assistant_msg = db.add_message(
                    conv_id,
                    MessageRole.ASSISTANT,
                    content,
                    files=all_generated_files if all_generated_files else None,
                    sources=sources if sources else None,
                    generated_images=generated_images_meta if generated_images_meta else None,
                )

                # Calculate and save cost for streaming (use full_tool_results for image cost)
                calculate_and_save_message_cost(
                    assistant_msg.id,
                    conv_id,
                    user.id,
                    conv.model,
                    usage,
                    full_tool_results,
                    len(content),
                    mode="stream",
                )

                # Auto-generate title from first message if still default
                generated_title: str | None = None
                if conv.title == "New Conversation":
                    logger.debug(
                        "Auto-generating conversation title from stream",
                        extra={"user_id": user.id, "conversation_id": conv_id},
                    )
                    generated_title = generate_title(message_text, content)
                    db.update_conversation(conv_id, user.id, title=generated_title)
                    logger.debug(
                        "Conversation title generated from stream",
                        extra={
                            "user_id": user.id,
                            "conversation_id": conv_id,
                            "title": generated_title,
                        },
                    )

                logger.info(
                    "Stream chat completed and saved",
                    extra={
                        "user_id": user.id,
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
                )
            except Exception as e:
                logger.error(
                    "Error saving stream message to DB",
                    extra={
                        "user_id": user.id,
                        "conversation_id": conv_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                return None

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
                        elif event_type in ("thinking", "tool_start", "tool_end", "token"):
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
                save_result = save_message_to_db(clean_content, metadata, tool_results, usage_info)

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


# ============================================================================
# Models Routes
# ============================================================================


@api.route("/models", methods=["GET"])
@api.output(ModelsListResponse)
@require_auth
def list_models(user: User) -> dict[str, Any]:
    """List available models."""
    # user parameter required by @require_auth but not used in this endpoint
    _ = user
    return {
        "models": [
            {"id": model_id, "name": model_name} for model_id, model_name in Config.MODELS.items()
        ],
        "default": Config.DEFAULT_MODEL,
    }


# ============================================================================
# Config Routes
# ============================================================================


@api.route("/config/upload", methods=["GET"])
@api.output(UploadConfigResponse)
@require_auth
def get_upload_config(user: User) -> dict[str, Any]:
    """Get file upload configuration for frontend."""
    # user parameter required by @require_auth but not used in this endpoint
    _ = user
    return {
        "maxFileSize": Config.MAX_FILE_SIZE,
        "maxFilesPerMessage": Config.MAX_FILES_PER_MESSAGE,
        "allowedFileTypes": list(Config.ALLOWED_FILE_TYPES),
    }


# ============================================================================
# Version Routes
# ============================================================================


@api.route("/version", methods=["GET"])
@api.output(VersionResponse)
def get_version() -> dict[str, str | None]:
    """Get current app version (JS bundle hash).

    This endpoint does not require authentication so version can be
    checked even before login. Used by frontend to detect when a new
    version is deployed and prompt users to reload.
    """
    from flask import current_app

    return {"version": current_app.config.get("APP_VERSION")}


# ============================================================================
# Health Check Routes
# ============================================================================


@api.route("/health", methods=["GET"])
@api.output(HealthResponse)
def health_check() -> tuple[dict[str, str | None], int]:
    """Liveness probe - checks if the application process is running.

    This endpoint should NOT check external dependencies (database, APIs).
    It only verifies the Flask application is responding to requests.

    Use /api/ready for readiness checks that verify dependencies.

    Returns:
        200: Application is alive and responding
    """
    from flask import current_app

    return {
        "status": "ok",
        "version": current_app.config.get("APP_VERSION"),
    }, 200


@api.route("/ready", methods=["GET"])
@api.output(ReadinessResponse)
@api.doc(responses=[503])
def readiness_check() -> tuple[dict[str, Any], int]:
    """Readiness probe - checks if the application can serve traffic.

    Verifies that all dependencies (database) are accessible.
    Use this for load balancer health checks that should remove
    unhealthy instances from the pool.

    Returns:
        200: Application is ready to serve traffic
        503: Application is not ready (dependency failure)
    """
    from flask import current_app

    from src.db.models import check_database_connectivity

    checks: dict[str, dict[str, Any]] = {}
    is_ready = True

    # Check database connectivity
    db_ok, db_error = check_database_connectivity()
    checks["database"] = {
        "status": "ok" if db_ok else "error",
        "message": "Connected" if db_ok else db_error,
    }
    if not db_ok:
        is_ready = False
        logger.error("Readiness check failed: database", extra={"error": db_error})

    response = {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
        "version": current_app.config.get("APP_VERSION"),
    }

    status_code = 200 if is_ready else 503
    if is_ready:
        logger.debug("Readiness check passed")
    else:
        logger.warning("Readiness check failed", extra={"checks": checks})

    return response, status_code


# ============================================================================
# Image Routes
# ============================================================================


@api.route("/messages/<message_id>/files/<int:file_index>/thumbnail", methods=["GET"])
@api.doc(
    summary="Get thumbnail for an image file",
    description="Returns thumbnail binary data (200) or pending status (202).",
    responses=[202, 403, 404],
)
@require_auth
def get_message_thumbnail(
    user: User, message_id: str, file_index: int
) -> Response | tuple[dict[str, Any], int]:
    """Get a thumbnail for an image file from a message.

    Thumbnails are stored in the blob store (files.db).

    Returns:
        - 200 with thumbnail binary data when ready
        - 202 with {"status": "pending"} when thumbnail is still being generated
        - Falls back to full image if thumbnail generation failed
    """
    logger.debug(
        "Getting thumbnail",
        extra={"user_id": user.id, "message_id": message_id, "file_index": file_index},
    )

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning("Message not found for thumbnail", extra={"message_id": message_id})
        raise_not_found_error("Message")

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Unauthorized thumbnail access", extra={"user_id": user.id, "message_id": message_id}
        )
        raise_auth_forbidden_error("Not authorized to access this resource")

    # Get the file metadata
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "File not found for thumbnail",
            extra={"message_id": message_id, "file_index": file_index},
        )
        raise_not_found_error("File")

    file = message.files[file_index]
    file_type = file.get("type", "application/octet-stream")

    # Check if it's an image
    if not file_type.startswith("image/"):
        logger.warning(
            "Non-image file requested as thumbnail",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_type": file_type,
            },
        )
        raise_validation_error("File is not an image", field="file_type")

    blob_store = get_blob_store()

    # Check thumbnail status (default to "ready" for legacy messages without status)
    thumbnail_status = file.get("thumbnail_status", ThumbnailStatus.READY.value)

    # Handle pending thumbnail with stale recovery
    if thumbnail_status == ThumbnailStatus.PENDING.value:
        # Check if message is old enough that generation should have completed
        # If pending for more than threshold, assume the worker died and regenerate synchronously
        message_age = (datetime.now() - message.created_at).total_seconds()
        if message_age > Config.THUMBNAIL_STALE_THRESHOLD_SECONDS:
            logger.warning(
                "Stale pending thumbnail detected, regenerating synchronously",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "file_index": file_index,
                    "message_age_seconds": message_age,
                    "threshold_seconds": Config.THUMBNAIL_STALE_THRESHOLD_SECONDS,
                },
            )
            # Get full image from blob store for regeneration
            blob_key = make_blob_key(message_id, file_index)
            blob_result = blob_store.get(blob_key)
            if blob_result:
                file_bytes, _ = blob_result
                file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
                # Regenerate synchronously (one-time recovery) using shared helper
                thumbnail = generate_and_save_thumbnail(
                    message_id, file_index, file_data_b64, file_type
                )
                if thumbnail:
                    try:
                        binary_data = base64.b64decode(thumbnail)
                        return Response(
                            binary_data,
                            mimetype="image/jpeg",
                            headers={"Cache-Control": "private, max-age=31536000"},
                        )
                    except binascii.Error:
                        pass  # Fall through to full image
            # Fall through to full image fallback below
        else:
            # Not stale yet - return 202 to signal frontend to poll
            logger.debug(
                "Thumbnail pending, returning 202",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "file_index": file_index,
                    "message_age_seconds": message_age,
                },
            )
            return {"status": "pending"}, 202

    # Try to get thumbnail from blob store
    has_thumbnail = file.get("has_thumbnail", False)
    # Also check legacy "thumbnail" field for migration compatibility
    has_legacy_thumbnail = "thumbnail" in file and file["thumbnail"]

    if has_thumbnail or has_legacy_thumbnail:
        # Try blob store first (new format)
        thumb_key = make_thumbnail_key(message_id, file_index)
        thumb_result = blob_store.get(thumb_key)
        if thumb_result:
            binary_data, mime_type = thumb_result
            logger.debug(
                "Returning thumbnail from blob store",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=mime_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )

        # Try legacy base64 thumbnail (for unmigrated messages)
        if has_legacy_thumbnail:
            try:
                binary_data = base64.b64decode(file["thumbnail"])
                logger.debug(
                    "Returning legacy thumbnail",
                    extra={
                        "user_id": user.id,
                        "message_id": message_id,
                        "conversation_id": message.conversation_id,
                        "file_index": file_index,
                        "size": len(binary_data),
                    },
                )
                return Response(
                    binary_data,
                    mimetype="image/jpeg",
                    headers={"Cache-Control": "private, max-age=31536000"},
                )
            except binascii.Error as e:
                logger.warning(
                    "Failed to decode legacy thumbnail",
                    extra={"message_id": message_id, "error": str(e)},
                )

    # Fall back to full image from blob store
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)
    if blob_result:
        binary_data, mime_type = blob_result
        logger.debug(
            "Returning full image as thumbnail fallback",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
                "size": len(binary_data),
            },
        )
        return Response(
            binary_data,
            mimetype=mime_type,
            headers={"Cache-Control": "private, max-age=31536000"},
        )

    # Try legacy base64 data (for unmigrated messages)
    file_data = file.get("data", "")
    if file_data:
        try:
            binary_data = base64.b64decode(file_data)
            logger.debug(
                "Returning legacy full image as thumbnail fallback",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=file_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )
        except binascii.Error as e:
            logger.error("Failed to decode legacy image data", extra={"error": str(e)})

    logger.warning(
        "No image data found for thumbnail",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "conversation_id": message.conversation_id,
            "file_index": file_index,
        },
    )
    raise_not_found_error("Image data")


@api.route("/messages/<message_id>/files/<int:file_index>", methods=["GET"])
@api.doc(
    summary="Get full file from a message",
    description="Returns the file as binary data with appropriate content-type header.",
    responses=[403, 404],
)
@require_auth
def get_message_file(
    user: User, message_id: str, file_index: int
) -> Response | tuple[dict[str, str], int]:
    """Get a full-size file from a message.

    Files are stored in the blob store (files.db).
    Falls back to legacy base64 data for unmigrated messages.

    Returns the file as binary data with appropriate content-type header.
    """
    logger.debug(
        "Getting file",
        extra={"user_id": user.id, "message_id": message_id, "file_index": file_index},
    )

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "Message not found for file", extra={"user_id": user.id, "message_id": message_id}
        )
        raise_not_found_error("Message")

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Unauthorized file access",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
            },
        )
        raise_auth_forbidden_error("Not authorized to access this resource")

    # Get the file metadata
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "File not found",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
            },
        )
        raise_not_found_error("File")

    file = message.files[file_index]
    file_type = file.get("type", "application/octet-stream")

    # Try blob store first (new format)
    blob_store = get_blob_store()
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)
    if blob_result:
        binary_data, mime_type = blob_result
        logger.debug(
            "Returning file from blob store",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
                "file_type": mime_type,
                "size": len(binary_data),
            },
        )
        return Response(
            binary_data,
            mimetype=mime_type,
            headers={"Cache-Control": "private, max-age=31536000"},
        )

    # Fall back to legacy base64 data (for unmigrated messages)
    file_data = file.get("data", "")
    if file_data:
        try:
            binary_data = base64.b64decode(file_data)
            logger.debug(
                "Returning legacy file",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "file_type": file_type,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=file_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )
        except binascii.Error as e:
            logger.error("Failed to decode legacy file data", extra={"error": str(e)})

    logger.warning(
        "No file data found",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "conversation_id": message.conversation_id,
            "file_index": file_index,
        },
    )
    raise_not_found_error("File data")


# ============================================================================
# Cost Tracking Routes
# ============================================================================


@api.route("/conversations/<conv_id>/cost", methods=["GET"])
@api.output(ConversationCostResponse)
@api.doc(responses=[404])
@require_auth
def get_conversation_cost(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
    """Get total cost for a conversation."""
    logger.debug(
        "Getting conversation cost", extra={"user_id": user.id, "conversation_id": conv_id}
    )

    # Verify conversation belongs to user
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for cost query",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    cost_usd = db.get_conversation_cost(conv_id)
    cost_display = convert_currency(cost_usd, Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    logger.info(
        "Conversation cost retrieved",
        extra={"user_id": user.id, "conversation_id": conv_id, "cost_usd": cost_usd},
    )

    return {
        "conversation_id": conv_id,
        "cost_usd": cost_usd,
        "cost": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
    }, 200


@api.route("/messages/<message_id>/cost", methods=["GET"])
@api.output(MessageCostResponse)
@api.doc(responses=[404])
@require_auth
def get_message_cost(user: User, message_id: str) -> tuple[dict[str, Any], int]:
    """Get cost for a specific message."""
    logger.debug("Getting message cost", extra={"user_id": user.id, "message_id": message_id})

    # Verify message belongs to user
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "Message not found for cost query",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for message cost query",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
            },
        )
        raise_not_found_error("Message")

    cost_data = db.get_message_cost(message_id)
    if not cost_data:
        logger.debug(
            "No cost data found for message",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Cost data for this message")

    cost_display = convert_currency(cost_data["cost_usd"], Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    image_gen_cost_usd = cost_data.get("image_generation_cost_usd", 0.0)
    image_gen_cost_display = convert_currency(image_gen_cost_usd, Config.COST_CURRENCY)
    image_gen_cost_formatted = (
        format_cost(image_gen_cost_display, Config.COST_CURRENCY)
        if image_gen_cost_usd > 0
        else None
    )

    logger.info(
        "Message cost retrieved",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "cost_usd": cost_data["cost_usd"],
            "image_generation_cost_usd": image_gen_cost_usd,
        },
    )

    response = {
        "message_id": message_id,
        "cost_usd": cost_data["cost_usd"],
        "cost": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
        "input_tokens": cost_data["input_tokens"],
        "output_tokens": cost_data["output_tokens"],
        "model": cost_data["model"],
    }

    if image_gen_cost_usd > 0:
        response["image_generation_cost_usd"] = image_gen_cost_usd
        response["image_generation_cost"] = image_gen_cost_display
        response["image_generation_cost_formatted"] = image_gen_cost_formatted

    return response, 200


@api.route("/users/me/costs/monthly", methods=["GET"])
@api.output(MonthlyCostResponse)
@api.doc(responses=[400])
@require_auth
def get_user_monthly_cost(user: User) -> tuple[dict[str, Any], int]:
    """Get cost for the current user in a specific month."""
    # Get year and month from query params (default to current month)
    now = datetime.now()
    year = request.args.get("year", type=int) or now.year
    month = request.args.get("month", type=int) or now.month

    # Validate month range
    if not (1 <= month <= 12):
        logger.warning(
            "Invalid month in request",
            extra={"user_id": user.id, "year": year, "month": month},
        )
        raise_validation_error("Month must be between 1 and 12", field="month")

    logger.debug(
        "Getting user monthly cost",
        extra={"user_id": user.id, "year": year, "month": month},
    )

    cost_data = db.get_user_monthly_cost(user.id, year, month)
    cost_display = convert_currency(cost_data["total_usd"], Config.COST_CURRENCY)
    formatted_cost = format_cost(cost_display, Config.COST_CURRENCY)

    # Convert breakdown to display currency
    breakdown_display = {}
    for model, data in cost_data["breakdown"].items():
        breakdown_display[model] = {
            "total": convert_currency(data["total_usd"], Config.COST_CURRENCY),
            "total_usd": data["total_usd"],
            "message_count": data["message_count"],
            "formatted": format_cost(
                convert_currency(data["total_usd"], Config.COST_CURRENCY), Config.COST_CURRENCY
            ),
        }

    logger.info(
        "User monthly cost retrieved",
        extra={
            "user_id": user.id,
            "year": year,
            "month": month,
            "total_usd": cost_data["total_usd"],
            "message_count": cost_data["message_count"],
        },
    )

    return {
        "user_id": user.id,
        "year": year,
        "month": month,
        "total_usd": cost_data["total_usd"],
        "total": cost_display,
        "currency": Config.COST_CURRENCY,
        "formatted": formatted_cost,
        "message_count": cost_data["message_count"],
        "breakdown": breakdown_display,
    }, 200


@api.route("/users/me/costs/history", methods=["GET"])
@api.output(CostHistoryResponse)
@require_auth
def get_user_cost_history(user: User) -> tuple[dict[str, Any], int]:
    """Get monthly cost history for the current user."""
    limit = request.args.get("limit", type=int) or Config.COST_HISTORY_DEFAULT_LIMIT
    # Cap limit to prevent performance issues
    limit = min(limit, Config.COST_HISTORY_MAX_MONTHS)
    logger.debug("Getting user cost history", extra={"user_id": user.id, "limit": limit})

    history = db.get_user_cost_history(user.id, limit)

    # Get current month
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Convert each month's cost to display currency
    history_display = []
    current_month_in_history = False
    for month_data in history:
        year = month_data["year"]
        month = month_data["month"]

        # Check if this is the current month
        if year == current_year and month == current_month:
            current_month_in_history = True

        cost_display = convert_currency(month_data["total_usd"], Config.COST_CURRENCY)
        history_display.append(
            {
                "year": year,
                "month": month,
                "total_usd": month_data["total_usd"],
                "total": cost_display,
                "currency": Config.COST_CURRENCY,
                "formatted": format_cost(cost_display, Config.COST_CURRENCY),
                "message_count": month_data["message_count"],
            }
        )

    # If current month is not in history, add it with $0 cost
    if not current_month_in_history:
        history_display.insert(
            0,
            {
                "year": current_year,
                "month": current_month,
                "total_usd": 0.0,
                "total": 0.0,
                "currency": Config.COST_CURRENCY,
                "formatted": format_cost(0.0, Config.COST_CURRENCY),
                "message_count": 0,
            },
        )

    logger.info(
        "User cost history retrieved",
        extra={"user_id": user.id, "months_count": len(history_display)},
    )

    return {
        "user_id": user.id,
        "history": history_display,
    }, 200


# ============================================================================
# Settings Routes
# ============================================================================


@api.route("/users/me/settings", methods=["GET"])
@api.output(UserSettingsResponse)
@require_auth
def get_user_settings(user: User) -> dict[str, Any]:
    """Get user settings including custom instructions."""
    logger.debug("Getting user settings", extra={"user_id": user.id})
    return {
        "custom_instructions": user.custom_instructions or "",
    }


@api.route("/users/me/settings", methods=["PATCH"])
@api.output(StatusResponse)
@require_auth
@validate_request(UpdateSettingsRequest)
def update_user_settings(user: User, data: UpdateSettingsRequest) -> tuple[dict[str, str], int]:
    """Update user settings."""
    logger.debug(
        "Updating user settings",
        extra={
            "user_id": user.id,
            "has_custom_instructions": data.custom_instructions is not None,
        },
    )

    if data.custom_instructions is not None:
        # Normalize empty/whitespace-only strings to None
        instructions = data.custom_instructions.strip() if data.custom_instructions else None
        db.update_user_custom_instructions(user.id, instructions)
        logger.info(
            "User settings updated",
            extra={"user_id": user.id, "has_instructions": bool(instructions)},
        )

    return {"status": "updated"}, 200


# ============================================================================
# Memory Routes
# ============================================================================


@api.route("/memories", methods=["GET"])
@api.output(MemoriesListResponse)
@require_auth
def list_memories(user: User) -> dict[str, Any]:
    """List all memories for the current user."""
    logger.debug("Listing memories", extra={"user_id": user.id})
    memories = db.list_memories(user.id)
    logger.info(
        "Memories listed",
        extra={"user_id": user.id, "count": len(memories)},
    )
    return {
        "memories": [
            {
                "id": m.id,
                "content": m.content,
                "category": m.category,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]
    }


@api.route("/memories/<memory_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_memory(user: User, memory_id: str) -> tuple[dict[str, str], int]:
    """Delete a memory."""
    logger.debug("Deleting memory", extra={"user_id": user.id, "memory_id": memory_id})
    if not db.delete_memory(memory_id, user.id):
        logger.warning(
            "Memory not found for deletion",
            extra={"user_id": user.id, "memory_id": memory_id},
        )
        raise_not_found_error("Memory")

    logger.info("Memory deleted", extra={"user_id": user.id, "memory_id": memory_id})
    return {"status": "deleted"}, 200
