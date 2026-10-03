"""Grounding annotations travel from the agent to the API and the database."""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_ANNS = [
    {
        "type": "claim",
        "verdict": "not_found",
        "quote": "PřepiServis",
        "prefix": "Answer about ",
        "reason": "Není ve zdrojích.",
    }
]
_SUMMARY = {"checked": True, "source_count": 2}
_ANSWER = "Answer about PřepiServis."
_USAGE = {
    "input_tokens": 50,
    "output_tokens": 10,
    "grounding": {"annotations": _ANNS, "summary": _SUMMARY},
}


def _without_nulls(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _events(lines: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in lines.splitlines()
        if line.startswith("data: ")
    ]


class TestBatchAnnotations:
    def test_response_and_reload_carry_annotations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        with patch("src.api.helpers.chat_turn.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.chat_batch.return_value = (_ANSWER, [], _USAGE, [])
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Who does it?"},
            )

        assert response.status_code == 200
        body = response.get_json()
        assert body["content"] == _ANSWER
        # The output schema writes unset optional fields as null
        assert [_without_nulls(a) for a in body["annotations"]] == _ANNS
        assert _without_nulls(body["grounding"]) == _SUMMARY

        loaded = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers)
        assistant = loaded.get_json()["messages"][-1]
        assert [_without_nulls(a) for a in assistant["annotations"]] == _ANNS
        assert _without_nulls(assistant["grounding"]) == _SUMMARY


class TestStreamAnnotations:
    def test_done_event_carries_annotations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        with patch("src.api.helpers.chat_turn.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": _ANSWER}
                yield {
                    "type": "final",
                    "content": _ANSWER,
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": _USAGE,
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Who does it?"},
            )
            events = _events(response.get_data(as_text=True))

        done = next(e for e in events if e["type"] == "done")
        assert done["content"] == _ANSWER
        assert done["annotations"] == _ANNS
        assert done["grounding"] == _SUMMARY


class TestGroundingStartedEvent:
    def test_forwarded_between_tokens_and_done(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        with patch("src.api.helpers.chat_turn.ChatAgent") as mock_agent_class:
            mock_agent = MagicMock()

            def mock_stream_events(*args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": _ANSWER}
                yield {"type": "grounding_started"}
                yield {
                    "type": "final",
                    "content": _ANSWER,
                    "result_messages": [],
                    "tool_results": [],
                    "usage_info": _USAGE,
                }

            mock_agent.stream_chat_events = mock_stream_events
            mock_agent_class.return_value = mock_agent

            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                headers=auth_headers,
                json={"message": "Who does it?"},
            )
            types = [e["type"] for e in _events(response.get_data(as_text=True))]

        assert types.index("token") < types.index("grounding_started") < types.index("done")
