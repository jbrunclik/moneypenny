"""The deep-research orchestrator with fake subagents."""

import threading
import time
from typing import Any

import pytest

from src.agent.cancellation import TurnCancelled, token_for
from src.agent.deep_research import orchestrator as orch
from src.agent.deep_research.board import ResearchBoard
from src.agent.deep_research.briefs import build_brief
from src.agent.deep_research.orchestrator import ItemResult, Orchestrator, merge_pages
from src.agent.deep_research.plan import DeepResearchPlan
from src.agent.source_pages import SourcePage
from src.config import Config


def _plan(n: int) -> DeepResearchPlan:
    items = [f"q{i}" for i in range(n)]
    return DeepResearchPlan(
        "offer-1", "Question?", "Praha", items, items, estimate={"minutes": 5, "cost_czk": 10}
    )


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 4)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 5.0)
    orch.reset_slots(8)


def _wait_cancellable(request_id: str, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        token = token_for(request_id)
        if token and token.cancelled:
            raise TurnCancelled
        time.sleep(0.01)


def _ok(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
    page = SourcePage(f"P{index}", f"https://p{index}.cz", "text")
    board.record_page(index, page)
    return ItemResult(
        index, "done", f"digest {index}", [page], {"input_tokens": 10, "output_tokens": 2}
    )


def _run(
    plan: DeepResearchPlan, events: list[dict[str, Any]]
) -> tuple[Orchestrator, list[ItemResult]]:
    o = Orchestrator(plan, events.append, run_id="run-1", today="2026-10-03", recent_turns="")
    return o, o.run()


def test_all_done_emits_events_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch, "run_subagent", _ok)
    events: list[dict[str, Any]] = []

    _, results = _run(_plan(3), events)

    assert [r.status for r in results] == ["done", "done", "done"]
    assert events[0] == {"type": "research_plan", "items": ["q0", "q1", "q2"]}
    done = [e for e in events if e["type"] == "research_item" and e["status"] == "done"]
    assert sorted(e["index"] for e in done) == [0, 1, 2] and all(e["pages"] == 1 for e in done)
    assert events[-1] == {"type": "research_sources", "count": 3}


def test_parallelism_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 2)
    running, peak, lock = [0], [0], threading.Lock()

    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    _run(_plan(4), [])

    assert peak[0] == 2


def test_second_run_waits_for_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    orch.reset_slots(2)
    release = threading.Event()

    def held(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        release.wait(2)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", held)
    first_events: list[dict[str, Any]] = []
    second_events: list[dict[str, Any]] = []
    first = threading.Thread(target=lambda: _run(_plan(2), first_events))
    first.start()
    time.sleep(0.1)
    second = threading.Thread(target=lambda: _run(_plan(2), second_events))
    second.start()
    time.sleep(0.2)
    assert any(e.get("status") == "waiting" for e in second_events)
    release.set()
    first.join(3)
    second.join(3)
    assert sum(1 for e in second_events if e.get("status") == "done") == 2


def test_an_item_past_its_deadline_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_SUBAGENT_TIMEOUT_SECONDS", 0.2)

    def maybe_slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        if index == 1:
            board.record_page(1, SourcePage("partial", "https://partial.cz", "half"))
            _wait_cancellable(request_id, 5)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", maybe_slow)
    o, results = _run(_plan(2), [])

    assert [r.status for r in results] == ["done", "timed_out"]
    assert [p.url for p in results[1].pages] == ["https://partial.cz"]


def test_failures_are_recorded_per_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def flaky(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        if index == 0:
            raise RuntimeError("search down")
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", flaky)

    _, results = _run(_plan(2), [])

    assert [r.status for r in results] == ["failed", "done"]


def test_finish_now_skips_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PARALLELISM", 1)

    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        _wait_cancellable(request_id, 0.3)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    o = Orchestrator(_plan(3), lambda e: None, run_id="run-2", today="2026-10-03", recent_turns="")
    threading.Timer(0.1, o.finish_now).start()

    results = o.run()

    assert results[0].status == "skipped"  # cut while running
    assert [r.status for r in results[1:]] == ["skipped", "skipped"]  # never started


def test_stop_raises_turn_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(brief: str, board: ResearchBoard, index: int, request_id: str) -> ItemResult:
        _wait_cancellable(request_id, 3)
        return ItemResult(index, "done", "", [], {})

    monkeypatch.setattr(orch, "run_subagent", slow)
    o = Orchestrator(_plan(2), lambda e: None, run_id="run-3", today="2026-10-03", recent_turns="")
    threading.Timer(0.1, o.stop).start()

    with pytest.raises(TurnCancelled):
        o.run()


def test_merge_pages_dedupes_caps_and_keeps_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "DEEP_RESEARCH_MAX_PAGES", 3)
    monkeypatch.setattr(Config, "DEEP_RESEARCH_PAGE_MAX_CHARS", 4)
    board = ResearchBoard()
    a, b, c, d = (SourcePage(n, f"https://{n}.cz", "long text") for n in "abcd")
    results = [ItemResult(0, "done", "", [a, b], {}), ItemResult(1, "done", "", [b, c, d], {})]

    merged = merge_pages(results, board)

    assert [p.url for p in merged] == ["https://a.cz", "https://b.cz", "https://c.cz"]
    assert merged[0].text == "long"


def test_brief_carries_context_date_and_previous_report() -> None:
    plan = _plan(2)
    plan.previous_report = "Round 1 found X."

    brief = build_brief(plan, 1, today="2026-10-03", recent_turns="user asked about agencies")

    for part in ("Question?", "Praha", "2026-10-03", "q1", "Round 1 found X.", "share_finding"):
        assert part in brief
