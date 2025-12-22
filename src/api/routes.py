import base64
import json
import queue
import threading
from collections.abc import Generator
from typing import Any

from flask import Blueprint, Response, request

from src.agent.chat_agent import ChatAgent, generate_title
from src.auth.google_auth import GoogleAuthError, is_email_allowed, verify_google_id_token
from src.auth.jwt_auth import create_token, get_current_user, require_auth
from src.config import Config
from src.db.models import db
from src.utils.images import process_image_files


def validate_files(files: list[dict[str, Any]]) -> tuple[bool, str]:
    """Validate uploaded files against config limits.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(files) > Config.MAX_FILES_PER_MESSAGE:
        return False, f"Too many files. Maximum is {Config.MAX_FILES_PER_MESSAGE}"

    for file in files:
        # Check file type
        file_type = file.get("type", "")
        if file_type not in Config.ALLOWED_FILE_TYPES:
            return False, f"File type '{file_type}' is not allowed"

        # Check file size (base64 is ~4/3 larger than binary)
        data = file.get("data", "")
        try:
            decoded_size = len(base64.b64decode(data))
            if decoded_size > Config.MAX_FILE_SIZE:
                max_mb = Config.MAX_FILE_SIZE / (1024 * 1024)
                return False, f"File '{file.get('name', 'unknown')}' exceeds {max_mb:.0f}MB limit"
        except Exception:
            return False, "Invalid file data encoding"

    return True, ""


api = Blueprint("api", __name__, url_prefix="/api")
auth = Blueprint("auth", __name__, url_prefix="/auth")


# ============================================================================
# Auth Routes
# ============================================================================


@auth.route("/google", methods=["POST"])
def google_auth() -> tuple[dict[str, Any], int]:
    """Authenticate with Google ID token from Sign In with Google."""
    if Config.is_development():
        return {"error": "Authentication disabled in local mode"}, 400

    data = request.get_json() or {}
    id_token = data.get("credential")

    if not id_token:
        return {"error": "Missing credential"}, 400

    try:
        user_info = verify_google_id_token(id_token)
    except GoogleAuthError as e:
        return {"error": str(e)}, 401

    email = user_info.get("email", "")
    if not is_email_allowed(email):
        return {"error": "Email not authorized"}, 403

    # Create or get user
    user = db.get_or_create_user(
        email=email,
        name=user_info.get("name", email),
        picture=user_info.get("picture"),
    )

    # Generate JWT token
    token = create_token(user)

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
def get_client_id() -> dict[str, str]:
    """Return Google Client ID for frontend initialization."""
    return {"client_id": Config.GOOGLE_CLIENT_ID}


@auth.route("/me")
@require_auth
def me() -> dict[str, dict[str, str | None]]:
    """Get current user info."""
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
        }
    }


# ============================================================================
# Conversation Routes
# ============================================================================


@api.route("/conversations", methods=["GET"])
@require_auth
def list_conversations() -> dict[str, list[dict[str, str]]]:
    """List all conversations for the current user."""
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    conversations = db.list_conversations(user.id)
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in conversations
        ]
    }


@api.route("/conversations", methods=["POST"])
@require_auth
def create_conversation() -> tuple[dict[str, str], int]:
    """Create a new conversation."""
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    data = request.get_json() or {}
    model = data.get("model", Config.DEFAULT_MODEL)

    if model not in Config.MODELS:
        return {"error": f"Invalid model. Choose from: {list(Config.MODELS.keys())}"}, 400

    conv = db.create_conversation(user.id, model=model)
    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }, 201


@api.route("/conversations/<conv_id>", methods=["GET"])
@require_auth
def get_conversation(conv_id: str) -> tuple[dict[str, Any], int]:
    """Get a conversation with its messages.

    Optimized: Only includes file metadata, not thumbnails or full file data.
    Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail.
    Full files can be fetched via /api/messages/<message_id>/files/<file_index>.
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        return {"error": "Conversation not found"}, 404

    messages = db.get_messages(conv_id)

    # Optimize file data: only include metadata, not thumbnails or full file data
    # Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail
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
        # Add hasDetails flag for lazy loading (only check for assistant messages)
        if m.role == "assistant":
            msg_data["hasDetails"] = db.has_details(m.id)

        optimized_messages.append(msg_data)

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": optimized_messages,
    }, 200


