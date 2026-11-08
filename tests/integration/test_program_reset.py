"""Resetting a program chat starts it clean: no messages, no facts and no
running summary left from before the reset."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Database, User


def test_reset_clears_compaction_and_facts(test_database: Database, test_user: User) -> None:
    conv = test_database.get_or_create_program_conversation("sports", test_user.id, "cycling")
    reply = test_database.add_message(conv.id, MessageRole.ASSISTANT, "Your FTP is 260")
    test_database.apply_conversation_facts(conv.id, test_user.id, reply.id, [("ftp", "260 W")], [])
    test_database.kv_set(
        test_user.id,
        "conv_compaction",
        conv.id,
        json.dumps({"summary": "old", "covered_count": 40}),
    )

    test_database.reset_program_conversation("sports", test_user.id, "cycling")

    assert test_database.get_messages(conv.id) == []
    assert test_database.get_conversation_facts(conv.id) == []
    assert test_database.kv_get(test_user.id, "conv_compaction", conv.id) is None
