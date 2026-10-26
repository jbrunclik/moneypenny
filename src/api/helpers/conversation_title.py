"""A turn's conversation title change: generated on the first exchange,
the agent's set_conversation_title retitle afterwards (see chat_save.py).
"""

from __future__ import annotations

from typing import Any

from src.agent.cancellation import STOPPED_EMPTY_TEXT
from src.agent.content import extract_conversation_title
from src.agent.title import generate_title
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def resolve_title_update(
    conv_id: str,
    user_id: str,
    message_text: str,
    content: str,
    result_messages: list[Any],
) -> str | None:
    """Resolve the conversation title change for this turn, if any.

    First exchange (title still default): auto-generate via generate_title,
    which takes precedence over any set_conversation_title call in the same
    turn. Later turns: apply the agent's set_conversation_title retitle when
    it differs from the current title. Program conversations (sports, language,
    planner) are never retitled.

    Wrapped in its own try/except so a title failure can never abort the
    message save (which already succeeded).
    """
    conv = db.get_conversation(conv_id, user_id)
    if not conv:
        return None

    try:
        if conv.title == Config.DEFAULT_CONVERSATION_TITLE:
            logger.debug(
                "Auto-generating conversation title from stream",
                extra={"user_id": user_id, "conversation_id": conv_id},
            )
            # The Stop placeholder says nothing about the topic
            reply = "" if content == STOPPED_EMPTY_TEXT else content
            new_title = generate_title(message_text, reply)
        elif conv.is_sports or conv.is_language or conv.is_planning:
            return None
        else:
            new_title = extract_conversation_title(result_messages)
            if new_title == conv.title:
                return None

        if new_title is not None:
            db.update_conversation(conv_id, user_id, title=new_title)
            logger.debug(
                "Conversation title updated from stream",
                extra={
                    "user_id": user_id,
                    "conversation_id": conv_id,
                    "title": new_title,
                },
            )
        return new_title
    except Exception:
        logger.exception(
            "Title generation/update failed (continuing without title)",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
        return None
