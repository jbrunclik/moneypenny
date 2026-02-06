"""API response building utilities."""

import json
from typing import Any

from flask import Request

from src.db.models import db
from src.utils.costs import calculate_total_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_request_json(request: Request) -> dict[str, Any] | None:
    """Safely get JSON from request body.

    Args:
        request: Flask request object

    Returns:
        Parsed JSON dict, or None if parsing fails or request has no JSON.
        Returns empty dict if silent=True and no JSON body.

    Note:
        This function catches JSONDecodeError to prevent 500 errors from
        malformed JSON requests. Callers should handle None return by
        using the invalid_json_error() response.

        HTTPException subclasses (like RequestEntityTooLarge for 413) are
        re-raised so Flask can handle them with proper error responses.
    """
    from werkzeug.exceptions import HTTPException

    try:
        return request.get_json(silent=True) or {}
    except HTTPException:
        # Re-raise HTTP exceptions (e.g., 413 Request Entity Too Large)
        # so Flask's error handler can return the appropriate response
        raise
    except Exception:
        # Catches any JSON parsing errors
        return None


def normalize_generated_images(
    generated_images: list[Any] | None,
) -> list[dict[str, str]]:
    """Normalize generated_images to ensure each item has proper structure.

    The LLM sometimes returns just prompt strings instead of {"prompt": "..."}
    objects. This function normalizes both formats.

    Args:
        generated_images: List of generated image metadata, may contain strings or dicts

    Returns:
        List of dicts with "prompt" key
    """
    if not generated_images:
        return []

    normalized = []
    for item in generated_images:
        if isinstance(item, str):
            # LLM returned just the prompt string
            normalized.append({"prompt": item})
        elif isinstance(item, dict) and "prompt" in item:
            # Already in correct format
            normalized.append(item)
        # Skip invalid items silently
    return normalized


