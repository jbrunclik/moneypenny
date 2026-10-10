"""Chat routes: Batch and streaming chat endpoints.

This module handles chat interactions with the AI agent, supporting both
batch (complete response) and streaming (SSE) modes.
"""

import json
import uuid
from typing import NoReturn

from apiflask import APIBlueprint
from flask import Response, request

from src.agent.cancellation import request_finish_now, request_stop
from src.agent.interjection import clear_interjection
from src.api.errors import (
    raise_llm_error,
    raise_not_found_error,
    raise_server_error,
    raise_validation_error,
)
from src.api.helpers.chat_save import save_message_to_db
from src.api.helpers.chat_turn import build_turn_context, prepare_turn
from src.api.helpers.turn_steering import (
    can_steer,
    running_turn_id,
    steer_running_turn,
    wait_for_reply,
)
from src.api.rate_limiting import rate_limit_chat
from src.api.schemas.chat import ChatBatchResponse, ChatRequest, InterjectRequest, StopChatRequest
from src.api.schemas.common import StatusResponse
from src.api.utils import build_chat_response, is_round_capped
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

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
    if data.deep_research:
        # A multi-minute run cannot live in one HTTP request; the stream has resume
        raise_validation_error("Deep research runs on the stream endpoint", field="deep_research")
    running = _steerable_running_turn(user, data, conv_id)
    if running is not None:
        return _steer_batch_send(user, data, conv_id, running)
    turn = prepare_turn(user, data, conv_id)
    ctx = build_turn_context(user, turn, request_id=str(uuid.uuid4()))
    ctx.apply()
    try:
        raw_response, tool_results, usage_info, result_messages = ctx.create_agent().chat_batch(
            **ctx.agent_call_kwargs()
        )
        logger.debug(
            "Chat agent completed",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "response_length": len(raw_response),
                "tool_results_count": len(tool_results),
                "input_tokens": usage_info.get("input_tokens", 0),
                "output_tokens": usage_info.get("output_tokens", 0),
            },
        )
        saved = save_message_to_db(
            raw_response,
            result_messages,
            tool_results,
            usage_info,
            conv_id,
            user.id,
            turn.conv.model,
            turn.message_text,
            ctx.request_id,
            client_connected=True,
            mode="batch",
        )
    except TimeoutError:
        logger.error(
            "Timeout in chat_batch",
            extra={"user_id": user.id, "conversation_id": conv_id},
            exc_info=True,
        )
        raise_llm_error("Request timed out. The AI took too long to respond. Please try again.")
    except Exception as e:
        # Log the error but don't expose internal details to users
        logger.error(
            "Error in chat_batch",
            extra={"user_id": user.id, "conversation_id": conv_id, "error": str(e)},
            exc_info=True,
        )
        _raise_chat_error(e)
    finally:
        ctx.clear()
        # Steering that arrived after the last tool round was never popped
        clear_interjection(user.id, conv_id)

    assistant_msg = db.get_message_by_id(saved.message_id) if saved else None
    if saved is None or assistant_msg is None:
        raise_server_error("Failed to generate response. Please try again.")

    response_data = build_chat_response(
        assistant_msg,
        assistant_msg.content,
        saved.all_generated_files,
        saved.sources,
        saved.generated_images_meta,
        conversation_title=saved.generated_title,
        user_message_id=turn.user_msg.id,
        language=saved.language,
        stopped_early=is_round_capped(usage_info.get("tool_rounds", 0)),
    )
    if usage_info.get("model_fallback"):
        # The conversation's model was down; the other tier answered
        response_data["model_fallback"] = usage_info["model_fallback"]
    return response_data, 200


def _steerable_running_turn(user: User, data: ChatRequest, conv_id: str) -> str | None:
    """The live turn (another device's) this send should steer, if any.

    A retry of a send that already landed falls through to the normal
    path's duplicate check (409).
    """
    if not can_steer(data) or not db.get_conversation(conv_id, user.id):
        return None
    if data.client_message_id and db.get_message_by_id(data.client_message_id):
        return None
    return running_turn_id(conv_id)


def _steer_batch_send(
    user: User, data: ChatRequest, conv_id: str, running: str
) -> tuple[dict[str, str], int]:
    """Steer the live turn and answer with its reply once it lands."""
    steering = steer_running_turn(user.id, conv_id, data.message.strip(), data.client_message_id)
    reply = wait_for_reply(running)
    if reply is None:
        raise_llm_error("The reply in progress didn't finish. Please try again.")
    response_data = build_chat_response(
        reply,
        reply.content,
        reply.files or [],
        reply.sources or [],
        reply.generated_images or [],
        user_message_id=steering.id,
        language=reply.language,
    )
    return response_data, 200


