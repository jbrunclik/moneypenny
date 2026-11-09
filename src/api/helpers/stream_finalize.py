"""End of a chat stream: save the turn and send the done event."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from src.api.helpers.chat_save import save_message_to_db
from src.api.helpers.stream_producer import (
    defer_final_steering,
    notify_response_ready,
    push_title,
)
from src.api.utils import build_stream_done_event
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.api.helpers.chat_streaming import StreamContext

logger = get_logger(__name__)


def finalize_stream(context: StreamContext) -> Generator[str]:
    """Save message to DB and yield done event."""
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
                    stopped_early=bool(context.usage_info.get("stopped_by")),
                )
                _flag_unanswered_steering(done_data, context)
                with contextlib.suppress(BrokenPipeError, ConnectionError, OSError):
                    yield f"data: {json.dumps(done_data)}\n\n"
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
            defer_final_steering(context.final_results, context.conv_id, save_result.message_id)

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
        stopped_early=bool(context.usage_info.get("stopped_by")),
    )
    _flag_unanswered_steering(done_data, context)

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
            notify_response_ready(
                context.user_id,
                context.conv_id,
                assistant_msg.content or "",
                push_title(context.usage_info),
            )


def _flag_unanswered_steering(done_data: dict[str, Any], context: StreamContext) -> None:
    """Name steering the turn never read: the client answers it with a
    follow-up turn (not after Stop - the user ended the turn themselves)."""
    steering_id = context.final_results.get("unanswered_steering_id")
    if steering_id and not context.stop_reason:
        done_data["unanswered_steering_id"] = steering_id
