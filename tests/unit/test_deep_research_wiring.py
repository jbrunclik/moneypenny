"""Deep research in the stream, cost and history layers."""

from datetime import datetime

from src.agent.deep_research.briefs import recent_turns_text
from src.agent.history import enrich_history
from src.agent.message_content import format_message_with_metadata
from src.api.helpers.chat_streaming import FORWARDED_EVENT_TYPES
from src.api.helpers.stream_resume import _JOURNALED_EVENT_TYPES
from src.api.schemas.common import MessageRole
from src.api.utils import calculate_deep_research_cost
from src.db.models.dataclasses import Message

_RESEARCH_EVENTS = {
    "research_plan",
    "research_item",
    "research_finding",
    "research_sources",
    "research_writing",
}


def test_research_events_are_forwarded_and_journaled() -> None:
    assert _RESEARCH_EVENTS <= set(FORWARDED_EVENT_TYPES)
    assert _RESEARCH_EVENTS <= _JOURNALED_EVENT_TYPES


def test_subagent_usage_is_priced_at_its_model() -> None:
    usage = {
        "deep_research_usage": [
            {
                "model": "gemini-3.8-flash",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cached_input_tokens": 0,
            },
            {
                "model": "gemini-3.8-flash",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cached_input_tokens": 0,
            },
        ]
    }
    from src.utils.costs import calculate_token_cost

    one = calculate_token_cost("gemini-3.8-flash", 1_000_000, 0)
    assert calculate_deep_research_cost(usage) == 2 * one
    assert calculate_deep_research_cost({}) == 0.0


def test_history_carries_the_research_entry() -> None:
    msg = Message(
        id="m1",
        conversation_id="c1",
        role=MessageRole.ASSISTANT,
        content="Report.",
        created_at=datetime.now(),
        research={"run": {"round": 2, "sub_questions": ["prices", "speed"]}},
    )

    [enriched] = enrich_history([msg])

    assert enriched["metadata"]["research"] == "deep research round 2: prices; speed"
    assert '"research":"deep research round 2' in format_message_with_metadata(enriched)


def test_recent_turns_text_is_compact() -> None:
    history = [
        {"role": "user", "content": "Kterou agenturu?", "metadata": {}},
        {"role": "assistant", "content": "Možná SPZ Služby." * 50, "metadata": {}},
    ]

    text = recent_turns_text(history)

    assert text.startswith("user: Kterou agenturu?")
    assert len(text) < 1200
