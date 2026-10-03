"""End of a chat stream: save the turn and send the done event."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING

from src.agent.tools.request_approval import build_approval_message
from src.api.helpers.chat_save import save_message_to_db
from src.api.helpers.stream_producer import _notify_response_ready, push_title
from src.api.schemas.common import MessageRole
from src.api.utils import build_stream_done_event, is_round_capped
from src.db.models import db
from src.utils.logging import get_logger
from src.utils.push import send_push_to_user

if TYPE_CHECKING:
    from src.api.helpers.chat_streaming import _StreamContext

logger = get_logger(__name__)


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
                    stopped_early=is_round_capped(context.usage_info.get("tool_rounds", 0)),
                )
                try:
                    yield f"data: {json.dumps(done_data)}\n\n"
                except BrokenPipeError, ConnectionError, OSError:
                    pass
            return

        save_result = save_message_to_db(
            context.clean_content,
            context.result_messages,
            context.tool_results,
            context.usage_info,
            context.conv_id,
            context.user_id,
            context.conv.model,
            context.message_text,
            context.stream_request_id,
            context.client_connected,
            context.expected_assistant_msg_id,
            stop_reason=context.stop_reason,
        )

        # Mark as saved so cleanup thread knows not to save again
        if save_result:
            context.final_results["saved"] = True

    # Skip done event if save failed (nothing to finalize)
    if not save_result:
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
        stopped_early=is_round_capped(context.usage_info.get("tool_rounds", 0)),
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
        if not context.stop_reason:
            _notify_response_ready(
                context.user_id,
                context.conv_id,
                assistant_msg.content or "",
                push_title(context.usage_info),
            )


def _finalize_approval_stream(context: _StreamContext) -> Generator[str]:
    """Handle finalization when an approval request was raised.

    Saves the approval message to the conversation and sends a done event.
    """
    approval_id: str = context.approval_info.get("approval_id", "")  # type: ignore[union-attr]
    description: str = context.approval_info.get("description", "")  # type: ignore[union-attr]
    tool_name: str = context.approval_info.get("tool_name", "")  # type: ignore[union-attr]
    sibling_results = context.approval_info.get("sibling_results", [])  # type: ignore[union-attr]

    # Build and save the approval message
    approval_message = build_approval_message(
        approval_id, description, tool_name, sibling_results=sibling_results
    )

    logger.debug(
        "Saving approval message from stream",
        extra={
            "user_id": context.user_id,
            "conversation_id": context.conv_id,
            "approval_id": approval_id,
        },
    )

    if context.placeholder_saved:
        assistant_msg = db.update_message_content(
            context.expected_assistant_msg_id,
            approval_message,
        )
        if not assistant_msg:
            assistant_msg = db.add_message(context.conv_id, MessageRole.ASSISTANT, approval_message)
    else:
        assistant_msg = db.add_message(context.conv_id, MessageRole.ASSISTANT, approval_message)

    # Mark as saved so cleanup thread doesn't try to save again
    context.final_results["saved"] = True

    context.turn.clear()

    def notify_approval_needed() -> None:
        # The turn is blocked on the user and nobody saw the request
        send_push_to_user(
            context.user_id,
            "Approval needed",
            description[:160],
            url=f"/#/conversations/{context.conv_id}",
            tag=f"approval-{approval_id}",
        )

    if not context.client_connected:
        notify_approval_needed()
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
        notify_approval_needed()
