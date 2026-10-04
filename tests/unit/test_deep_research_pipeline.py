"""The deep-research pipeline: events in order, a final event the save path stores."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent.cancellation import TurnCancelled, register_token, token_for, unregister_token
from src.agent.deep_research import pipeline
from src.agent.deep_research.board import ResearchBoard
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.deep_research.subagent import ItemResult
from src.agent.grounding_check import GroundingOutcome
from src.agent.source_pages import SourcePage
from src.config import Config


def _plan() -> DeepResearchPlan:
    return DeepResearchPlan(
        "offer-1",
        "Which agency?",
        "Praha",
        ["prices", "speed"],
        ["prices", "speed", "x"],
        estimate={"minutes": 5, "cost_czk": 10},
    )


class FakeOrchestrator:
    outcome: Any = "ok"

    def __init__(
        self, plan: DeepResearchPlan, emit: Any, run_id: str, today: str, recent_turns: str
    ) -> None:
        self.plan, self.emit = plan, emit
        self.board = ResearchBoard()
        self.finished_early = False

    def spent(self) -> list[dict[str, int]]:
        return [{"input_tokens": 70, "output_tokens": 7, "cached_input_tokens": 0}]

    def run(self) -> list[ItemResult]:
        self.emit({"type": "research_plan", "items": self.plan.sub_questions})
        if FakeOrchestrator.outcome == "stop":
            raise TurnCancelled
        if FakeOrchestrator.outcome == "quiet":
            time.sleep(0.5)
        if FakeOrchestrator.outcome == "nothing":
            return [ItemResult(i, "timed_out", "", [], {}) for i in range(2)]
        page = SourcePage("A", "https://a.cz", "alpha")
        self.board.record_page(0, page)
        status = "failed" if FakeOrchestrator.outcome == "all_failed" else "done"
        usage = {"input_tokens": 50, "output_tokens": 5, "cached_input_tokens": 0}
        return [ItemResult(i, status, f"digest {i}", [page], usage) for i in range(2)]

    def finish_now(self) -> None:
        self.finished_early = True

    stopped = False

    def stop(self) -> None:
        FakeOrchestrator.stopped = True


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    FakeOrchestrator.outcome = "ok"
    FakeOrchestrator.stopped = False
    monkeypatch.setattr(pipeline, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(pipeline, "writer_model", MagicMock())

    def stream(_messages: Any, _model: Any, totals: Any) -> Any:
        totals.input_tokens += 900
        totals.output_tokens += 300
        yield "Report "
        yield "text."

    check = MagicMock(
        return_value=GroundingOutcome(
            annotations=[{"type": "claim", "verdict": "supported", "quote": "Report", "source": 1}],
            summary={"checked": True, "source_count": 1},
            usage={
                "model": "lite",
                "input_tokens": 1,
                "output_tokens": 1,
                "cached_input_tokens": 0,
            },
        )
    )
    followups = MagicMock(
        return_value=(
            ["next?"],
            {"input_tokens": 300, "output_tokens": 20, "cached_input_tokens": 0},
        )
    )
    monkeypatch.setattr(pipeline, "stream_report", stream)
    monkeypatch.setattr(pipeline, "check_grounding_pages", check)
    monkeypatch.setattr(pipeline, "extract_followups", followups)
    return {"check": check, "followups": followups}


def _events(**kwargs: Any) -> list[dict[str, Any]]:
    return list(pipeline.run_deep_research(_plan(), "", request_id="req-1", **kwargs))


def test_events_in_order_and_a_final_event(fakes: dict[str, MagicMock]) -> None:
    events = _events()
    types = [e["type"] for e in events]

    assert types[0] == "research_plan"
    assert types.index("research_writing") < types.index("token") < types.index("grounding_started")
    assert types[-1] == "final"
    final = events[-1]
    assert final["content"] == "Report text."
    usage = final["usage_info"]
    assert (
        usage["input_tokens"] == 900 and usage["answer_model"] == Config.DEEP_RESEARCH_WRITER_MODEL
    )
    assert usage["grounding"]["annotations"][0]["source"] == 1
    # Every started subagent (orchestrator.spent), then the follow-up extraction
    assert [u["input_tokens"] for u in usage["deep_research_usage"]] == [70, 300]
    assert usage["research_sources"] == [{"title": "A", "url": "https://a.cz"}]
    run = usage["research_run"]
    assert run["sub_questions"] == ["prices", "speed"]
    assert run["offered_sub_questions"] == ["prices", "speed", "x"]
    assert [i["status"] for i in run["items"]] == ["done", "done"]
    assert run["pages_read"] == 1 and run["round"] == 1
    offer = run["followup"]
    assert (
        offer["sub_questions"] == ["next?"] and offer["kind"] == "followup" and offer["round"] == 2
    )


def test_deep_research_grounding_limits(fakes: dict[str, MagicMock]) -> None:
    _events()
    kwargs = fakes["check"].call_args.kwargs
    assert kwargs["max_source_chars"] == Config.DEEP_RESEARCH_GROUNDING_MAX_SOURCE_CHARS
    assert kwargs["max_claims"] == Config.DEEP_RESEARCH_GROUNDING_MAX_CLAIMS
    # A 200k-char report check needs longer than a chat turn's 10 s
    assert kwargs["timeout_seconds"] == Config.DEEP_RESEARCH_GROUNDING_TIMEOUT_SECONDS


def test_all_items_failed_skips_the_writer(fakes: dict[str, MagicMock]) -> None:
    FakeOrchestrator.outcome = "all_failed"

    events = _events()

    assert "research_writing" not in [e["type"] for e in events]
    final = events[-1]
    assert final["content"].startswith("Research failed")
    assert [i["status"] for i in final["usage_info"]["research_run"]["items"]] == [
        "failed",
        "failed",
    ]
    fakes["check"].assert_not_called()


def test_stop_ends_with_a_note_and_no_report(fakes: dict[str, MagicMock]) -> None:
    FakeOrchestrator.outcome = "stop"

    final = _events()[-1]

    assert final["content"] == "Research stopped."
    assert final["stop_reason"] == "user"
    fakes["check"].assert_not_called()


def test_no_followups_means_no_followup_offer(fakes: dict[str, MagicMock]) -> None:
    fakes["followups"].return_value = ([], {})

    run = _events()[-1]["usage_info"]["research_run"]

    assert "followup" not in run


def test_a_run_that_found_nothing_skips_the_writer(fakes: dict[str, MagicMock]) -> None:
    """Every item cut with no pages and no digest: no report from nothing."""
    FakeOrchestrator.outcome = "nothing"

    events = _events()

    assert "research_writing" not in [e["type"] for e in events]
    assert events[-1]["content"].startswith("Research failed")
    assert events[-1]["usage_info"]["research_failed"] is True
    fakes["check"].assert_not_called()


def test_spend_is_recorded_on_every_ending(fakes: dict[str, MagicMock]) -> None:
    """Stop, all-failed and a report all price what the subagents spent."""
    for outcome in ("stop", "all_failed", "ok"):
        FakeOrchestrator.outcome = outcome
        usage = _events()[-1]["usage_info"]
        assert usage["deep_research_usage"][0]["input_tokens"] == 70, outcome


def test_a_quiet_research_phase_sends_liveness_ticks(
    fakes: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No event for a while (slow subagents) must not look like a dead stream."""
    monkeypatch.setattr(pipeline, "TICK_SECONDS", 0.1)
    FakeOrchestrator.outcome = "quiet"

    types = [e["type"] for e in _events()]

    assert types.count("research_tick") >= 2
    assert types.index("research_tick") < types.index("research_writing")


