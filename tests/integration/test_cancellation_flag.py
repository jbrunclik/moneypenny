"""The stop flag round-trips through kv_store (cross-worker carrier)."""

from src.agent.cancellation import clear_stop_request, request_stop, stop_requested
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User


def test_stop_flag_lifecycle(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    assert stop_requested(test_user.id, test_conversation.id) is False
    request_stop(test_user.id, test_conversation.id)
    assert stop_requested(test_user.id, test_conversation.id) is True
    clear_stop_request(test_user.id, test_conversation.id)
    assert stop_requested(test_user.id, test_conversation.id) is False
