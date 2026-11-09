"""ask_choice: a clarifying question with 2-4 options on a card; the pick is
the user's reply (one approval mechanism, step 5, docs/features/proposals.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from src.agent.proposals import start_turn
from src.agent.tool_results import set_current_request_id
from src.agent.tools.ask_choice import ask_choice
from src.agent.tools.context import set_conversation_context
from src.db.models import use_database
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal


@pytest.fixture
def chat(test_database: Database, test_conversation: Conversation) -> Iterator[Conversation]:
    with use_database(test_database):
        set_conversation_context(test_conversation.id, test_conversation.user_id)
        set_current_request_id("turn-1")
        yield test_conversation
        set_conversation_context(None, None)
        set_current_request_id(None)


def _ask(question: str = "Which dentist appointment?", options: list[str] | None = None) -> str:
    choices = options if options is not None else ["Thursday 9:00", "Friday 14:30"]
    return str(ask_choice.invoke({"question": question, "options": choices}))


def _shown(db: Database, conv: Conversation) -> Proposal:
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "Which one?")
    db.link_proposals("turn-1", reply.id)
    [card] = db.pending_proposals(conv.id)
    return card


class TestToolSchema:
    def test_every_param_has_a_concrete_type(self) -> None:
        for name, schema in ask_choice.args.items():
            assert "type" in schema or "anyOf" in schema, name
        assert ask_choice.args["options"]["items"]["type"] == "string"


def test_the_question_goes_on_a_card_with_its_options(
    chat: Conversation, test_database: Database
) -> None:
    result = _ask()

    assert result.startswith("QUESTION shown to the user")
    [card] = test_database.pending_proposals(chat.id)
    assert (card.kind, card.summary) == ("question", "Which dentist appointment?")
    assert [o["label"] for o in card.options] == ["Thursday 9:00", "Friday 14:30"]


@pytest.mark.parametrize(
    ("options", "why"),
    [
        (["Only one"], "2-4"),
        (["A", "B", "C", "D", "E"], "2-4"),
        (["Morning", "morning"], "different"),
        (["Yes", "Something else"], "yes or no"),
        (["1", "2"], "number"),
        (["x" * 61, "B"], "short"),
    ],
)
def test_options_that_cannot_be_told_apart_are_refused(
    chat: Conversation, test_database: Database, options: list[str], why: str
) -> None:
    result = json.loads(_ask(options=options))

    assert why in result["error"]
    assert test_database.pending_proposals(chat.id) == []


@pytest.mark.parametrize("reply", ["Friday 14:30", "friday 14:30!"])
def test_the_pick_answers_it_and_the_agent_hears_which(
    chat: Conversation, test_database: Database, reply: str
) -> None:
    _ask()
    _shown(test_database, chat)

    note, [answered] = start_turn(chat.id, reply)

    assert (answered.state, answered.chosen) == ("approved", 1)
    assert note == "The user picked for “Which dentist appointment?”: Friday 14:30"


def test_an_answer_in_their_own_words_closes_it(
    chat: Conversation, test_database: Database
) -> None:
    _ask()
    _shown(test_database, chat)

    note, answered = start_turn(chat.id, "neither, next week")

    assert answered == []
    assert note == "The question was closed without a pick: Which dentist appointment?"


def test_a_yes_is_no_pick(chat: Conversation, test_database: Database) -> None:
    _ask()
    _shown(test_database, chat)

    _note, answered = start_turn(chat.id, "yes")

    assert answered == []


def test_it_is_a_chat_tool_never_an_agents() -> None:
    from src.agent.tools import get_tools_for_request, tools_for_grants

    assert "ask_choice" in {t.name for t in get_tools_for_request()}
    assert "ask_choice" not in {t.name for t in get_tools_for_request(is_planning=True)}
    assert "ask_choice" not in {t.name for t in tools_for_grants(["*"], "u1")}


def test_a_pick_answers_only_the_question_not_a_delete_beside_it(
    chat: Conversation, test_database: Database
) -> None:
    """ "Smazat" picks the option; it must not also approve the held delete."""
    from unittest.mock import patch

    with (
        patch("src.agent.tools.todoist.todoist_client.get_todoist_token", return_value="t"),
        patch("src.agent.tools.todoist_client.todoist_api_request", return_value=None) as api,
    ):
        from src.agent.tools.todoist import todoist

        todoist.invoke({"action": "delete_task", "task_id": "t1"})
        _ask("Co s tím úkolem?", ["Smazat", "Nechat"])
        reply = test_database.add_message(chat.id, MessageRole.ASSISTANT, "Which?")
        test_database.link_proposals("turn-1", reply.id)

        _note, answered = start_turn(chat.id, "Smazat")

    assert [(p.kind, p.state) for p in answered] == [("question", "approved")]
    assert not any(c.args[0] == "DELETE" for c in api.call_args_list)


@pytest.mark.parametrize("options", [["Friday", "Friday!"], ["A, B", "A B"], ["2.", "Thursday"]])
def test_options_the_server_reads_alike_are_refused(
    chat: Conversation, test_database: Database, options: list[str]
) -> None:
    assert "error" in json.loads(_ask(options=options))


def test_a_question_closed_without_a_pick_says_so_neutrally(
    chat: Conversation, test_database: Database
) -> None:
    _ask()
    _shown(test_database, chat)

    note, _ = start_turn(chat.id, "")  # an app-sent message: no answer

    assert note == "The question was closed without a pick: Which dentist appointment?"


def test_a_bare_number_is_no_pick(chat: Conversation, test_database: Database) -> None:
    """ "2" may be the user's own answer (two tickets): only a label picks."""
    _ask()
    _shown(test_database, chat)

    _note, answered = start_turn(chat.id, "2")

    assert answered == []
