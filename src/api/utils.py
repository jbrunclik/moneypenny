"""API response building utilities."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from flask import Request
from werkzeug.exceptions import HTTPException

from src.config import Config
from src.db.models import db
from src.enums import MessageRole
from src.utils.clock import to_api, utc_now
from src.utils.files import StoredFile, UploadedFile
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

    try:
        return request.get_json(silent=True) or {}
    except HTTPException:
        # Re-raise HTTP exceptions (e.g., 413 Request Entity Too Large)
        # so Flask's error handler can return the appropriate response
        raise
    except ValueError:
        # JSON parsing errors (silent=True already swallows most of them)
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
    gen_image_files: Sequence[UploadedFile | StoredFile], message_id: str
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


def add_grounding(data: dict[str, Any], msg: Any) -> None:
    """Grounding-check annotations and their summary, when the message has them."""
    annotations = getattr(msg, "annotations", None)
    if annotations:
        data["annotations"] = annotations
        data["grounding"] = getattr(msg, "grounding", None)


def add_action(data: dict[str, Any], msg: Any) -> None:
    """What a user message sent on the user's behalf was, when it has one."""
    action = getattr(msg, "action", None)
    if action:
        data["action"] = action


def add_research(data: dict[str, Any], msg: Any) -> None:
    """Deep-research offer or run data, when the message has it."""
    research = getattr(msg, "research", None)
    if research:
        data["research"] = research


def add_artifacts(data: dict[str, Any], msg: Any) -> None:
    """Artifacts shown under the message ([{id, version, title}]), when it has any."""
    artifacts = getattr(msg, "artifacts", None)
    if artifacts:
        data["artifacts"] = artifacts


def build_chat_response(
    assistant_msg: Any,
    content: str,
    gen_image_files: Sequence[UploadedFile | StoredFile],
    sources: list[dict[str, str]],
    generated_images_meta: list[dict[str, str]],
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    language: str | None = None,
    stopped_early: bool = False,
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
        "created_at": to_api(assistant_msg.created_at),
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
    if stopped_early:
        response_data["stopped_early"] = True
    stop_reason = getattr(assistant_msg, "stop_reason", None)
    if stop_reason:
        response_data["stop_reason"] = stop_reason
    add_grounding(response_data, assistant_msg)
    add_research(response_data, assistant_msg)
    add_artifacts(response_data, assistant_msg)
    response_data["message_count"] = conversation_message_count(assistant_msg)

    return response_data


def conversation_message_count(assistant_msg: Any) -> int:
    """The conversation's exact message count after a turn finished.

    Other devices notice new messages by comparing counts, so the sending
    client takes this as its baseline instead of guessing +2 (regenerate and
    continue change the count by 0/+1, and the drift hid the other device's
    next messages).
    """
    return db.count_messages(assistant_msg.conversation_id)


def is_round_capped(tool_rounds: int) -> bool:
    """Whether a turn ran into the tool-round cap (the model was told to stop).

    Compares against the CURRENT cap, not the one in effect when the turn ran
    (message_costs stores only the round count): changing AGENT_MAX_TOOL_ROUNDS
    re-labels historical replies. Accepted to avoid a column for a hint flag.
    """
    cap = Config.AGENT_MAX_TOOL_ROUNDS
    return cap > 0 and tool_rounds >= cap


def is_empty_placeholder(message: Any) -> bool:
    """An assistant message saved empty at stream start, not filled in yet."""
    return bool(
        message.role == MessageRole.ASSISTANT
        and not message.content
        and not message.files
        and not message.sources
        and not message.generated_images
    )


def streaming_message_id(conversation_id: str) -> str | None:
    """The reply still being generated in this conversation, if any.

    Its empty placeholder is filtered from responses, so another device
    learns about the in-flight turn only through this id - and follows it
    via the resume endpoint. Looked up in the conversation, not the returned
    page: steering saves user messages after the placeholder (it fell out of
    a "newest rows" scan), and a search jump loads an older window. Only one
    younger than the longest a turn can run counts: an old empty reply is
    just empty.
    """
    # A deep-research run outlasts a chat turn
    longest = max(Config.CHAT_TIMEOUT_SECONDS, Config.DEEP_RESEARCH_RUN_TIMEOUT_SECONDS)
    cutoff = utc_now() - timedelta(seconds=longest + 60)
    return db.get_streaming_placeholder_id(conversation_id, cutoff)


def serialize_messages_for_response(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Message objects to optimized response format.

    Only includes file metadata (name, type, messageId, fileIndex), not full data.
    Filters out empty placeholder messages that are still being processed by stream.
    Assistant replies cut off by the tool-round cap get ``stopped_early: true``.
    Shared by the conversation, planner and program routes (the planner once
    kept its own copy that lacked the placeholder filter).
    """
    # Filter out empty placeholder messages (still being processed by stream)
    messages = [m for m in messages if not is_empty_placeholder(m)]

    capped_ids = db.get_round_capped_message_ids(
        [m.id for m in messages if m.role == MessageRole.ASSISTANT],
        Config.AGENT_MAX_TOOL_ROUNDS,
    )

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
            "created_at": to_api(m.created_at),
        }
        if m.sources:
            msg_data["sources"] = m.sources
        if m.generated_images:
            # Normalize generated_images to ensure proper structure
            # (LLM sometimes returns just strings instead of {"prompt": "..."} objects)
            msg_data["generated_images"] = normalize_generated_images(m.generated_images)
        if m.language:
            msg_data["language"] = m.language
        if m.id in capped_ids:
            msg_data["stopped_early"] = True
        if m.stop_reason:
            msg_data["stop_reason"] = m.stop_reason
        add_grounding(msg_data, m)
        add_research(msg_data, m)
        add_artifacts(msg_data, m)
        add_action(msg_data, m)

        optimized_messages.append(msg_data)
    return optimized_messages


def build_stream_done_event(
    assistant_msg: Any,
    gen_image_files: Sequence[UploadedFile | StoredFile],
    sources: list[dict[str, str]],
    generated_images_meta: list[dict[str, str]],
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    language: str | None = None,
    stopped_early: bool = False,
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
        stopped_early: Whether the turn hit the tool-round cap

    Returns:
        Done event dictionary with type, id, created_at, content, and optional files/sources/generated_images/title/language
    """
    done_data: dict[str, Any] = {
        "type": "done",
        "id": assistant_msg.id,
        "created_at": to_api(assistant_msg.created_at),
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
    if stopped_early:
        done_data["stopped_early"] = True
    stop_reason = getattr(assistant_msg, "stop_reason", None)
    if stop_reason:
        done_data["stop_reason"] = stop_reason
    add_grounding(done_data, assistant_msg)
    add_research(done_data, assistant_msg)
    add_artifacts(done_data, assistant_msg)
    done_data["message_count"] = conversation_message_count(assistant_msg)

    return done_data
