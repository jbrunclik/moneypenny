"""The stop flag round-trips through kv_store (cross-worker carrier), scoped to one turn."""

from src.agent.cancellation import clear_stop_request, request_stop, stop_requested
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User


def test_stop_flag_lifecycle(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    assert stop_requested(test_user.id, test_conversation.id, "msg-a") is False
    request_stop(test_user.id, test_conversation.id, "msg-a")
    assert stop_requested(test_user.id, test_conversation.id, "msg-a") is True
    clear_stop_request(test_user.id, test_conversation.id, "msg-a")
    assert stop_requested(test_user.id, test_conversation.id, "msg-a") is False


def test_stop_for_one_turn_does_not_match_another(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    request_stop(test_user.id, test_conversation.id, "msg-b")
    assert stop_requested(test_user.id, test_conversation.id, "msg-a") is False


def test_an_older_turn_ending_does_not_clear_the_current_turns_stop(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    """Turn A (aborted client-side, still running) finishes after turn B's Stop was sent."""
    request_stop(test_user.id, test_conversation.id, "msg-b")
    clear_stop_request(test_user.id, test_conversation.id, "msg-a")  # A's finally
    assert stop_requested(test_user.id, test_conversation.id, "msg-b") is True
