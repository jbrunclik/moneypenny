"""Persistence pipeline for a completed chat turn.

Orchestrates metadata extraction, generated-file collection, message
persistence, cost accounting and title generation. Called from both the stream
generator and the cleanup thread.

Memory operations are not handled here: manage_memory writes during the turn so
the model can read the outcome, rather than having its arguments replayed after
the fact.
"""

from __future__ import annotations

from typing import Any

from src.agent.agent import generate_title
from src.agent.content import (
    detect_response_language,
    extract_cited_sources,
    extract_image_prompts_from_messages,
    extract_sources_fallback_from_tool_results,
)
from src.agent.tool_results import get_full_tool_results, set_current_request_id
from src.agent.tools import set_conversation_context, set_current_message_files
from src.api.schemas import MessageRole
from src.api.utils import calculate_and_save_message_cost
from src.config import Config
from src.db.models import db
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SaveResult:
    """Result from save_message_to_db with extracted data for done event."""

    def __init__(
        self,
        message_id: str,
        sources: list[dict[str, str]],
        generated_images_meta: list[dict[str, str]],
        all_generated_files: list[dict[str, Any]],
        generated_title: str | None,
        language: str | None,
    ) -> None:
        self.message_id = message_id
        self.sources = sources
        self.generated_images_meta = generated_images_meta
        self.all_generated_files = all_generated_files
        self.generated_title = generated_title
        self.language = language


def _extract_stream_metadata(
    content: str,
    result_messages: list[Any],
    tools: list[dict[str, Any]],
    user_id: str,
    conv_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Extract sources, image prompts and language from the turn."""
    sources: list[dict[str, Any]] = list(extract_cited_sources(result_messages))
    generated_images_meta = extract_image_prompts_from_messages(result_messages)
    language = detect_response_language(content)

    # Fallback: if web_search was used but no cite_sources, extract from tool results
    if not sources and tools:
        sources = extract_sources_fallback_from_tool_results(tools)

    logger.debug(
        "Extracted metadata from stream",
        extra={
            "user_id": user_id,
            "conversation_id": conv_id,
            "sources_count": len(sources) if sources else 0,
            "generated_images_count": len(generated_images_meta) if generated_images_meta else 0,
            "language": language,
        },
    )
    return sources, generated_images_meta, language


def _collect_generated_files(
    stream_request_id: str, user_id: str, conv_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pop the full tool results, clean up request context, extract files.

    Returns (all_generated_files, full_tool_results). NOTE:
    get_full_tool_results() POPS the results - callable only once per request.
    """
    full_tool_results = get_full_tool_results(stream_request_id)
    set_current_request_id(None)  # Clean up
    set_current_message_files(None)  # Clean up
    set_conversation_context(None, None)  # Clean up

    # Extract generated files from FULL tool results (before stripping)
    gen_image_files = extract_generated_images_from_tool_results(full_tool_results)
    code_output_files = extract_code_output_files_from_tool_results(full_tool_results)

    all_generated_files = gen_image_files + code_output_files
    if all_generated_files:
        logger.info(
            "Generated files extracted from stream",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "image_count": len(gen_image_files),
                "code_output_count": len(code_output_files),
            },
        )
    return all_generated_files, full_tool_results


def _persist_assistant_message(
    conv_id: str,
    user_id: str,
    content: str,
    assistant_message_id: str | None,
    all_generated_files: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    generated_images_meta: list[dict[str, Any]],
    language: str | None,
) -> Any:
    """UPDATE the stream-start placeholder, or INSERT when it is gone/absent."""
    logger.debug(
        "Saving assistant message from stream",
        extra={"user_id": user_id, "conversation_id": conv_id},
    )
    kwargs: dict[str, Any] = {
        "files": all_generated_files if all_generated_files else None,
        "sources": sources if sources else None,
        "generated_images": generated_images_meta if generated_images_meta else None,
        "language": language,
    }
    if assistant_message_id:
        assistant_msg = db.update_message_content(assistant_message_id, content, **kwargs)
        if assistant_msg:
            return assistant_msg
        # Placeholder was deleted (user deleted while processing) — fall back to INSERT
        logger.info(
            "Placeholder message deleted during processing, falling back to INSERT",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
    return db.add_message(conv_id, MessageRole.ASSISTANT, content, **kwargs)


def _maybe_generate_title(
    conv_id: str, user_id: str, message_text: str, content: str
) -> str | None:
    """Auto-generate the conversation title from the first exchange.

    Wrapped in its own try/except so a title-generation failure can never
    abort the message save (which already succeeded). On failure the default
    title stays; the next user message retries.
    """
    conv = db.get_conversation(conv_id, user_id)
    if not conv or conv.title != Config.DEFAULT_CONVERSATION_TITLE:
        return None

    logger.debug(
        "Auto-generating conversation title from stream",
        extra={"user_id": user_id, "conversation_id": conv_id},
    )
    try:
        generated_title = generate_title(message_text, content)
        if generated_title is not None:
            db.update_conversation(conv_id, user_id, title=generated_title)
            logger.debug(
                "Conversation title generated from stream",
                extra={
                    "user_id": user_id,
                    "conversation_id": conv_id,
                    "title": generated_title,
                },
            )
        return generated_title
    except Exception:
        logger.exception(
            "Title generation/update failed (continuing without title)",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
        return None


def save_message_to_db(
    content: str,
    result_messages: list[Any],
    tools: list[dict[str, Any]],
    usage: dict[str, Any],
    conv_id: str,
    user_id: str,
    model: str,
    message_text: str,
    stream_request_id: str,
    client_connected: bool,
    assistant_message_id: str | None = None,
) -> SaveResult | None:
    """Save message to database. Called from both generator and cleanup thread.

    Orchestrates the sub-steps: metadata extraction, generated-file collection,
    message persistence, cost accounting and title generation.

    Args:
        content: Message content to save
        result_messages: All messages from the graph for metadata extraction
        tools: Tool results list
        usage: Usage info dictionary
        conv_id: Conversation ID
        user_id: User ID string (for logging)
        model: Model name
        message_text: Original user message text (for title generation)
        stream_request_id: Streaming request ID (for full tool results)
        client_connected: Whether client is still connected (for logging)
        assistant_message_id: Pre-generated message ID for streaming recovery

    Returns:
        SaveResult with extracted data for building done event, or None on error.
    """
    try:
        sources, generated_images_meta, language = _extract_stream_metadata(
            content, result_messages, tools, user_id, conv_id
        )
        all_generated_files, full_tool_results = _collect_generated_files(
            stream_request_id, user_id, conv_id
        )
        assistant_msg = _persist_assistant_message(
            conv_id,
            user_id,
            content,
            assistant_message_id,
            all_generated_files,
            sources,
            generated_images_meta,
            language,
        )

        # Calculate and save cost for streaming (use full_tool_results for image cost)
        calculate_and_save_message_cost(
            assistant_msg.id,
            conv_id,
            user_id,
            model,
            usage,
            full_tool_results,
            len(content),
            mode="stream",
        )

        generated_title = _maybe_generate_title(conv_id, user_id, message_text, content)

        logger.info(
            "Stream chat completed and saved",
            extra={
                "user_id": user_id,
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
            language=language,
        )
    except Exception as e:
        logger.error(
            "Error saving stream message to DB",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "error": str(e),
            },
            exc_info=True,
        )
        return None
