"""Saving a deep-research report: run data, sources, follow-up offer, pricing."""

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent.deep_research.offer import build_offer
from src.api.helpers import chat_save
from src.api.schemas.common import MessageRole


@pytest.fixture
def save(test_database: Any, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(chat_save, "db", test_database)
    priced = MagicMock(return_value=0.05)
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


def _record(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    return next(r for r in caplog.records if r.getMessage() == message)


def test_a_report_logs_the_run_against_its_estimate(
    save: MagicMock,
    test_database: Any,
    test_conversation: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    usage = _usage(followup=False)
    usage["research_run"].update(
        items=[
            {"status": "done", "pages": 5},
            {"status": "failed", "pages": 0},
            {"status": "timed_out", "pages": 3},
            {"status": "skipped", "pages": 1},
        ],
        pages_read=9,
        board=[{"agent": 0}, {"agent": 1}],
        cache_hits=3,
        duration_ms=360_000,
        estimate={"minutes": 5, "cost_czk": 10},
        finished_early=True,
    )

    with caplog.at_level(logging.INFO):
        chat_save.save_message_to_db(
            "Report.",
            [],
            [],
            usage,
            test_conversation.id,
            test_conversation.user_id,
            "m",
            "Start deep research",
            "req",
            True,
        )

    run = _record(caplog, "Deep research run")
    assert (run.items, run.failed, run.timed_out, run.skipped) == (4, 1, 1, 1)
    assert (run.pages_read, run.board_entries, run.cache_hits) == (9, 2, 3)
    assert (run.duration_ms, run.finished_early, run.cost_usd) == (360_000, True, 0.05)
    assert run.estimate == {"minutes": 5, "cost_czk": 10}
    assert isinstance(run.cost_czk, float)


def test_superseding_an_offer_is_logged(
    save: MagicMock,
    test_database: Any,
    test_conversation: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old = build_offer({"question": "Q", "context": "", "sub_questions": ["a"]})
    old_id = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "x", research={"offer": old}
    ).id

    with caplog.at_level(logging.INFO):
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

    record = _record(caplog, "Deep research superseded")
    assert record.offer_message_id == old_id
    assert record.kind == "initial"
    assert record.seconds_open >= 0


def _offer_turn(run_now: bool) -> list[Any]:
    from langchain_core.messages import AIMessage

    args = {"question": "Q", "context": "", "sub_questions": ["a"], "run_now": run_now}
    return [
        AIMessage(
            content="", tool_calls=[{"name": "propose_deep_research", "args": args, "id": "p"}]
        )
    ]


@pytest.mark.parametrize(
    ("message_text", "autostart"),
    [("Ověř mi, jestli dává smysl mít návleky", False), ("Prozkoumej to důkladně", True)],
)
def test_an_offer_autostarts_only_when_the_user_asked(
    save: MagicMock, test_database: Any, test_conversation: Any, message_text: str, autostart: bool
) -> None:
    saved = chat_save.save_message_to_db(
        "Quick answer.",
        _offer_turn(run_now=True),
        [],
        {},
        test_conversation.id,
        test_conversation.user_id,
        "m",
        message_text,
        "req",
        True,
    )

    assert saved is not None
    offer = test_database.get_message_by_id(saved.message_id).research["offer"]
    assert offer["autostart"] is autostart
