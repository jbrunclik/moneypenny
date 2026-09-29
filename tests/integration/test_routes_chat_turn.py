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
from src.agent.tools.context import get_conversation_context
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
    assert get_current_request_id() is None
    assert get_conversation_context() == (None, None)


def test_batch_agent_conversation_uses_the_resolved_system_prompt(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    """System agents store no prompt; batch mode must resolve it like streaming."""
    agent = test_database.create_agent(
        user_id=test_user.id, name="Briefing", system_type=SYSTEM_TYPE_DAILY_BRIEFING
    )
    assert agent.conversation_id
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        instance = MagicMock()
        instance.chat_batch.return_value = ("Morning!", [], _USAGE, [])
        agent_class.return_value = instance
        response = _batch(client, agent.conversation_id, auth_headers)

    assert response.status_code == 200
    goals = agent_class.call_args.kwargs["agent_context"]["goals"]
    assert goals == SYSTEM_AGENT_PROMPTS[SYSTEM_TYPE_DAILY_BRIEFING]


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
