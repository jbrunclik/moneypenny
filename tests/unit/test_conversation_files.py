"""The shared loader for files uploaded in the current conversation.

retrieve_file and execute_code(files=...) both resolve a history file id
(``message_id:file_index``) through it, with the same ownership, conversation
and retention checks.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.conversation_files import (
    ConversationFile,
    load_conversation_file,
    parse_file_id,
)
from src.db.models.helpers import save_file_to_blob_store
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, User


@pytest.fixture
def conversation(
    test_database: Database, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> Generator[str]:
    import src.agent.tools.conversation_files as module

    monkeypatch.setattr(module, "db", test_database)
    conv = test_database.create_conversation(test_user.id, "Flat")
    set_conversation_context(conv.id, test_user.id)
    yield conv.id
    set_conversation_context(None, None)


def _upload(
    database: Database, conv_id: str, name: str = "plan.pdf", data: bytes = b"%PDF-1"
) -> str:
    file = {"name": name, "type": "application/pdf", "data": base64.b64encode(data).decode()}
    message = database.add_message(conv_id, "user", "Here is the plan", files=[file])
    save_file_to_blob_store(message.id, 0, file)
    return message.id


def test_parse_file_id() -> None:
    assert parse_file_id("m1:0") == ("m1", 0)
    for bad in ["m1", ":1", "m1:x", "m1:-1", ""]:
        assert parse_file_id(bad) is None


def test_loads_a_file_of_the_current_conversation(
    test_database: Database, conversation: str
) -> None:
    message_id = _upload(test_database, conversation, data=b"%PDF-plan")

    loaded = load_conversation_file(message_id, 0)

    assert loaded == ConversationFile(
        file_id=f"{message_id}:0", name="plan.pdf", mime_type="application/pdf", data=b"%PDF-plan"
    )


def test_refuses_a_message_of_another_conversation(
    test_database: Database, test_user: User, conversation: str
) -> None:
    other = test_database.create_conversation(test_user.id, "Other")
    message_id = _upload(test_database, other.id)

    result = load_conversation_file(message_id, 0)

    assert isinstance(result, str)
    assert "does not belong to this conversation" in json.loads(result)["error"]


def test_refuses_an_expired_attachment(
    test_database: Database, conversation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_id = _upload(test_database, conversation)
    from src.utils import clock

    later = utc_now() + timedelta(days=31)
    monkeypatch.setattr(clock, "_now", lambda: later)

    result = load_conversation_file(message_id, 0)

    assert isinstance(result, str)
    assert "cleaned up" in json.loads(result)["error"]


def test_index_out_of_range_names_the_file_count(
    test_database: Database, conversation: str
) -> None:
    message_id = _upload(test_database, conversation)

    result = load_conversation_file(message_id, 3)

    assert isinstance(result, str)
    assert "1 file(s)" in json.loads(result)["error"]