def extract_metadata_fields(
    metadata: dict[str, Any] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Extract sources and generated_images from metadata dict.

    Args:
        metadata: Metadata dict from extract_metadata_from_response, or None

    Returns:
        Tuple of (sources list, generated_images list)
    """
    if not metadata:
        return [], []
    sources = metadata.get("sources", [])
    generated_images = normalize_generated_images(metadata.get("generated_images", []))
    return sources, generated_images


def extract_language_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    """Extract language code from metadata dict.

    Args:
        metadata: Metadata dict from extract_metadata_from_response, or None

    Returns:
        ISO 639-1 language code (e.g., "en", "cs") or None if not present
    """
    if not metadata:
        return None
    language = metadata.get("language")
    if language and isinstance(language, str):
        # Normalize to lowercase and handle edge cases like "EN" or "en-US"
        normalized: str = language.lower().split("-")[0][:2]
        return normalized
    return None


def extract_memory_operations(
    metadata: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Extract memory operations from metadata dict.

    Memory operations allow the LLM to add, update, or delete user memories.

    Args:
        metadata: Metadata dict from extract_metadata_from_response, or None

    Returns:
        List of memory operation dicts with 'action', 'content', 'category', 'id' fields
    """
    if not metadata:
        return []

    operations = metadata.get("memory_operations", [])

    # Validate each operation has required fields
    valid_operations = []
    valid_actions = {"add", "update", "delete"}

    for op in operations:
        if not isinstance(op, dict):
            logger.warning("Invalid memory operation - not a dict", extra={"operation": op})
            continue

        action = op.get("action")
        if action not in valid_actions:
            logger.warning(
                "Invalid memory operation action",
                extra={"action": action, "valid_actions": list(valid_actions)},
            )
            continue

        # Validate required fields per action
        if action == "add":
            if not op.get("content"):
                logger.warning("Memory add operation missing content", extra={"operation": op})
                continue
        elif action == "update":
            if not op.get("id") or not op.get("content"):
                logger.warning(
                    "Memory update operation missing id or content", extra={"operation": op}
                )
                continue
        elif action == "delete":
            if not op.get("id"):
                logger.warning("Memory delete operation missing id", extra={"operation": op})
                continue

        valid_operations.append(op)

    return valid_operations


def process_memory_operations(user_id: str, operations: list[dict[str, Any]]) -> None:
    """Process memory operations extracted from LLM response.

    Args:
        user_id: The user ID
        operations: List of memory operation dicts
    """
    if not operations:
        return

    logger.info(
        "Processing memory operations",
        extra={"user_id": user_id, "operation_count": len(operations)},
    )

    for op in operations:
        action = op["action"]

        try:
            if action == "add":
                content = op["content"]
                category = op.get("category")
                memory = db.add_memory(user_id, content, category)
                logger.info(
                    "Memory added via LLM",
                    extra={
                        "user_id": user_id,
                        "memory_id": memory.id,
                        "category": category,
                    },
                )
            elif action == "update":
                memory_id = op["id"]
                content = op["content"]
                category = op.get("category")
                success = db.update_memory(memory_id, user_id, content, category)
                if success:
                    logger.info(
                        "Memory updated via LLM",
                        extra={"user_id": user_id, "memory_id": memory_id},
                    )
                else:
                    logger.warning(
                        "Memory update failed - not found or unauthorized",
                        extra={"user_id": user_id, "memory_id": memory_id},
                    )
            elif action == "delete":
                memory_id = op["id"]
                success = db.delete_memory(memory_id, user_id)
                if success:
                    logger.info(
                        "Memory deleted via LLM",
                        extra={"user_id": user_id, "memory_id": memory_id},
                    )
                else:
                    logger.warning(
                        "Memory delete failed - not found or unauthorized",
                        extra={"user_id": user_id, "memory_id": memory_id},
                    )
        except Exception as e:
            logger.error(
                "Error processing memory operation",
                extra={"user_id": user_id, "action": action, "error": str(e)},
                exc_info=True,
            )


def build_response_files(
    gen_image_files: list[dict[str, Any]], message_id: str
) -> list[dict[str, Any]]:
    """Build file metadata list for API response.

    Args:
        gen_image_files: List of generated image file dicts
        message_id: The message ID to associate files with

    Returns:
        List of file metadata dicts with name, type, messageId, fileIndex
    """
    response_files = []
    for idx, f in enumerate(gen_image_files):
        response_files.append(
            {
                "name": f.get("name", ""),
                "type": f.get("type", ""),
                "messageId": message_id,
                "fileIndex": idx,
            }
        )
    return response_files


def build_chat_response(
    assistant_msg: Any,
    content: str,
    gen_image_files: list[dict[str, Any]],
    sources: list[dict[str, str]],
    generated_images_meta: list[dict[str, str]],
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Build chat response dictionary for batch endpoint.

    Args:
        assistant_msg: Message object from database
        content: The message content text
        gen_image_files: List of generated image file dicts
        sources: List of source dicts
        generated_images_meta: List of generated image metadata dicts
        conversation_title: Optional conversation title (included if provided)
        user_message_id: Optional user message ID (for updating temp IDs in frontend)
        language: Optional ISO 639-1 language code for TTS

    Returns:
        Response dictionary with id, role, content, created_at, and optional files/sources/generated_images/title/language
    """
    response_data: dict[str, Any] = {
        "id": assistant_msg.id,
        "role": "assistant",
        "content": content,
        "created_at": assistant_msg.created_at.isoformat(),
    }

    if gen_image_files:
        response_data["files"] = build_response_files(gen_image_files, assistant_msg.id)
    if sources:
        response_data["sources"] = sources
    if generated_images_meta:
        response_data["generated_images"] = generated_images_meta
    if conversation_title:
        response_data["title"] = conversation_title
    if user_message_id:
        response_data["user_message_id"] = user_message_id
    if language:
        response_data["language"] = language

    return response_data


def build_stream_done_event(
    assistant_msg: Any,
    gen_image_files: list[dict[str, Any]],
    sources: list[dict[str, str]],
    generated_images_meta: list[dict[str, str]],
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Build done event dictionary for streaming endpoint.

    Args:
        assistant_msg: Message object from database
        gen_image_files: List of generated image file dicts
        sources: List of source dicts
        generated_images_meta: List of generated image metadata dicts
        conversation_title: Optional conversation title (included if provided)
        user_message_id: Optional user message ID (for updating temp IDs in frontend)
        language: Optional ISO 639-1 language code for TTS

    Returns:
        Done event dictionary with type, id, created_at, content, and optional files/sources/generated_images/title/language
    """
    done_data: dict[str, Any] = {
        "type": "done",
        "id": assistant_msg.id,
        "created_at": assistant_msg.created_at.isoformat(),
        # Always include content for recovery if token events were lost
        "content": assistant_msg.content or "",
    }

    if gen_image_files:
        done_data["files"] = build_response_files(gen_image_files, assistant_msg.id)
    if sources:
        done_data["sources"] = sources
    if generated_images_meta:
        done_data["generated_images"] = generated_images_meta
    if conversation_title:
        done_data["title"] = conversation_title
    if user_message_id:
        done_data["user_message_id"] = user_message_id
    if language:
        done_data["language"] = language

    return done_data


def calculate_and_save_message_cost(
    message_id: str,
    conversation_id: str,
    user_id: str,
    model: str,
    usage_info: dict[str, Any],
    tool_results: list[dict[str, Any]],
    response_length: int,
    mode: str = "batch",
) -> None:
    """Calculate and save cost for a message.

    Args:
        message_id: The message ID
        conversation_id: The conversation ID
        user_id: The user ID
        model: The model used
        usage_info: Dict with 'input_tokens' and 'output_tokens'
        tool_results: List of tool result dicts
        response_length: Length of the response content (used for logging warnings when token metadata is missing)
        mode: 'batch' or 'stream' (for logging)
    """
    input_tokens = usage_info.get("input_tokens", 0)
    output_tokens = usage_info.get("output_tokens", 0)

    # Calculate image generation cost from tool_results
    image_cost = calculate_image_generation_cost_from_tool_results(tool_results)

    # Log warning if no usage metadata (should be rare - indicates API issue)
    if input_tokens == 0 and output_tokens == 0:
        logger.warning(
            f"No token usage metadata found in {mode} mode",
            extra={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": model,
                "response_length": response_length,
            },
        )

    cost_usd = calculate_total_cost(
        model,
        input_tokens,
        output_tokens,
        image_generation_cost=image_cost,
    )

    db.save_message_cost(
        message_id,
        conversation_id,
        user_id,
        model,
        input_tokens,
        output_tokens,
        cost_usd,
        image_generation_cost_usd=image_cost,
    )

    logger.info(
        f"{mode.capitalize()} chat cost saved",
        extra={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )


def calculate_image_generation_cost_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> float:
    """Calculate total cost for all image generations from tool_results.

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        Total cost in USD for all image generations (0.0 if no images or missing usage_metadata)
    """
    from src.utils.costs import calculate_image_generation_cost

    total_cost = 0.0

    for tool_result in tool_results:
        if not isinstance(tool_result, dict) or tool_result.get("type") != "tool":
            continue

        content = tool_result.get("content", "")
        if not content:
            continue

        try:
            content_data = json.loads(content) if isinstance(content, str) else {}
        except json.JSONDecodeError, TypeError:
            continue

        # Check if this is a generate_image result with usage_metadata
        # The image data is in _full_result.image (not sent to LLM), but usage_metadata is at top level
        if isinstance(content_data, dict) and "_full_result" in content_data:
            usage_metadata = content_data.get("usage_metadata")
            if usage_metadata:
                total_cost += calculate_image_generation_cost(usage_metadata)
            else:
                logger.warning(
                    "Image generation tool result missing usage_metadata",
                    extra={"tool_result_keys": list(content_data.keys())},
                )

    return total_cost