def _steer_stream_send(user: User, data: ChatRequest, conv_id: str, running: str) -> Response:
    """Steer the live turn; the client then follows it like a remote stream."""
    steering = steer_running_turn(user.id, conv_id, data.message.strip(), data.client_message_id)
    events = [
        {"type": "user_message_saved", "user_message_id": steering.id},
        {
            "type": "interjected",
            "message_id": running,
            "message_count": db.count_messages(conv_id),
        },
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return Response(body, mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


def _raise_chat_error(error: Exception) -> NoReturn:
    """Map an agent failure to a user-facing error without internal details."""
    error_str = str(error).lower()
    if "timeout" in error_str or "timed out" in error_str:
        raise_llm_error("Request timed out. Please try again.")
    if "rate limit" in error_str or "quota" in error_str:
        raise_llm_error("AI service is busy. Please try again in a moment.")
    raise_server_error("Failed to generate response. Please try again.")


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
- `interjected`: Another device's turn was running in this conversation: the (plain text)
  message was saved as steering for it and no turn of its own runs; follow that reply
  via the resume endpoint - `{"type": "interjected", "message_id": "...", "message_count": N}`

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
    running = _steerable_running_turn(user, data, conv_id)
    if running is not None:
        return _steer_stream_send(user, data, conv_id, running)
    turn = prepare_turn(user, data, conv_id)
    ctx = build_turn_context(user, turn, request_id=str(uuid.uuid4()))
    logger.debug(
        "Starting stream chat agent",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "model": turn.conv.model,
            "history_length": len(ctx.history),
            "force_tools": turn.force_tools,
        },
    )
    generator = create_stream_generator(user=user, turn=turn, ctx=ctx)

    return Response(
        generator,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@api.route("/conversations/<conv_id>/chat/interject", methods=["POST"])
@api.output(StatusResponse)
@api.doc(
    summary="Steer a turn that is currently generating",
    description=(
        "Mid-run steering: stores guidance that the agent picks up between "
        "tool rounds of the in-flight turn (cross-worker via kv_store). The "
        "text is also persisted as a regular user message so future turns "
        "see it in history. Best-effort: if the turn finishes before the "
        "next tool round, the guidance still lands in history."
    ),
    responses=[400, 401, 404],
)
@rate_limit_chat
@require_auth
@validate_request(InterjectRequest)
def chat_interject(user: User, data: InterjectRequest, conv_id: str) -> dict[str, str]:
    """Inject user guidance into a running multi-round turn."""
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        raise_not_found_error("Conversation")

    text = data.message.strip()
    # A retry of the same client id is a no-op
    existing = db.get_message_by_id(data.client_message_id) if data.client_message_id else None
    if existing is not None:
        if existing.conversation_id != conv_id:
            raise_not_found_error("Conversation")
        return {"status": "interjected"}
    steer_running_turn(user.id, conv_id, text, data.client_message_id)
    return {"status": "interjected"}


@api.route("/conversations/<conv_id>/chat/stop", methods=["POST"])
@api.output(StatusResponse)
@api.doc(
    summary="Stop the running chat turn",
    description=(
        "Ask the in-flight turn of this conversation to stop at its next "
        "checkpoint (cross-worker via kv_store). message_id names the turn "
        "(its assistant message id from user_message_saved). The stream then ends with a "
        "done event carrying stop_reason 'user' and the partial reply saved. "
        "Harmless when no turn is running."
    ),
    responses=[401, 404],
)
@rate_limit_chat
@require_auth
@validate_request(StopChatRequest)
def chat_stop(user: User, data: StopChatRequest, conv_id: str) -> dict[str, str]:
    """Request that the running turn stops."""
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        raise_not_found_error("Conversation")
    request_stop(user.id, conv_id, data.message_id)
    logger.info(
        "Stop requested",
        extra={"user_id": user.id, "conversation_id": conv_id, "message_id": data.message_id},
    )
    return {"status": "stopping"}


@api.route("/conversations/<conv_id>/chat/finish-now", methods=["POST"])
@api.output(StatusResponse)
@api.doc(
    summary="Finish a deep-research run now",
    description=(
        "Cut the remaining research of the running deep-research turn and write "
        "the report from what was gathered (cross-worker via kv_store). message_id "
        "names the turn (its assistant message id)."
    ),
    responses=[401, 404],
)
@rate_limit_chat
@require_auth
@validate_request(StopChatRequest)
def chat_finish_now(user: User, data: StopChatRequest, conv_id: str) -> dict[str, str]:
    """Request that a running deep-research turn writes its report now."""
    if not db.get_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    request_finish_now(user.id, conv_id, data.message_id)
    logger.info(
        "Deep research finish-now requested",
        extra={"user_id": user.id, "conversation_id": conv_id, "message_id": data.message_id},
    )
    return {"status": "finishing"}


@api.route("/conversations/<conv_id>/chat/stream/<message_id>/resume", methods=["GET"])
@api.doc(
    summary="Resume an interrupted chat stream",
    description="""Resume a chat stream from the event journal after a connection loss.

Pass `after_seq` (the `seq` of the last SSE event the client rendered; 0 for
none). The server replays journaled events with a higher seq, continues live
while generation is still running, and finishes with a `done` event built
from the saved message. Emits `{"type": "error", "code": "RESUME_FAILED"}`
when the turn failed and nothing was saved.
""",
    responses=[404],
)
@rate_limit_chat
@require_auth
def chat_stream_resume(user: User, conv_id: str, message_id: str) -> Response:
    """Resume streaming for an in-flight or recently finished assistant message."""
    from src.api.helpers.stream_resume import stream_resume_events

    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        raise_not_found_error("Conversation")

    msg = db.get_message_by_id(message_id)
    if not msg or msg.conversation_id != conv_id:
        raise_not_found_error("Message")

    after_seq = request.args.get("after_seq", default=0, type=int)
    logger.info(
        "Resuming chat stream",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_id": message_id,
            "after_seq": after_seq,
        },
    )

    return Response(
        stream_resume_events(message_id, after_seq),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
