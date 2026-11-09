"""Answer-only turns: the user's typed answer to a run's card.

The card resolves before the agent would run (prepare_turn), and the resumed
- or ended - run is the reply, so the turn runs no agent: the batch response
and the stream's done event carry the answered cards and no assistant reply
(docs/features/proposals.md). The run's report arrives through the agent
conversation's sync.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING

from src.api.utils import proposal_to_response
from src.db.models import db

if TYPE_CHECKING:
    from src.api.helpers.chat_turn import PreparedTurn


def answer_only_body(turn: PreparedTurn) -> dict[str, object]:
    """The batch response (and the done event's fields) for an answer-only turn."""
    return {
        "answer_only": True,
        "user_message_id": turn.user_msg.id,
        "answered_proposals": [proposal_to_response(p) for p in turn.answered_proposals],
        "message_count": db.count_messages(turn.conv.id),
    }


def answer_only_stream(turn: PreparedTurn) -> Generator[str]:
    """The stream for an answer-only turn: the user message is saved, done."""
    saved = {"type": "user_message_saved", "user_message_id": turn.user_msg.id}
    yield f"data: {json.dumps(saved)}\n\n"
    yield f"data: {json.dumps({'type': 'done', **answer_only_body(turn)})}\n\n"
