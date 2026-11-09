"""Deletes and archives asked for in chat wait on the turn's card; approving
performs exactly those calls (docs/features/proposals.md, step 4)."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.proposals import answer_typed, resolve
from src.agent.tool_results import set_current_request_id
from src.agent.tools.context import set_conversation_context
from src.db.models import use_database
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal


def _fake_api(method: str, path: str, token: str, **_: Any) -> Any:
    """Todoist: a task's name by id; writes succeed."""
    if method == "GET" and path.startswith("/tasks/"):
        return {"id": path.split("/")[2], "content": f"Task {path.split('/')[2]}"}
    return None


@pytest.fixture
def api(test_database: Database, test_conversation: Conversation) -> Iterator[MagicMock]:
    """A chat turn in the test conversation, with Todoist connected."""
    with (
        use_database(test_database),
        patch("src.agent.tools.todoist.todoist_client.get_todoist_token", return_value="t"),
        patch(
            "src.agent.tools.todoist_client.todoist_api_request", side_effect=_fake_api
        ) as request,
    ):
        set_conversation_context(test_conversation.id, test_conversation.user_id)
        set_current_request_id("turn-1")
        yield request
        set_conversation_context(None, None)
        set_current_request_id(None)


def _delete(task_id: str) -> str:
    from src.agent.tools.todoist import todoist

    return str(todoist.invoke({"action": "delete_task", "task_id": task_id}))


def _deletes(api: MagicMock) -> list[str]:
    return [c.args[1] for c in api.call_args_list if c.args[0] == "DELETE"]


def _card(db: Database, conv: Conversation) -> Proposal:
    [card] = db.pending_proposals(conv.id)
    return card


def _shown(db: Database, conv: Conversation) -> Proposal:
    """The turn's reply is saved: its card shows under it."""
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Shall I?")
    db.link_proposals("turn-1", reply.id)
    return _card(db, conv)


def test_a_delete_in_chat_waits_on_its_card(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    result = _delete("t1")

    assert result.startswith("PROPOSAL shown to the user as a card")
    assert _deletes(api) == []
    card = _card(test_database, test_conversation)
    assert (card.kind, card.summary) == ("chat_change", "Delete task “Task t1”")
    assert card.details == {"Delete task": "Task t1"}
    assert [o["label"] for o in card.options] == ["Delete"]


def test_a_turns_deletes_share_one_card(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    _delete("t1")
    _delete("t2")

    card = _card(test_database, test_conversation)
    assert card.summary == "Delete 2 items"
    assert list(card.details.values()) == ["Task t1", "Task t2"]


def test_parallel_deletes_in_one_round_share_one_card(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [pool.submit(copy_context().run, _delete, t) for t in ("t1", "t2")]
        [r.result() for r in runs]

    card = _card(test_database, test_conversation)
    assert sorted(card.details.values()) == ["Task t1", "Task t2"]


def test_approving_performs_exactly_the_stored_calls(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    _delete("t1")
    _delete("t2")
    card = _shown(test_database, test_conversation)
    set_conversation_context(None, None)  # the approve request has no turn of its own

    done = resolve(card, 0, "button")

    assert done.state == "approved"
    assert _deletes(api) == ["/tasks/t1", "/tasks/t2"]
    assert done.result == "Done - task “Task t1”, task “Task t2”."
    assert test_database.pending_proposals(test_conversation.id) == []  # no new card


def test_a_partial_failure_says_what_was_not_done(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    def fail_t2(method: str, path: str, token: str, **kw: Any) -> Any:
        if method == "DELETE" and path == "/tasks/t2":
            raise RuntimeError("404 Not Found")
        return _fake_api(method, path, token, **kw)

    _delete("t1")
    _delete("t2")
    card = _shown(test_database, test_conversation)
    api.side_effect = fail_t2

    done = resolve(card, 0, "button")

    assert done.state == "approved"
    assert done.result is not None and done.result.startswith("Done 1 of 2")
    assert "Task t2" in done.result


def test_when_nothing_could_be_done_the_card_failed(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    _delete("t1")
    card = _shown(test_database, test_conversation)
    api.side_effect = RuntimeError("Todoist is down")

    done = resolve(card, 0, "button")

    assert done.state == "failed"
    assert done.result is not None and "Task t1" in done.result


def test_a_typed_yes_approves_it(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    _delete("t1")
    _shown(test_database, test_conversation)

    [done] = answer_typed(test_conversation.id, "ano")

    assert done.state == "approved"
    assert _deletes(api) == ["/tasks/t1"]


def test_other_changes_run_at_once(api: MagicMock) -> None:
    from src.agent.tools.todoist import todoist

    todoist.invoke({"action": "complete_task", "task_id": "t1"})

    assert any(c.args[0] == "POST" for c in api.call_args_list)


def test_a_failed_lookup_shows_the_id(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    api.side_effect = RuntimeError("timeout")

    _delete("t9")

    assert _card(test_database, test_conversation).details == {"Delete task": "t9"}


@pytest.mark.parametrize("reply", ["yes please", "smaž to", "Delete it", "ano, smazat"])
def test_a_plain_go_ahead_approves_it(
    reply: str, api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    """A delete's own verb, or a polite yes, answers its card (no confirm loop)."""
    _delete("t1")
    _shown(test_database, test_conversation)

    [done] = answer_typed(test_conversation.id, reply)

    assert done.state == "approved"


def test_a_repeated_call_is_not_a_second_row(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    """The model re-checking and calling the same delete again changes nothing."""
    _delete("t1")
    _delete("t1")

    assert _card(test_database, test_conversation).details == {"Delete task": "Task t1"}


def test_a_delete_without_its_item_gets_the_tools_own_error(
    api: MagicMock, test_database: Database, test_conversation: Conversation
) -> None:
    from src.agent.tools.todoist import todoist

    result = str(todoist.invoke({"action": "delete_task"}))

    assert not result.startswith("PROPOSAL")
    assert test_database.pending_proposals(test_conversation.id) == []


def test_a_calendar_event_is_named_with_its_day_and_time() -> None:
    google_calendar = importlib.import_module("src.agent.tools.google_calendar")
    event = {"summary": "Dentist", "start": {"dateTime": "2026-11-12T09:00:00+01:00"}}
    with (
        patch.object(
            google_calendar, "_get_google_calendar_access_token", return_value=("t", None)
        ),
        patch.object(google_calendar, "_google_calendar_api_request", return_value=event),
    ):
        assert google_calendar.event_label({"event_id": "e1"}) == "Dentist (Thu 12 Nov 09:00)"


def test_an_untitled_event_is_named_by_its_time() -> None:
    google_calendar = importlib.import_module("src.agent.tools.google_calendar")
    event = {"start": {"date": "2026-11-12"}}
    with (
        patch.object(
            google_calendar, "_get_google_calendar_access_token", return_value=("t", None)
        ),
        patch.object(google_calendar, "_google_calendar_api_request", return_value=event),
    ):
        assert google_calendar.event_label({"event_id": "e1"}) == "(no title) (Thu 12 Nov)"
