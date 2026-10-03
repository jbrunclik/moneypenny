"""A deep-research turn runs on the stream: events, saved report, finish-now."""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from flask.testing import FlaskClient

from src.agent.deep_research.offer import build_offer
from src.api.schemas.common import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_RUN = {"round": 1, "sub_questions": ["a", "b"], "items": [{"status": "done", "pages": 1}] * 2}


def _fake_pipeline(
    plan: Any, recent_turns: str, request_id: str, finish_requested: Any = None
) -> Any:
    yield {"type": "research_plan", "items": plan.sub_questions}
    yield {"type": "research_item", "index": 0, "status": "started"}
    yield {"type": "research_finding", "agent": 0, "text": "Price 1 590 Kč"}
    yield {"type": "research_item", "index": 0, "status": "done", "pages": 1}
    yield {"type": "research_sources", "count": 1}
    yield {"type": "research_writing"}
    yield {"type": "token", "text": "Report."}
    yield {
        "type": "final",
        "content": "Report.",
        "result_messages": [],
        "tool_results": [],
        "usage_info": {
            "input_tokens": 10,
            "output_tokens": 5,
            "answer_model": "gemini-3.1-pro-preview",
            "research_run": _RUN,
            "research_sources": [{"title": "A", "url": "https://a.cz"}],
        },
    }


def _events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_deep_turn_streams_research_events_and_saves_the_report(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    offer = build_offer({"question": "Q", "context": "", "sub_questions": ["a", "b"]})
    offer_id = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "quick", research={"offer": offer}
    ).id

    with patch("src.api.helpers.stream_producer.run_deep_research", _fake_pipeline):
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={
                "message": "Start deep research",
                "deep_research": {
                    "offer_message_id": offer_id,
                    "sub_questions": ["a", "b"],
                    "context": "",
                },
            },
        )
        events = _events(response.get_data(as_text=True))

    types = [e["type"] for e in events]
    for expected in (
        "research_plan",
        "research_item",
        "research_finding",
        "research_sources",
        "research_writing",
    ):
        assert expected in types
    done = next(e for e in events if e["type"] == "done")
    assert done["research"]["run"]["sub_questions"] == ["a", "b"]
    assert done["sources"] == [{"title": "A", "url": "https://a.cz"}]


def test_finish_now_sets_the_flag(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_user: Any,
) -> None:
    from src.agent.cancellation import finish_now_requested

    response = client.post(
        f"/api/conversations/{test_conversation.id}/chat/finish-now",
        headers=auth_headers,
        json={"message_id": "assistant-1"},
    )

    assert response.status_code == 200
    assert finish_now_requested(test_user.id, test_conversation.id, "assistant-1")
    assert not finish_now_requested(test_user.id, test_conversation.id, "another-turn")