def test_an_abandoned_run_stops_its_research(fakes: dict[str, MagicMock]) -> None:
    """The producer's deadline closes the generator: subagents must not bill on."""
    FakeOrchestrator.outcome = "quiet"
    gen = pipeline.run_deep_research(_plan(), "", request_id="req-1")
    next(gen)  # research_plan

    gen.close()

    assert FakeOrchestrator.stopped is True


def test_finish_now_is_checked_about_once_a_second(
    fakes: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each check reads the kv store; 0.2 s polling was 5 reads a second per run."""
    monkeypatch.setattr(pipeline, "FINISH_CHECK_SECONDS", 1.0)
    FakeOrchestrator.outcome = "quiet"  # research takes 0.5 s
    checks = MagicMock(return_value=False)

    _events(finish_requested=checks)

    assert checks.call_count <= 2


def test_the_followup_extraction_is_priced(fakes: dict[str, MagicMock]) -> None:
    usage = _events()[-1]["usage_info"]["deep_research_usage"]

    assert {
        "model": Config.DEEP_RESEARCH_SUBAGENT_MODEL,
        "input_tokens": 300,
        "output_tokens": 20,
        "cached_input_tokens": 0,
    } in usage


def test_stop_while_writing_prices_the_partial_report_at_the_writer(
    fakes: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    register_token("req-1")

    def stream(_messages: Any, _model: Any, totals: Any) -> Any:
        totals.input_tokens += 900
        yield "Half a report"
        token_for("req-1").cancel()  # the user pressed Stop mid-writing
        yield " never sent"

    monkeypatch.setattr(pipeline, "stream_report", stream)
    try:
        final = _events()[-1]
    finally:
        unregister_token("req-1")

    assert final["stop_reason"] == "user"
    assert final["usage_info"]["answer_model"] == Config.DEEP_RESEARCH_WRITER_MODEL
