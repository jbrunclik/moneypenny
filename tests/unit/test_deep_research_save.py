"""Saving a deep-research report: run data, sources, follow-up offer, pricing."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent.deep_research.offer import build_offer
from src.api.helpers import chat_save
from src.api.schemas.common import MessageRole


@pytest.fixture
def save(test_database: Any, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(chat_save, "db", test_database)
    priced = MagicMock()
    monkeypatch.setattr(chat_save, "calculate_and_save_message_cost", priced)
    monkeypatch.setattr(chat_save, "_resolve_title_update", MagicMock(return_value=None))
    return priced


def _usage(followup: bool = True) -> dict[str, Any]:
    run: dict[str, Any] = {
        "round": 1,
        "sub_questions": ["a"],
        "items": [{"status": "done", "pages": 1}],
    }
    if followup:
        run["followup"] = build_offer(
            {"question": "Q", "context": "", "sub_questions": ["next?"]}, kind="followup", round_=2
        )
    return {
        "input_tokens": 900,
        "output_tokens": 300,
        "answer_model": "gemini-3.1-pro-preview",
        "research_run": run,
        "research_sources": [{"title": "A", "url": "https://a.cz"}],
    }


def test_report_stores_run_sources_and_prices_at_the_writer(
    save: MagicMock, test_database: Any, test_conversation: Any
) -> None:
    saved = chat_save.save_message_to_db(
        "Report.",
        [],
        [],
        _usage(),
        test_conversation.id,
        test_conversation.user_id,
        "gemini-3.8-flash",
        "Start deep research",
        "req",
        True,
    )

    assert saved is not None
    msg = test_database.get_message_by_id(saved.message_id)
    assert msg.research["run"]["followup"]["status"] == "offered"
    assert msg.sources == [{"title": "A", "url": "https://a.cz"}]
    assert save.call_args.args[3] == "gemini-3.1-pro-preview"


def test_a_followup_offer_supersedes_an_open_offer(
    save: MagicMock, test_database: Any, test_conversation: Any
) -> None:
    old = build_offer({"question": "Q", "context": "", "sub_questions": ["a"]})
    old_id = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "x", research={"offer": old}
    ).id

    chat_save.save_message_to_db(
        "Report.",
        [],
        [],
        _usage(),
        test_conversation.id,
        test_conversation.user_id,
        "m",
        "q",
        "req",
        True,
    )

    assert test_database.get_message_by_id(old_id).research["offer"]["status"] == "superseded"
