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


def generate_summary(agent: Agent, messages: list[dict[str, str]]) -> str:
    """Generate a summary of conversation messages using the LLM.

    Args:
        agent: The agent whose conversation is being summarized
        messages: List of messages to summarize (role, content dicts)

    Returns:
        Summary text
    """
    # Import here to avoid circular imports
    from google import genai
    from google.genai.types import GenerateContentConfig

    # Build the conversation text for summarization
    conversation_text = ""
    for msg in messages:
        role = "Agent" if msg["role"] == "assistant" else "Trigger"
        conversation_text += f"{role}: {msg['content'][:500]}...\n\n"

    # Use a fast model for summarization
    client = genai.Client(api_key=Config.GEMINI_API_KEY)

    prompt = f"""Summarize this autonomous agent conversation history concisely.
Focus on:
1. Key actions taken by the agent
2. Important information discovered
3. Ongoing tasks or goals
4. Any errors or issues encountered

Keep the summary under 500 words. Write in past tense.

Agent: {agent.name}
Description: {agent.description or "N/A"}

Conversation:
{conversation_text}

Summary:"""

    try:
        response = client.models.generate_content(
            model=Config.AI_ASSIST_MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.3,  # More deterministic for summaries
            ),
        )

        if response.text:
            return response.text.strip()
        return "Previous conversation history has been compacted."

    except Exception as e:
        logger.error(
            "Failed to generate conversation summary",
            extra={"agent_id": agent.id, "error": str(e)},
        )
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
