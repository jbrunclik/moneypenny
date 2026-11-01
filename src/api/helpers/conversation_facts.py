"""Conversation facts around a chat turn: loaded into it, recorded after it.

Ordinary chats only - planner, sports and language conversations keep their
own notebooks, agent conversations are not the user's chat, and an anonymous
conversation keeps nothing (docs/features/conversation-facts.md).
"""

from langchain_core.messages import BaseMessage

from src.agent.content import extract_fact_edits
from src.config import Config
from src.db.models import Conversation, ConversationFact, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def facts_eligible(conv: Conversation, anonymous_mode: bool) -> bool:
    """Whether this conversation keeps a facts list."""
    return Config.CONVERSATION_FACTS_ENABLED and not (
        anonymous_mode
        or conv.anonymous_mode
        or conv.is_planning
        or conv.is_sports
        or conv.is_language
        or conv.is_agent
    )


def load_turn_facts(conv: Conversation, anonymous_mode: bool) -> list[ConversationFact] | None:
    """The facts for the turn's context; None where the conversation keeps none."""
    return db.get_conversation_facts(conv.id) if facts_eligible(conv, anonymous_mode) else None


def record_turn_facts(
    conv_id: str, user_id: str, message_id: str, result_messages: list[BaseMessage]
) -> None:
    """Apply the turn's record_conversation_facts edits to its saved reply.

    Best-effort: the reply is already saved, a facts failure must not undo it.
    """
    try:
        conv = db.get_conversation(conv_id, user_id)
        if conv is None or not facts_eligible(conv, anonymous_mode=False):
            return
        sets, removes = extract_fact_edits(result_messages)
        if not (sets or removes):
            return
        result = db.apply_conversation_facts(conv_id, user_id, message_id, sets, removes)
        logger.info(
            "Conversation facts recorded",
            extra={
                "conversation_id": conv_id,
                "message_id": message_id,
                "applied": result.applied,
                "rejected": result.rejected,
            },
        )
    except Exception:
        logger.warning("Recording conversation facts failed", exc_info=True)