@api.route("/conversations/<conv_id>", methods=["PATCH"])
@require_auth
def update_conversation(conv_id: str) -> tuple[dict[str, str], int]:
    """Update a conversation (title, model)."""
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    data = request.get_json() or {}
    title = data.get("title")
    model = data.get("model")

    if model and model not in Config.MODELS:
        return {"error": f"Invalid model. Choose from: {list(Config.MODELS.keys())}"}, 400

    if not db.update_conversation(conv_id, user.id, title=title, model=model):
        return {"error": "Conversation not found"}, 404

    return {"status": "updated"}, 200


@api.route("/conversations/<conv_id>", methods=["DELETE"])
@require_auth
def delete_conversation(conv_id: str) -> tuple[dict[str, str], int]:
    """Delete a conversation."""
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth

    if not db.delete_conversation(conv_id, user.id):
        return {"error": "Conversation not found"}, 404

    return {"status": "deleted"}, 200


# ============================================================================
# Chat Routes
# ============================================================================


@api.route("/conversations/<conv_id>/chat/batch", methods=["POST"])
@require_auth
def chat_batch(conv_id: str) -> tuple[dict[str, str], int]:
    """Send a message and get a complete response (non-streaming).

    Accepts JSON body with:
    - message: str (required) - the text message
    - files: list[dict] (optional) - array of {name, type, data} file objects
    - force_tools: list[str] (optional) - list of tool names to force (e.g. ["web_search"])
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        return {"error": "Conversation not found"}, 404

    data = request.get_json() or {}
    message_text = data.get("message", "").strip()
    files = data.get("files", [])
    force_tools = data.get("force_tools", [])

    if not message_text and not files:
        return {"error": "Message or files required"}, 400

    # Validate files if present
    if files:
        is_valid, error = validate_files(files)
        if not is_valid:
            return {"error": error}, 400
        # Generate thumbnails for images
        files = process_image_files(files)

    # Save user message with separate content and files
    db.add_message(conv_id, "user", message_text, files=files if files else None)

    # Get previous agent state
    previous_state = db.get_agent_state(conv_id)

    # Create agent and get response
    agent = ChatAgent(model_name=conv.model)
    response, new_state = agent.chat_with_state(
        message_text, files, previous_state, force_tools=force_tools
    )

    # Save response and state
    assistant_msg = db.add_message(conv_id, "assistant", response)
    db.save_agent_state(conv_id, new_state)

    # Auto-generate title from first message if still default
    if conv.title == "New Conversation":
        new_title = generate_title(message_text, response)
        db.update_conversation(conv_id, user.id, title=new_title)

    return {
        "id": assistant_msg.id,
        "role": "assistant",
        "content": response,
        "created_at": assistant_msg.created_at.isoformat(),
    }, 200


@api.route("/conversations/<conv_id>/chat/stream", methods=["POST"])
@require_auth
def chat_stream(conv_id: str) -> Response | tuple[dict[str, str], int]:
    """Send a message and stream the response via Server-Sent Events.

    Accepts JSON body with:
    - message: str (required) - the text message
    - files: list[dict] (optional) - array of {name, type, data} file objects
    - force_tools: list[str] (optional) - list of tool names to force (e.g. ["web_search"])

    Uses SSE keepalive heartbeats to prevent proxy timeouts during long LLM thinking phases.
    Keepalives are sent as SSE comments (: keepalive) which clients ignore but proxies see as activity.
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        return {"error": "Conversation not found"}, 404

    data = request.get_json() or {}
    message_text = data.get("message", "").strip()
    files = data.get("files", [])
    force_tools = data.get("force_tools", [])

    if not message_text and not files:
        return {"error": "Message or files required"}, 400

    # Validate files if present
    if files:
        is_valid, error = validate_files(files)
        if not is_valid:
            return {"error": error}, 400
        # Generate thumbnails for images
        files = process_image_files(files)

    # Save user message with separate content and files
    db.add_message(conv_id, "user", message_text, files=files if files else None)

    # Get conversation history for context
    messages = db.get_messages(conv_id)
    history = [
        {"role": m.role, "content": m.content, "files": m.files} for m in messages[:-1]
    ]  # Exclude the just-added message

    def generate() -> Generator[str, None, None]:
        """Generator that streams events as SSE with keepalive support.

        Uses a separate thread to stream events into a queue, while the main
        generator loop sends keepalives when no events are available. This prevents
        proxy timeouts during the LLM's "thinking" phase before tokens start flowing.

        Emits event types: token, thinking, tool_call, tool_result, done, error
        """
        # Create agent with thinking enabled for streaming
        agent = ChatAgent(model_name=conv.model, include_thinking=True)
        full_response = ""
        details: list[dict[str, Any]] = []  # Collect detail events for DB storage
        event_queue: queue.Queue[dict[str, Any] | None | Exception] = queue.Queue()
        stream_done = threading.Event()

        def stream_events() -> None:
            """Background thread that streams events into the queue."""
            try:
                for event in agent.stream_chat(
                    message_text, files, history, force_tools=force_tools
                ):
                    event_queue.put(event)
                event_queue.put(None)  # Signal completion
            except Exception as e:
                event_queue.put(e)  # Signal error
            finally:
                stream_done.set()

        # Start streaming in background thread
        stream_thread = threading.Thread(target=stream_events, daemon=True)
        stream_thread.start()

        try:
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    item = event_queue.get(timeout=Config.SSE_KEEPALIVE_INTERVAL)

                    if item is None:
                        # Stream completed successfully
                        break
                    elif isinstance(item, Exception):
                        # Error occurred
                        yield f"data: {json.dumps({'type': 'error', 'message': str(item)})}\n\n"
                        return
                    else:
                        # Got an event - forward to client and collect details
                        event_type = item.get("type")

                        if event_type == "token":
                            full_response += item.get("text", "")
                            yield f"data: {json.dumps(item)}\n\n"

                        elif event_type == "thinking":
                            # Store for DB and forward to client
                            details.append(
                                {
                                    "type": "thinking",
                                    "content": item.get("content", ""),
                                }
                            )
                            yield f"data: {json.dumps(item)}\n\n"

                        elif event_type == "tool_call":
                            # Store for DB and forward to client
                            details.append(
                                {
                                    "type": "tool_call",
                                    "id": item.get("id", ""),
                                    "name": item.get("name", ""),
                                    "args": item.get("args", {}),
                                }
                            )
                            yield f"data: {json.dumps(item)}\n\n"

                        elif event_type == "tool_result":
                            # Store for DB and forward to client
                            details.append(
                                {
                                    "type": "tool_result",
                                    "tool_call_id": item.get("tool_call_id", ""),
                                    "content": item.get("content", ""),
                                }
                            )
                            yield f"data: {json.dumps(item)}\n\n"

                except queue.Empty:
                    # No event available, send keepalive comment
                    # SSE comments start with ":" and are ignored by clients
                    yield ": keepalive\n\n"

            # Save complete response to DB with details
            assistant_msg = db.add_message(
                conv_id, "assistant", full_response, details=details if details else None
            )

            # Auto-generate title from first message if still default
            if conv.title == "New Conversation":
                new_title = generate_title(message_text, full_response)
                db.update_conversation(conv_id, user.id, title=new_title)

            # Include details in done event for streaming messages
            done_event: dict[str, Any] = {
                "type": "done",
                "id": assistant_msg.id,
                "created_at": assistant_msg.created_at.isoformat(),
            }
            if details:
                done_event["details"] = details

            yield f"data: {json.dumps(done_event)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

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
@require_auth
def list_models() -> dict[str, Any]:
    """List available models."""
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
@require_auth
def get_upload_config() -> dict[str, Any]:
    """Get file upload configuration for frontend."""
    return {
        "maxFileSize": Config.MAX_FILE_SIZE,
        "maxFilesPerMessage": Config.MAX_FILES_PER_MESSAGE,
        "allowedFileTypes": list(Config.ALLOWED_FILE_TYPES),
    }


