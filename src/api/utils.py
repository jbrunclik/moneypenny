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
    cached_input_tokens = usage_info.get("cached_input_tokens", 0)
    tool_rounds = usage_info.get("tool_rounds", 0)
    tool_call_count = usage_info.get("tool_call_count", 0)

    # Costs incurred inside tools: image generations + delegate subagent runs
    image_cost = calculate_image_generation_cost_from_tool_results(tool_results)
    delegate_cost = calculate_delegate_cost_from_tool_results(tool_results)

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
        cached_input_tokens=cached_input_tokens,
        tool_llm_cost=delegate_cost,
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
        cached_input_tokens=cached_input_tokens,
        tool_rounds=tool_rounds,
        tool_call_count=tool_call_count,
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
        except (json.JSONDecodeError, TypeError):
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


def calculate_delegate_cost_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> float:
    """Sum the token cost of delegate_task subagent runs in tool_results.

    delegate_task embeds its subagent's usage under a top-level
    _delegate_usage key in the tool result JSON (priced at the subagent's own
    model, which may differ from the conversation's).

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        Total cost in USD (0.0 when no delegate runs happened)
    """
    from src.utils.costs import calculate_token_cost

    total_cost = 0.0

    for tool_result in tool_results:
        if not isinstance(tool_result, dict) or tool_result.get("type") != "tool":
            continue

        content = tool_result.get("content", "")
        if not content or not isinstance(content, str):
            continue

        try:
            content_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(content_data, dict):
            continue
        usage = content_data.get("_delegate_usage")
        if not isinstance(usage, dict):
            continue

        total_cost += calculate_token_cost(
            str(usage.get("model", "")),
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        )

    return total_cost
