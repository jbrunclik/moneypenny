"""Conversation compaction for autonomous agents.

Prevents agent conversations from exceeding context limits by
summarizing older messages when the conversation grows too long.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models.dataclasses import Agent

logger = get_logger(__name__)

# Per-message character cap in summarizer input. Generous on purpose: a
# 500-char cap meant the summarizer saw ~25% of the text it replaced (measured
# on production conversations). The cheap summary model has a large context
# window; this only guards pathological messages.
SUMMARY_MESSAGE_MAX_CHARS = 8000

# What a conversation summary should preserve (shared by all summarizers)
SUMMARY_FOCUS = (
    "1. Key topics, questions, and decisions\n"
    "2. Important facts, preferences, or context the user shared\n"
    "3. Conclusions reached or actions the assistant took\n"
    "4. Any ongoing tasks or open threads\n"
    "5. Exact identifiers needed to continue the work verbatim: names, "
    "dates, numbers, amounts, URLs, and file or message references"
)


def needs_compaction(agent: Agent) -> bool:
    """Check if an agent's conversation needs compaction.

    Args:
        agent: The agent to check

    Returns:
        True if message count exceeds AGENT_COMPACTION_THRESHOLD
    """
    if not agent.conversation_id:
        return False

    message_count = db.get_agent_message_count(agent.id)
    return message_count > Config.AGENT_COMPACTION_THRESHOLD


def run_summary_model(prompt: str) -> str | None:
    """Run the fast summarization model on a prompt.

    Returns the stripped summary text, or None if the model returned nothing
    or raised. Callers supply their own fallback text.
    """
    # Import here to avoid circular imports
    from google import genai
    from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel

    try:
        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=Config.AI_ASSIST_MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.3,  # More deterministic for summaries
                # Summaries are extraction, not reasoning: on production
                # conversations LOW kept fact recall (81-92% vs 74-88% at the
                # API default) at ~30% lower cost - thinking tokens were ~85%
                # of the summarizer's output spend.
                thinking_config=ThinkingConfig(thinking_level=ThinkingLevel.LOW),
            ),
        )
        if response.text:
            return response.text.strip()
        # No text without an exception is usually a blocked response (safety,
        # recitation) - record why, it is otherwise invisible
        candidate = response.candidates[0] if response.candidates else None
        logger.warning(
            "Summary model returned no text",
            extra={
                "finish_reason": str(getattr(candidate, "finish_reason", None)),
                "block_reason": str(getattr(response.prompt_feedback, "block_reason", None)),
            },
        )
        return None
    except Exception as e:
        logger.error("Failed to generate conversation summary", extra={"error": str(e)})
        return None


# Marker compact_agent_conversation() puts on the summary message it inserts
PREVIOUS_SUMMARY_PREFIX = "[Previous conversation summary]\n\n"

_AGENT_SUMMARY_FOCUS = (
    "1. Key actions taken by the agent\n"
    "2. Important information discovered (exact values, names, dates)\n"
    "3. Ongoing tasks or goals\n"
    "4. Any errors or issues encountered"
)


def _segmented_agent_summary(agent: Agent, messages: list[dict[str, Any]]) -> str | None:
    """Summary for the messages being compacted away, or None on failure.

    Reuses the segmented summaries of regular chats: the previous compaction's
    summary message is kept as the first segment (not re-summarized - folding
    it into a new summary every time compounded the loss), and only the
    messages after it are summarized, from full text, in batches.
    """
    # Lazy: compaction_segments imports this module for run_summary_model
    from src.agent.compaction_segments import (
        Segment,
        extend_segments,
        render_segments,
        summarize_segment,
    )

    prior: list[Segment] = []
    start = 0
    if messages and messages[0]["content"].startswith(PREVIOUS_SUMMARY_PREFIX):
        prior_text = messages[0]["content"][len(PREVIOUS_SUMMARY_PREFIX) :].strip()
        if prior_text:
            prior = [Segment(prior_text, end=1, passes=1)]
        start = 1
    summarize = partial(
        summarize_segment,
        role_labels=("Trigger", "Agent"),
        intro=(
            "Summarize the following part of an autonomous agent's conversation "
            f"concisely.\nAgent: {agent.name}\nDescription: {agent.description or 'N/A'}"
        ),
        focus=_AGENT_SUMMARY_FOCUS,
    )
    segments = extend_segments(prior, messages, start, len(messages), summarize=summarize)
    return render_segments(segments) if segments else None


def compact_conversation(agent: Agent) -> bool:
    """Compact an agent's conversation if needed.

    This function:
    1. Checks if compaction is needed
    2. Gets messages to summarize
    3. Generates a summary using LLM
    4. Replaces old messages with the summary

    Args:
        agent: The agent whose conversation to compact

    Returns:
        True if compaction was performed, False otherwise
    """
    if not needs_compaction(agent):
        return False

    logger.info(
        "Starting conversation compaction",
        extra={"agent_id": agent.id, "agent_name": agent.name},
    )

    # Get all messages in the conversation
    if not agent.conversation_id:
        return False

    messages = db.get_messages(agent.conversation_id)

    if len(messages) <= Config.AGENT_COMPACTION_KEEP_RECENT:
        return False

    # Get messages to summarize (all except recent ones)
    messages_to_summarize = messages[: -Config.AGENT_COMPACTION_KEEP_RECENT]
    messages_as_dicts = [
        {"role": m.role.value, "content": m.content} for m in messages_to_summarize
    ]

    summary = _segmented_agent_summary(agent, messages_as_dicts)
    if not summary:
        # Compaction DELETES the messages - never do it behind a placeholder.
        # They stay until a later run summarizes them successfully.
        logger.warning(
            "Agent compaction skipped: summary unavailable",
            extra={"agent_id": agent.id},
        )
        return False

    # Perform compaction
    deleted_count = db.compact_agent_conversation(
        agent.id,
        summary,
        keep_recent=Config.AGENT_COMPACTION_KEEP_RECENT,
    )

    logger.info(
        "Conversation compaction completed",
        extra={
            "agent_id": agent.id,
            "messages_deleted": deleted_count,
            "summary_length": len(summary),
        },
    )

    return deleted_count > 0