# ============================================================================
# Image Routes
# ============================================================================


@api.route("/messages/<message_id>/files/<int:file_index>/thumbnail", methods=["GET"])
@require_auth
def get_message_thumbnail(
    message_id: str, file_index: int
) -> Response | tuple[dict[str, str], int]:
    """Get a thumbnail for an image file from a message.

    Returns the thumbnail as binary data with appropriate content-type header.
    Falls back to full image if thumbnail doesn't exist.
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        return {"error": "Message not found"}, 404

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        return {"error": "Not authorized"}, 403

    # Get the file
    if not message.files or file_index >= len(message.files):
        return {"error": "File not found"}, 404

    file = message.files[file_index]
    file_type = file.get("type", "application/octet-stream")

    # Check if it's an image
    if not file_type.startswith("image/"):
        return {"error": "File is not an image"}, 400

    # Prefer thumbnail, fall back to full image if thumbnail doesn't exist
    thumbnail_data = file.get("thumbnail")
    if thumbnail_data:
        try:
            binary_data = base64.b64decode(thumbnail_data)
            return Response(
                binary_data,
                mimetype=file_type,
                headers={
                    "Cache-Control": "private, max-age=31536000",  # Cache for 1 year
                },
            )
        except Exception:
            # Fall through to full image
            pass

    # Fall back to full image if no thumbnail
    file_data = file.get("data", "")
    if not file_data:
        return {"error": "Image data not found"}, 404

    try:
        binary_data = base64.b64decode(file_data)
        return Response(
            binary_data,
            mimetype=file_type,
            headers={
                "Cache-Control": "private, max-age=31536000",
            },
        )
    except Exception:
        return {"error": "Invalid image data"}, 500


@api.route("/messages/<message_id>/files/<int:file_index>", methods=["GET"])
@require_auth
def get_message_file(message_id: str, file_index: int) -> Response | tuple[dict[str, str], int]:
    """Get a full-size file from a message.

    Returns the file as binary data with appropriate content-type header.
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        return {"error": "Message not found"}, 404

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        return {"error": "Not authorized"}, 403

    # Get the file
    if not message.files or file_index >= len(message.files):
        return {"error": "File not found"}, 404

    file = message.files[file_index]
    file_data = file.get("data", "")
    file_type = file.get("type", "application/octet-stream")

    # Decode base64 and return as binary
    try:
        binary_data = base64.b64decode(file_data)
        return Response(
            binary_data,
            mimetype=file_type,
            headers={
                "Cache-Control": "private, max-age=31536000",  # Cache for 1 year
            },
        )
    except Exception:
        return {"error": "Invalid file data"}, 500


# ============================================================================
# Message Details Routes (lazy loading)
# ============================================================================


@api.route("/messages/<message_id>/details", methods=["GET"])
@require_auth
def get_message_details(message_id: str) -> tuple[dict[str, Any], int]:
    """Get details (thinking/tool events) for a message.

    Used for lazy loading details on historical messages.
    Returns the details array for the message.
    """
    user = get_current_user()
    assert user is not None  # Guaranteed by @require_auth

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        return {"error": "Message not found"}, 404

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        return {"error": "Not authorized"}, 403

    # Get details
    details = db.get_message_details(message_id)

    return {"details": details or []}, 200
