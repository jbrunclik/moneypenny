"""A Todoist task read in full stays whole for the rest of the turn.

Nov 15 2026: the agent read a task with a 9.7k-char description, ran other
tools, and by the next round the description was aged to 2,000 chars - it
then said it had no way to read a description that long. A single task is
what the agent edits from; a 56k task list may still be aged.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.agent.tool_result_aging import AGED_TRUNCATION_MARKER, age_consumed_tool_messages

_LONG = "Plan step. " * 1000  # ~11k chars


def _round(call_id: str, action: str) -> list[BaseMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[{"id": call_id, "name": "todoist", "args": {"action": action}}],
        ),
        ToolMessage(
            content=json.dumps({"task": {"id": "t1", "description": _LONG}}),
            tool_call_id=call_id,
            name="todoist",
        ),
    ]


def _aged(first_action: str) -> str:
    messages: list[BaseMessage] = [
        HumanMessage(content="Rewrite the plan in my task"),
        *_round("c1", first_action),
        *_round("c2", "list_projects"),  # a later round: c1 is now consumed
    ]
    age_consumed_tool_messages(messages)
    return str(messages[2].content)


def test_a_single_task_read_stays_whole() -> None:
    assert AGED_TRUNCATION_MARKER not in _aged("get_task")
    assert _LONG in _aged("get_task")


def test_a_task_list_is_still_aged() -> None:
    assert AGED_TRUNCATION_MARKER in _aged("list_tasks")


def test_the_marker_says_how_to_get_it_back() -> None:
    assert "call the tool again" in AGED_TRUNCATION_MARKER
