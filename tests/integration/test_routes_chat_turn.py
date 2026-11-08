"""Batch and streaming chat share one turn setup (src/api/helpers/chat_turn.py).

Regression tests for the ways the two hand-kept copies had drifted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

from src.agent.daily_briefing import SYSTEM_AGENT_PROMPTS, SYSTEM_TYPE_DAILY_BRIEFING
from src.agent.executor import get_agent_context
from src.agent.tool_results import get_current_request_id
from src.agent.tools.context import get_conversation_context, get_standing_namespace
from src.db.models import Database, User

_USAGE = {"input_tokens": 10, "output_tokens": 5}


def _batch(client: FlaskClient, conv_id: str, headers: dict[str, str]) -> Any:
    return client.post(
        f"/api/conversations/{conv_id}/chat/batch", headers=headers, json={"message": "hi"}
    )


def test_batch_clears_request_context_when_the_agent_raises(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    """Worker threads are reused: a failed turn must not leak its context."""
    agent = test_database.create_agent(user_id=test_user.id, name="Helper")
    assert agent.conversation_id
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent_class.return_value.chat_batch.side_effect = RuntimeError("model exploded")
        response = _batch(client, agent.conversation_id, auth_headers)

    assert response.status_code == 500
    assert get_agent_context() is None
    assert get_standing_namespace() is None
    assert get_current_request_id() is None
    assert get_conversation_context() == (None, None)


def _captured_turn(client: FlaskClient, conv_id: str, headers: dict[str, str]) -> MagicMock:
    """Run a batch turn with a fake ChatAgent; returns the ChatAgent class mock."""
    seen: dict[str, Any] = {}

    def chat_batch(**_: Any) -> tuple[str, list[Any], dict[str, int], list[Any]]:
        seen["agent_context"] = get_agent_context()
        seen["namespace"] = get_standing_namespace()
        return ("ok", [], _USAGE, [])

    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent_class.return_value.chat_batch.side_effect = chat_batch
        response = _batch(client, conv_id, headers)
    assert response.status_code == 200, response.get_json()
    agent_class.seen = seen
    return agent_class


def test_an_agent_chat_runs_as_an_ordinary_turn(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    """Standing chats: writing in an agent's chat is an ordinary chat turn with
    the agent's instructions - not its unattended-run restrictions."""
    agent = test_database.create_agent(
        user_id=test_user.id,
        name="Helper",
        system_prompt="Help with the garden",
        tool_permissions=[],
    )
    assert agent.conversation_id

    agent_class = _captured_turn(client, agent.conversation_id, auth_headers)

    kwargs = agent_class.call_args.kwargs
    assert "is_autonomous" not in kwargs and "agent_context" not in kwargs
    assert kwargs["standing"].kind == "agent"
    assert "Help with the garden" in kwargs["standing"].instructions
    assert agent_class.seen == {"agent_context": None, "namespace": f"agent:{agent.id}"}


def test_the_briefing_chat_carries_the_stock_prompt(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    """System agents store no prompt; the chat turn resolves it like a run."""
    agent = test_database.create_agent(
        user_id=test_user.id, name="Briefing", system_type=SYSTEM_TYPE_DAILY_BRIEFING
    )
    assert agent.conversation_id

    agent_class = _captured_turn(client, agent.conversation_id, auth_headers)

    standing = agent_class.call_args.kwargs["standing"]
    assert SYSTEM_AGENT_PROMPTS[SYSTEM_TYPE_DAILY_BRIEFING] in standing.instructions


def test_a_sports_chat_runs_as_an_ordinary_turn(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    import json

    test_database.kv_set(
        test_user.id, "sports", "programs", json.dumps([{"id": "cycling", "name": "Cycling"}])
    )
    conv = test_database.get_or_create_program_conversation("sports", test_user.id, "cycling")

    agent_class = _captured_turn(client, conv.id, auth_headers)

    standing = agent_class.call_args.kwargs["standing"]
    assert (standing.kind, standing.name) == ("sports", "Cycling")
    assert agent_class.seen["namespace"] == "sports"


def test_an_agent_chat_history_is_compacted_like_any_chat(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    agent = test_database.create_agent(user_id=test_user.id, name="Helper")
    assert agent.conversation_id
    with patch(
        "src.api.helpers.chat_turn.build_compacted_history", side_effect=lambda u, c, h: h
    ) as compact:
        _captured_turn(client, agent.conversation_id, auth_headers)

    assert compact.call_args.args[1] == agent.conversation_id


def test_pending_approval_still_blocks(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    """A run paused for approval still holds its chat (unchanged)."""
    agent = test_database.create_agent(user_id=test_user.id, name="Helper")
    assert agent.conversation_id
    test_database.create_approval_request(
        agent_id=agent.id,
        user_id=test_user.id,
        tool_name="todoist",
        tool_args={"action": "delete_task"},
        description="Delete a task",
    )

    response = _batch(client, agent.conversation_id, auth_headers)

    assert response.status_code == 400
    assert "awaiting approval" in str(response.get_json())


def test_batch_response_includes_code_output_files(
    client: FlaskClient, auth_headers: dict[str, str], test_conversation: Any
) -> None:
    """Batch returned only generated images; code-execution files appeared
    only after a reload (streaming already sent both)."""
    output_file = {"name": "plot.png", "type": "image/png", "data": "iVBORw0KGgo="}
    with (
        patch("src.api.helpers.chat_turn.ChatAgent") as agent_class,
        patch(
            "src.api.helpers.chat_save.extract_code_output_files_from_tool_results",
            return_value=[output_file],
        ),
    ):
        instance = MagicMock()
        instance.chat_batch.return_value = ("", [], _USAGE, [])
        agent_class.return_value = instance
        response = _batch(client, test_conversation.id, auth_headers)

    assert response.status_code == 200
    data = response.get_json()
    assert [f["name"] for f in data["files"]] == ["plot.png"]
    # A files-only turn still gets visible text
    assert data["content"]
