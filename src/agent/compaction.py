"""Conversation compaction for autonomous agents.

Prevents agent conversations from exceeding context limits by
summarizing older messages when the conversation grows too long.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models.dataclasses import Agent

logger = get_logger(__name__)


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


def _run_summary_model(prompt: str) -> str | None:
    """Run the fast summarization model on a prompt.

    Returns the stripped summary text, or None if the model returned nothing
    or raised. Callers supply their own fallback text.
    """
    # Import here to avoid circular imports
    from google import genai
    from google.genai.types import GenerateContentConfig

    try:
        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=Config.AI_ASSIST_MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.3,  # More deterministic for summaries
            ),
        )
        if response.text:
            return response.text.strip()
        return None
    except Exception as e:
        logger.error("Failed to generate conversation summary", extra={"error": str(e)})
        return None


def summarize_messages(
    messages: list[dict[str, str]],
    prior_summary: str | None = None,
    *,
    role_labels: tuple[str, str] = ("User", "Assistant"),
    focus: str = (
        "1. Key topics, questions, and decisions\n"
        "2. Important facts, preferences, or context the user shared\n"
        "3. Conclusions reached or actions the assistant took\n"
        "4. Any ongoing tasks or open threads\n"
        "5. Exact identifiers needed to continue the work verbatim: names, "
        "dates, numbers, amounts, URLs, and file or message references"
    ),
    intro: str = "Summarize this conversation history concisely.",
    max_words: int = 500,
) -> str | None:
    """Summarize conversation messages into a concise running summary.

    When ``prior_summary`` is provided it is folded in so context accumulates
    across successive compactions rather than being lost.

    Args:
        messages: Messages to summarize, as ``{"role", "content"}`` dicts
        prior_summary: Existing summary covering earlier messages, if any
        role_labels: (user_label, assistant_label) used to render the transcript
        focus: Bulleted guidance on what the summary should capture
        intro: Opening instruction line
        max_words: Soft length cap for the summary

    Returns:
        Summary text, or None if the model produced nothing (caller decides
        the fallback).
    """
    user_label, assistant_label = role_labels
    conversation_text = ""
    for msg in messages:
        label = assistant_label if msg["role"] == "assistant" else user_label
        conversation_text += f"{label}: {msg['content'][:500]}...\n\n"

    prior_block = ""
    if prior_summary:
        prior_block = (
            "An earlier part of this conversation was already summarized as:\n"
            f"{prior_summary}\n\n"
            "Extend that summary to also cover the new messages below, keeping it "
            "a single coherent summary (do not drop earlier details).\n\n"
        )

    prompt = (
        f"{intro}\n"
        "Focus on:\n"
        f"{focus}\n\n"
        f"Keep the summary under {max_words} words. Write in past tense.\n\n"
        f"{prior_block}"
        "Conversation:\n"
        f"{conversation_text}\n"
        "Summary:"
    )

    return _run_summary_model(prompt)


def generate_summary(agent: Agent, messages: list[dict[str, str]]) -> str:
    """Generate a summary of an autonomous agent's conversation using the LLM.

    Args:
        agent: The agent whose conversation is being summarized
        messages: List of messages to summarize (role, content dicts)

    Returns:
        Summary text
    """
    summary = summarize_messages(
        messages,
        role_labels=("Trigger", "Agent"),
        focus=(
            "1. Key actions taken by the agent\n"
            "2. Important information discovered\n"
            "3. Ongoing tasks or goals\n"
            "4. Any errors or issues encountered"
        ),
        intro=(
            "Summarize this autonomous agent conversation history concisely.\n"
            f"Agent: {agent.name}\n"
            f"Description: {agent.description or 'N/A'}"
        ),
    )
    if summary:
        return summary
    return "Previous conversation history has been compacted due to length."


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

    # Generate summary
    summary = generate_summary(agent, messages_as_dicts)

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
